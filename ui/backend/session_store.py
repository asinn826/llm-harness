"""Session store: SQLite-backed persistent conversation history.

Stores sessions and messages with full-text search support.
Thread-safe — uses a connection per call with WAL mode.
"""
import json
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


_DB_DIR = Path.home() / ".llm_harness"
_DB_PATH = _DB_DIR / "sessions.db"
DEFAULT_PROJECT_ID = "default"
DEFAULT_PROJECT_NAME = "Imported conversations"
_IMMUTABLE_HF_REVISION_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")


def _get_conn() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_default INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_compare INTEGER DEFAULT 0,
            project_id TEXT REFERENCES projects(id) ON DELETE SET NULL
        );
    """)

    # Existing databases predate projects. SQLite's CREATE TABLE IF NOT EXISTS
    # does not add new columns, so migrate the sessions table in place.
    session_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    if "project_id" not in session_columns:
        conn.execute("ALTER TABLE sessions ADD COLUMN project_id TEXT")

    conn.executescript("""

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model_id TEXT,
            tool_name TEXT,
            tool_args TEXT,
            tokens_generated INTEGER,
            generation_time_ms INTEGER,
            created_at TEXT NOT NULL,
            position INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS comparison_models (
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            model_id TEXT NOT NULL,
            backend TEXT,
            revision TEXT,
            PRIMARY KEY (session_id, position),
            UNIQUE (session_id, model_id)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, position);

        CREATE INDEX IF NOT EXISTS idx_sessions_project
            ON sessions(project_id, updated_at);
    """)
    # FTS table for full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
        USING fts5(content, content=messages, content_rowid=rowid)
    """)

    now = datetime.now().isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO projects
           (id, name, created_at, updated_at, is_default)
           VALUES (?, ?, ?, ?, 1)""",
        (DEFAULT_PROJECT_ID, DEFAULT_PROJECT_NAME, now, now),
    )
    conn.execute(
        "UPDATE sessions SET project_id = ? WHERE project_id IS NULL OR project_id = ''",
        (DEFAULT_PROJECT_ID,),
    )
    conn.commit()
    conn.close()


def _project_with_counts(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    project = dict(row)
    counts = conn.execute(
        """SELECT COUNT(*) AS session_count,
                  SUM(CASE WHEN is_compare = 1 THEN 1 ELSE 0 END) AS comparison_count
           FROM sessions WHERE project_id = ?""",
        (project["id"],),
    ).fetchone()
    project["session_count"] = counts["session_count"] or 0
    project["comparison_count"] = counts["comparison_count"] or 0
    return project


def create_project(name: str) -> dict:
    """Create a project that can own chats and comparison threads."""
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Project name cannot be empty")

    conn = _get_conn()
    project_id = str(uuid.uuid4())[:12]
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO projects (id, name, created_at, updated_at, is_default)
           VALUES (?, ?, ?, ?, 0)""",
        (project_id, cleaned_name, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    project = _project_with_counts(conn, row)
    conn.close()
    return project


def get_project(project_id: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    project = _project_with_counts(conn, row) if row else None
    conn.close()
    return project


def list_projects() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM projects ORDER BY is_default DESC, updated_at DESC"
    ).fetchall()
    projects = [_project_with_counts(conn, row) for row in rows]
    conn.close()
    return projects


def _normalize_comparison_models(
    models: Optional[list],
    *,
    require_immutable_revision: bool = True,
) -> list[dict]:
    """Validate and normalize an ordered comparison lineup before writing."""
    normalized = []
    seen = set()
    for model in models or []:
        if isinstance(model, str):
            model_id = model.strip()
            backend = None
            revision = None
        elif isinstance(model, dict):
            model_id = model.get("model_id") or model.get("id")
            model_id = model_id.strip() if isinstance(model_id, str) else ""
            backend = model.get("backend")
            revision = model.get("revision")
        else:
            raise ValueError("Invalid comparison model")

        if not model_id:
            raise ValueError("Every comparison model requires model_id")
        if model_id in seen:
            raise ValueError(f"Duplicate comparison model: {model_id}")
        seen.add(model_id)

        revision = revision.strip() if isinstance(revision, str) else ""
        if (
            require_immutable_revision
            and not _IMMUTABLE_HF_REVISION_RE.fullmatch(revision)
        ):
            raise ValueError(
                f"Comparison model {model_id} requires an immutable Hugging Face "
                "commit revision"
            )
        normalized.append({
            "model_id": model_id,
            "backend": backend,
            "revision": revision.lower() or None,
        })
    return normalized


def create_session(
    title: str = "New session",
    is_compare: bool = False,
    project_id: Optional[str] = None,
    models: Optional[list[dict]] = None,
) -> dict:
    """Create a new session. Returns the session dict."""
    normalized_models = _normalize_comparison_models(models)
    if normalized_models and not is_compare:
        raise ValueError("Comparison models can only be set on compare sessions")

    conn = _get_conn()
    project_id = project_id or DEFAULT_PROJECT_ID
    project = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        conn.close()
        raise ValueError(f"Project {project_id} not found")

    session_id = str(uuid.uuid4())[:12]
    now = datetime.now().isoformat()
    try:
        conn.execute(
            """INSERT INTO sessions
               (id, title, created_at, updated_at, is_compare, project_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, title, now, now, int(is_compare), project_id),
        )
        for position, model in enumerate(normalized_models):
            conn.execute(
                """INSERT INTO comparison_models
                   (session_id, position, model_id, backend, revision)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, position, model["model_id"], model["backend"], model["revision"]),
            )
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (now, project_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return get_session(session_id)


def get_comparison_models(session_id: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        """SELECT session_id, position, model_id, backend, revision
           FROM comparison_models
           WHERE session_id = ?
           ORDER BY position ASC""",
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def set_comparison_models(session_id: str, models: list[dict]) -> list[dict]:
    """Replace a comparison's ordered model lineup."""
    conn = _get_conn()
    session = conn.execute(
        "SELECT id, is_compare FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not session:
        conn.close()
        raise ValueError(f"Session {session_id} not found")
    if not session["is_compare"]:
        conn.close()
        raise ValueError("Comparison models can only be set on compare sessions")

    existing_lineup_count = conn.execute(
        "SELECT COUNT(*) AS count FROM comparison_models WHERE session_id = ?",
        (session_id,),
    ).fetchone()["count"]
    historical_rows = conn.execute(
        """SELECT model_id, MIN(position) AS first_position
           FROM messages
           WHERE session_id = ? AND model_id IS NOT NULL
           GROUP BY model_id
           ORDER BY first_position ASC""",
        (session_id,),
    ).fetchall()
    historical_model_ids = [row["model_id"] for row in historical_rows]

    # Pre-revision comparisons inferred their lineup from model-attributed
    # messages. Permit a one-time, identity-preserving migration of that exact
    # historical lineup; all genuinely new lineups must be commit-pinned.
    is_legacy_history_migration = (
        existing_lineup_count == 0 and bool(historical_model_ids)
    )
    try:
        normalized_models = _normalize_comparison_models(
            models,
            require_immutable_revision=not is_legacy_history_migration,
        )
    except Exception:
        conn.close()
        raise
    if is_legacy_history_migration:
        submitted_model_ids = [model["model_id"] for model in normalized_models]
        if submitted_model_ids != historical_model_ids:
            conn.close()
            raise ValueError(
                "Legacy comparison lineup must match its historical model IDs"
            )

    try:
        conn.execute("DELETE FROM comparison_models WHERE session_id = ?", (session_id,))
        for position, model in enumerate(normalized_models):
            conn.execute(
                """INSERT INTO comparison_models
                   (session_id, position, model_id, backend, revision)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, position, model["model_id"], model["backend"], model["revision"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    return get_comparison_models(session_id)


def _session_with_metadata(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    session = dict(row)
    stats = conn.execute(
        "SELECT COUNT(*) AS msg_count FROM messages WHERE session_id = ?",
        (session["id"],),
    ).fetchone()
    session["message_count"] = stats["msg_count"] or 0

    lineup_rows = conn.execute(
        """SELECT session_id, position, model_id, backend, revision
           FROM comparison_models
           WHERE session_id = ? ORDER BY position ASC""",
        (session["id"],),
    ).fetchall()
    lineup = [dict(model) for model in lineup_rows]
    session["comparison_models"] = lineup

    if lineup:
        session["models"] = [model["model_id"] for model in lineup]
    else:
        model_rows = conn.execute(
            """SELECT model_id, MIN(position) AS first_position
               FROM messages
               WHERE session_id = ? AND model_id IS NOT NULL
               GROUP BY model_id
               ORDER BY first_position ASC""",
            (session["id"],),
        ).fetchall()
        session["models"] = [model["model_id"] for model in model_rows]
    return session


def get_session(session_id: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    session = _session_with_metadata(conn, row) if row else None
    conn.close()
    return session


def list_sessions(
    limit: int = 50,
    offset: int = 0,
    project_id: Optional[str] = None,
    is_compare: Optional[bool] = None,
) -> list[dict]:
    conn = _get_conn()
    where = []
    params: list = []
    if project_id is not None:
        where.append("project_id = ?")
        params.append(project_id)
    if is_compare is not None:
        where.append("is_compare = ?")
        params.append(int(is_compare))
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    params.extend([limit, offset])
    rows = conn.execute(
        f"SELECT * FROM sessions{where_sql} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    sessions = [_session_with_metadata(conn, row) for row in rows]

    conn.close()
    return sessions


def delete_session(session_id: str) -> bool:
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def update_session_title(session_id: str, title: str):
    conn = _get_conn()
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
        (title, now, session_id),
    )
    conn.execute(
        """UPDATE projects SET updated_at = ?
           WHERE id = (SELECT project_id FROM sessions WHERE id = ?)""",
        (now, session_id),
    )
    conn.commit()
    conn.close()


def add_message(
    session_id: str,
    role: str,
    content: str,
    model_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_args: Optional[dict] = None,
    tokens_generated: Optional[int] = None,
    generation_time_ms: Optional[int] = None,
) -> dict:
    """Add a message to a session. Returns the message dict."""
    conn = _get_conn()

    # Get next position
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 as next_pos FROM messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    position = row["next_pos"]

    msg_id = str(uuid.uuid4())[:12]
    now = datetime.now().isoformat()
    args_json = json.dumps(tool_args) if tool_args else None

    conn.execute(
        """INSERT INTO messages
           (id, session_id, role, content, model_id, tool_name, tool_args,
            tokens_generated, generation_time_ms, created_at, position)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (msg_id, session_id, role, content, model_id, tool_name, args_json,
         tokens_generated, generation_time_ms, now, position),
    )

    # Update FTS index
    conn.execute(
        "INSERT INTO messages_fts(rowid, content) VALUES (last_insert_rowid(), ?)",
        (content,),
    )

    # Update session timestamp
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (now, session_id),
    )
    conn.execute(
        """UPDATE projects SET updated_at = ?
           WHERE id = (SELECT project_id FROM sessions WHERE id = ?)""",
        (now, session_id),
    )

    conn.commit()
    msg = dict(conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone())
    conn.close()
    return msg


def get_messages(session_id: str, limit: int = 1000, offset: int = 0) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY position ASC LIMIT ? OFFSET ?",
        (session_id, limit, offset),
    ).fetchall()
    conn.close()
    messages = []
    for r in rows:
        m = dict(r)
        if m["tool_args"]:
            try:
                m["tool_args"] = json.loads(m["tool_args"])
            except (json.JSONDecodeError, TypeError):
                pass
        messages.append(m)
    return messages


def search_sessions(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across all messages. Returns matching sessions."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT DISTINCT s.*
        FROM messages_fts fts
        JOIN messages m ON m.rowid = fts.rowid
        JOIN sessions s ON s.id = m.session_id
        WHERE messages_fts MATCH ?
        ORDER BY s.updated_at DESC
        LIMIT ?
    """, (query, limit)).fetchall()
    sessions = [_session_with_metadata(conn, row) for row in rows]
    conn.close()
    return sessions


def fork_session(session_id: str, from_position: int) -> dict:
    """Fork a session at a given message position. Returns the new session."""
    conn = _get_conn()

    # Get original session
    original = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not original:
        conn.close()
        raise ValueError(f"Session {session_id} not found")

    # Create forked session
    new_id = str(uuid.uuid4())[:12]
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO sessions
           (id, title, created_at, updated_at, is_compare, project_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (new_id, f"{original['title']} (fork)", now, now,
         original["is_compare"], original["project_id"]),
    )

    lineup = conn.execute(
        """SELECT position, model_id, backend, revision
           FROM comparison_models WHERE session_id = ? ORDER BY position ASC""",
        (session_id,),
    ).fetchall()
    for model in lineup:
        conn.execute(
            """INSERT INTO comparison_models
               (session_id, position, model_id, backend, revision)
               VALUES (?, ?, ?, ?, ?)""",
            (new_id, model["position"], model["model_id"],
             model["backend"], model["revision"]),
        )

    # Copy messages up to the fork point
    messages = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? AND position <= ? ORDER BY position ASC",
        (session_id, from_position),
    ).fetchall()

    for msg in messages:
        msg_id = str(uuid.uuid4())[:12]
        conn.execute(
            """INSERT INTO messages
               (id, session_id, role, content, model_id, tool_name, tool_args,
                tokens_generated, generation_time_ms, created_at, position)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (msg_id, new_id, msg["role"], msg["content"], msg["model_id"],
             msg["tool_name"], msg["tool_args"], msg["tokens_generated"],
             msg["generation_time_ms"], now, msg["position"]),
        )
        conn.execute(
            "INSERT INTO messages_fts(rowid, content) VALUES (last_insert_rowid(), ?)",
            (msg["content"],),
        )

    conn.commit()
    conn.close()
    return get_session(new_id)


def get_conversation_list(session_id: str) -> list[dict]:
    """Get messages in the format expected by the harness (role + content dicts)."""
    messages = get_messages(session_id)
    return [{"role": m["role"], "content": m["content"]} for m in messages]


# Initialize on import
init_db()

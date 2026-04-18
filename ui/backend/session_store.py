"""Session store: SQLite-backed persistent conversation history.

Stores sessions and messages with full-text search support.
Thread-safe — uses a connection per call with WAL mode.
"""
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


_DB_DIR = Path.home() / ".llm_harness"
_DB_PATH = _DB_DIR / "sessions.db"


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
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_compare INTEGER DEFAULT 0
        );

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

        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, position);
    """)
    # FTS table for full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
        USING fts5(content, content=messages, content_rowid=rowid)
    """)
    conn.commit()
    conn.close()


def create_session(title: str = "New session", is_compare: bool = False) -> dict:
    """Create a new session. Returns the session dict."""
    conn = _get_conn()
    session_id = str(uuid.uuid4())[:12]
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at, is_compare) VALUES (?, ?, ?, ?, ?)",
        (session_id, title, now, now, int(is_compare)),
    )
    conn.commit()
    session = dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())
    conn.close()
    return session


def get_session(session_id: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_sessions(limit: int = 50, offset: int = 0) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    sessions = [dict(r) for r in rows]

    # Attach model info and message count to each session
    for s in sessions:
        stats = conn.execute("""
            SELECT COUNT(*) as msg_count,
                   GROUP_CONCAT(DISTINCT model_id) as models
            FROM messages WHERE session_id = ? AND model_id IS NOT NULL
        """, (s["id"],)).fetchone()
        s["message_count"] = stats["msg_count"]
        s["models"] = [m for m in (stats["models"] or "").split(",") if m]

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
    conn.execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
        (title, datetime.now().isoformat(), session_id),
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
    conn.close()
    return [dict(r) for r in rows]


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
        "INSERT INTO sessions (id, title, created_at, updated_at, is_compare) VALUES (?, ?, ?, ?, ?)",
        (new_id, f"{original['title']} (fork)", now, now, original["is_compare"]),
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

    conn.commit()
    session = dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (new_id,)).fetchone())
    conn.close()
    return session


def get_conversation_list(session_id: str) -> list[dict]:
    """Get messages in the format expected by the harness (role + content dicts)."""
    messages = get_messages(session_id)
    return [{"role": m["role"], "content": m["content"]} for m in messages]


# Initialize on import
init_db()

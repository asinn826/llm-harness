"""Tests for the session store (SQLite-backed conversation history).

Uses a temporary database for each test to ensure isolation.
"""
import json
import os
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch

# Override the DB path before importing session_store
_TEST_DB = Path("/tmp/llm_harness_test_sessions.db")


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure a fresh database for each test."""
    if _TEST_DB.exists():
        _TEST_DB.unlink()
    with patch("ui.backend.session_store._DB_PATH", _TEST_DB):
        from ui.backend import session_store
        session_store._DB_PATH = _TEST_DB
        session_store.init_db()
        yield session_store
    if _TEST_DB.exists():
        _TEST_DB.unlink()


def test_create_session(clean_db):
    store = clean_db
    session = store.create_session(title="Test session")
    assert session["title"] == "Test session"
    assert session["id"]
    assert session["created_at"]
    assert session["is_compare"] == 0


def test_create_compare_session(clean_db):
    store = clean_db
    session = store.create_session(title="Compare test", is_compare=True)
    assert session["is_compare"] == 1


def test_init_db_creates_default_project_and_backfills_legacy_sessions(clean_db):
    store = clean_db

    # Recreate the minimal pre-project schema to exercise the in-place migration.
    if _TEST_DB.exists():
        _TEST_DB.unlink()
    conn = sqlite3.connect(_TEST_DB)
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_compare INTEGER DEFAULT 0
        );
        INSERT INTO sessions
            (id, title, created_at, updated_at, is_compare)
        VALUES
            ('legacy', 'Legacy comparison', '2026-01-01', '2026-01-01', 1);
    """)
    conn.commit()
    conn.close()

    store.init_db()

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0]["id"] == store.DEFAULT_PROJECT_ID
    assert projects[0]["name"] == "Imported conversations"
    assert projects[0]["is_default"] == 1

    migrated = store.get_session("legacy")
    assert migrated["project_id"] == store.DEFAULT_PROJECT_ID


def test_create_project_and_project_scoped_session(clean_db):
    store = clean_db
    project = store.create_project("Local coding models")
    session = store.create_session(
        title="Compare code completion",
        is_compare=True,
        project_id=project["id"],
    )

    assert store.get_project(project["id"])["name"] == "Local coding models"
    assert session["project_id"] == project["id"]
    assert store.list_sessions(project_id=project["id"])[0]["id"] == session["id"]
    assert store.list_sessions(project_id=store.DEFAULT_PROJECT_ID) == []


def test_list_sessions_can_filter_comparisons(clean_db):
    store = clean_db
    store.create_session(title="Legacy chat", is_compare=False)
    comparison = store.create_session(title="Model comparison", is_compare=True)

    comparisons = store.list_sessions(is_compare=True)
    chats = store.list_sessions(is_compare=False)

    assert [s["id"] for s in comparisons] == [comparison["id"]]
    assert [s["title"] for s in chats] == ["Legacy chat"]


def test_comparison_models_are_ordered_and_attached_to_session(clean_db):
    store = clean_db
    session = store.create_session(title="Lineup", is_compare=True)

    store.set_comparison_models(session["id"], [
        {"model_id": "org/model-b", "backend": "hf", "revision": "b" * 40},
        {"model_id": "org/model-a", "backend": "mlx", "revision": "a" * 40},
    ])

    lineup = store.get_comparison_models(session["id"])
    assert [m["model_id"] for m in lineup] == ["org/model-b", "org/model-a"]
    assert lineup[0]["position"] == 0
    assert lineup[1]["backend"] == "mlx"

    restored = store.get_session(session["id"])
    assert restored["models"] == ["org/model-b", "org/model-a"]
    assert restored["comparison_models"] == lineup


def test_get_session(clean_db):
    store = clean_db
    created = store.create_session(title="Lookup test")
    found = store.get_session(created["id"])
    assert found is not None
    assert found["title"] == "Lookup test"


def test_get_session_not_found(clean_db):
    store = clean_db
    assert store.get_session("nonexistent") is None


def test_list_sessions_ordered_by_update(clean_db):
    store = clean_db
    s1 = store.create_session(title="First")
    s2 = store.create_session(title="Second")
    s3 = store.create_session(title="Third")

    sessions = store.list_sessions()
    assert len(sessions) == 3
    # Most recent first
    assert sessions[0]["title"] == "Third"
    assert sessions[2]["title"] == "First"


def test_delete_session(clean_db):
    store = clean_db
    session = store.create_session(title="Delete me")
    assert store.delete_session(session["id"])
    assert store.get_session(session["id"]) is None


def test_delete_nonexistent_session(clean_db):
    store = clean_db
    assert not store.delete_session("nonexistent")


def test_update_session_title(clean_db):
    store = clean_db
    session = store.create_session(title="Old title")
    store.update_session_title(session["id"], "New title")
    updated = store.get_session(session["id"])
    assert updated["title"] == "New title"


def test_add_and_get_messages(clean_db):
    store = clean_db
    session = store.create_session(title="Chat test")

    store.add_message(session["id"], "user", "Hello")
    store.add_message(session["id"], "assistant", "Hi there!", model_id="qwen-4b")
    store.add_message(session["id"], "user", "What's 2+2?")

    messages = store.get_messages(session["id"])
    assert len(messages) == 3
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"
    assert messages[0]["position"] == 0
    assert messages[1]["role"] == "assistant"
    assert messages[1]["model_id"] == "qwen-4b"
    assert messages[1]["position"] == 1
    assert messages[2]["position"] == 2


def test_add_tool_message(clean_db):
    store = clean_db
    session = store.create_session()
    msg = store.add_message(
        session["id"], "tool", "result: 4",
        tool_name="calculator",
        tool_args={"expression": "2+2"},
    )
    assert msg["tool_name"] == "calculator"

    messages = store.get_messages(session["id"])
    assert messages[0]["tool_args"] == {"expression": "2+2"}


def test_message_with_metrics(clean_db):
    store = clean_db
    session = store.create_session()
    msg = store.add_message(
        session["id"], "assistant", "The answer is 4",
        model_id="qwen-4b",
        tokens_generated=15,
        generation_time_ms=230,
    )
    assert msg["tokens_generated"] == 15
    assert msg["generation_time_ms"] == 230


def test_list_sessions_includes_model_info(clean_db):
    store = clean_db
    session = store.create_session(title="Multi-model")
    store.add_message(session["id"], "assistant", "Response 1", model_id="qwen-4b")
    store.add_message(session["id"], "assistant", "Response 2", model_id="gemma-4")

    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert set(sessions[0]["models"]) == {"qwen-4b", "gemma-4"}
    assert sessions[0]["message_count"] == 2


def test_fork_session(clean_db):
    store = clean_db
    original = store.create_session(title="Original")
    store.add_message(original["id"], "user", "Message 1")
    store.add_message(original["id"], "assistant", "Response 1", model_id="qwen-4b")
    store.add_message(original["id"], "user", "Message 2")
    store.add_message(original["id"], "assistant", "Response 2", model_id="qwen-4b")

    # Fork after position 1 (keeps first 2 messages)
    forked = store.fork_session(original["id"], from_position=1)
    assert forked["title"] == "Original (fork)"
    assert forked["id"] != original["id"]

    forked_msgs = store.get_messages(forked["id"])
    assert len(forked_msgs) == 2
    assert forked_msgs[0]["content"] == "Message 1"
    assert forked_msgs[1]["content"] == "Response 1"

    # Original unchanged
    original_msgs = store.get_messages(original["id"])
    assert len(original_msgs) == 4


def test_fork_nonexistent_session(clean_db):
    store = clean_db
    with pytest.raises(ValueError, match="not found"):
        store.fork_session("nonexistent", from_position=0)


def test_search_sessions(clean_db):
    store = clean_db
    s1 = store.create_session(title="Auth debug")
    store.add_message(s1["id"], "user", "Fix the authentication middleware")
    s2 = store.create_session(title="Calendar")
    store.add_message(s2["id"], "user", "What's on my calendar today?")

    results = store.search_sessions("authentication")
    assert len(results) == 1
    assert results[0]["title"] == "Auth debug"


def test_get_conversation_list(clean_db):
    store = clean_db
    session = store.create_session()
    store.add_message(session["id"], "user", "Hello")
    store.add_message(session["id"], "assistant", "Hi!")

    conv = store.get_conversation_list(session["id"])
    assert conv == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
    ]


def test_delete_session_cascades_messages(clean_db):
    store = clean_db
    session = store.create_session()
    store.add_message(session["id"], "user", "Hello")
    store.add_message(session["id"], "assistant", "Hi!")

    store.delete_session(session["id"])
    assert store.get_messages(session["id"]) == []

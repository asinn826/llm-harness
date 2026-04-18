"""Tests for the FastAPI server endpoints.

Uses TestClient for REST endpoints and mock model manager
to avoid loading real models during tests.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Override DB path before importing
_TEST_DB = Path("/tmp/llm_harness_test_server.db")


@pytest.fixture(autouse=True)
def clean_db():
    if _TEST_DB.exists():
        _TEST_DB.unlink()
    with patch("ui.backend.session_store._DB_PATH", _TEST_DB):
        from ui.backend import session_store
        session_store._DB_PATH = _TEST_DB
        session_store.init_db()
        yield
    if _TEST_DB.exists():
        _TEST_DB.unlink()


@pytest.fixture
def mock_model_manager():
    """Mock the model manager to avoid loading real models."""
    from ui.backend.model_manager import ModelInfo
    with patch("ui.backend.server.model_manager") as mm:
        mm.current_model = ModelInfo(model_id="test-model", backend="mlx", status="ready")
        mm.is_loaded = True
        mm.list_models.return_value = {
            "recommended": [
                {"id": "test/model-1", "name": "Test Model 1", "backend": "mlx",
                 "is_cached": True, "is_loaded": True},
            ],
            "cached": [],
            "current": "test/model-1",
            "current_backend": "mlx",
        }
        yield mm


@pytest.fixture
def client(mock_model_manager):
    from fastapi.testclient import TestClient
    from ui.backend.server import app
    return TestClient(app)


# ── Health ─────────────────────────────────────────────────────────────────

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Models ─────────────────────────────────────────────────────────────────

def test_list_models(client, mock_model_manager):
    resp = client.get("/models")
    assert resp.status_code == 200
    data = resp.json()
    assert "recommended" in data
    assert "cached" in data
    assert data["current"] == "test/model-1"


def test_current_model(client, mock_model_manager):
    resp = client.get("/models/current")
    assert resp.status_code == 200
    data = resp.json()
    assert data["loaded"] is True
    assert data["model_id"] == "test-model"


def test_current_model_none(client, mock_model_manager):
    mock_model_manager.current_model = None
    resp = client.get("/models/current")
    data = resp.json()
    assert data["loaded"] is False


def test_unload_model(client, mock_model_manager):
    resp = client.post("/models/unload")
    assert resp.status_code == 200
    mock_model_manager.unload_model.assert_called_once()


# ── Sessions ───────────────────────────────────────────────────────────────

def test_create_session(client):
    resp = client.post("/sessions", json={"title": "Test session"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test session"
    assert "id" in data


def test_list_sessions(client):
    client.post("/sessions", json={"title": "Session 1"})
    client.post("/sessions", json={"title": "Session 2"})
    resp = client.get("/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


def test_get_session(client):
    create_resp = client.post("/sessions", json={"title": "Lookup"})
    session_id = create_resp.json()["id"]
    resp = client.get(f"/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Lookup"


def test_get_session_not_found(client):
    resp = client.get("/sessions/nonexistent")
    assert resp.status_code == 404


def test_delete_session(client):
    create_resp = client.post("/sessions", json={"title": "Delete me"})
    session_id = create_resp.json()["id"]
    resp = client.delete(f"/sessions/{session_id}")
    assert resp.status_code == 200

    resp = client.get(f"/sessions/{session_id}")
    assert resp.status_code == 404


def test_update_session_title(client):
    create_resp = client.post("/sessions", json={"title": "Old"})
    session_id = create_resp.json()["id"]
    resp = client.patch(f"/sessions/{session_id}", json={"title": "New"})
    assert resp.status_code == 200

    resp = client.get(f"/sessions/{session_id}")
    assert resp.json()["title"] == "New"


def test_fork_session(client):
    # Create session with messages
    create_resp = client.post("/sessions", json={"title": "Original"})
    session_id = create_resp.json()["id"]

    from ui.backend.session_store import add_message
    add_message(session_id, "user", "Hello")
    add_message(session_id, "assistant", "Hi!", model_id="test")
    add_message(session_id, "user", "More")

    resp = client.post(f"/sessions/{session_id}/fork", json={"from_position": 1})
    assert resp.status_code == 200
    forked = resp.json()
    assert forked["title"] == "Original (fork)"

    msgs_resp = client.get(f"/sessions/{forked['id']}/messages")
    assert len(msgs_resp.json()) == 2


def test_get_messages(client):
    create_resp = client.post("/sessions", json={"title": "Messages"})
    session_id = create_resp.json()["id"]

    from ui.backend.session_store import add_message
    add_message(session_id, "user", "Hello")
    add_message(session_id, "assistant", "Hi!")

    resp = client.get(f"/sessions/{session_id}/messages")
    assert resp.status_code == 200
    msgs = resp.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


def test_search_sessions(client):
    # Create sessions with distinct messages
    r1 = client.post("/sessions", json={"title": "Auth"})
    r2 = client.post("/sessions", json={"title": "Calendar"})

    from ui.backend.session_store import add_message
    add_message(r1.json()["id"], "user", "Fix the authentication bug")
    add_message(r2.json()["id"], "user", "Show my calendar events")

    resp = client.get("/sessions/search", params={"q": "authentication"})
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["title"] == "Auth"

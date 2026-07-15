"""Tests for the FastAPI server endpoints.

Uses TestClient for REST endpoints and mock model manager
to avoid loading real models during tests.
"""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Override DB path before importing
_TEST_DB = Path("/tmp/llm_harness_test_server.db")
PINNED_A = "a" * 40
PINNED_B = "b" * 40
PINNED_C = "c" * 40


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


def test_current_model_includes_revision(client, mock_model_manager):
    from ui.backend.model_manager import ModelInfo

    mock_model_manager.current_model = ModelInfo(
        model_id="test-model", backend="mlx", revision="sha-current", status="ready"
    )
    data = client.get("/models/current").json()
    assert data["revision"] == "sha-current"


def test_load_endpoint_forwards_revision(client, mock_model_manager):
    from ui.backend.model_manager import ModelInfo

    mock_model_manager.load_model.return_value = ModelInfo(
        model_id="org/model", backend="hf", revision="sha-load", status="ready"
    )
    response = client.post("/models/load", json={
        "model_id": "org/model",
        "backend": "hf",
        "revision": "sha-load",
    })

    assert response.status_code == 200
    assert response.json()["model"]["revision"] == "sha-load"
    mock_model_manager.load_model.assert_called_once_with(
        "org/model", "hf", revision="sha-load"
    )


def test_ws_load_forwards_and_echoes_revision(client, mock_model_manager):
    from ui.backend.model_manager import ModelInfo

    mock_model_manager.load_model.return_value = ModelInfo(
        model_id="org/model", backend="mlx", revision="sha-ws", status="ready"
    )
    with client.websocket_connect("/ws/models/load") as ws:
        ws.send_json({
            "model_id": "org/model",
            "backend": "mlx",
            "revision": "sha-ws",
        })
        message = ws.receive_json()

    assert message == {
        "type": "done",
        "model_id": "org/model",
        "backend": "mlx",
        "revision": "sha-ws",
    }
    args, kwargs = mock_model_manager.load_model.call_args
    assert args[:2] == ("org/model", "mlx")
    assert callable(args[2])
    assert kwargs == {"revision": "sha-ws"}


def test_ws_install_downloads_without_loading_runtime(client, mock_model_manager):
    installed = {
        "model_id": "org/model",
        "backend": "hf",
        "resolved_revision": "sha-install",
        "cache_status": "complete",
    }
    with patch("ui.backend.server.install_model", return_value=installed) as installer:
        with client.websocket_connect("/ws/models/install") as ws:
            ws.send_json({
                "model_id": "org/model",
                "backend": "hf",
                "revision": "sha-install",
            })
            message = ws.receive_json()

    assert message == {
        "type": "done",
        "model_id": "org/model",
        "backend": "hf",
        "revision": "sha-install",
        "cache_status": "complete",
    }
    args = installer.call_args.args
    assert args[:3] == ("org/model", "hf", "sha-install")
    assert callable(args[3])
    mock_model_manager.load_model.assert_not_called()


def test_ws_install_requires_pinned_revision(client, mock_model_manager):
    with client.websocket_connect("/ws/models/install") as ws:
        ws.send_json({"model_id": "org/model", "backend": "hf"})
        message = ws.receive_json()

    assert message["type"] == "error"
    assert "immutable revision" in message["message"]
    mock_model_manager.load_model.assert_not_called()


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

def test_list_projects_includes_default_project(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    projects = resp.json()
    assert len(projects) == 1
    assert projects[0]["id"] == "default"
    assert projects[0]["name"] == "Imported conversations"


def test_create_and_get_project(client):
    create_resp = client.post("/projects", json={"name": "Writing evaluations"})
    assert create_resp.status_code == 200
    project = create_resp.json()
    assert project["name"] == "Writing evaluations"
    assert project["is_default"] == 0

    get_resp = client.get(f"/projects/{project['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == project["id"]

def test_create_session(client):
    resp = client.post("/sessions", json={"title": "Test session"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test session"
    assert "id" in data


def test_create_comparison_in_project_with_ordered_models(client):
    project = client.post("/projects", json={"name": "Coding"}).json()
    resp = client.post("/sessions", json={
        "title": "Compare coding models",
        "is_compare": True,
        "project_id": project["id"],
        "models": [
            {"model_id": "org/model-b", "backend": "hf", "revision": PINNED_B},
            {"model_id": "org/model-a", "backend": "mlx", "revision": PINNED_A},
        ],
    })

    assert resp.status_code == 200
    session = resp.json()
    assert session["project_id"] == project["id"]
    assert session["models"] == ["org/model-b", "org/model-a"]
    assert session["comparison_models"][1]["revision"] == PINNED_A


def test_invalid_lineup_does_not_leave_an_orphan_session(client):
    resp = client.post("/sessions", json={
        "title": "Not a comparison",
        "is_compare": False,
        "models": [{"model_id": "org/model-a"}],
    })

    assert resp.status_code == 400
    assert client.get("/sessions").json() == []


def test_duplicate_comparison_models_are_rejected_atomically(client):
    resp = client.post("/sessions", json={
        "title": "Duplicate lineup",
        "is_compare": True,
        "models": [
            {"model_id": "org/model-a"},
            {"model_id": "org/model-a"},
        ],
    })

    assert resp.status_code == 400
    assert client.get("/sessions").json() == []


def test_list_sessions(client):
    client.post("/sessions", json={"title": "Session 1"})
    client.post("/sessions", json={"title": "Session 2"})
    resp = client.get("/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


def test_list_sessions_filters_by_project_and_type(client):
    project_a = client.post("/projects", json={"name": "A"}).json()
    project_b = client.post("/projects", json={"name": "B"}).json()
    client.post("/sessions", json={
        "title": "A comparison", "is_compare": True, "project_id": project_a["id"],
    })
    client.post("/sessions", json={
        "title": "A chat", "is_compare": False, "project_id": project_a["id"],
    })
    client.post("/sessions", json={
        "title": "B comparison", "is_compare": True, "project_id": project_b["id"],
    })

    resp = client.get("/sessions", params={
        "project_id": project_a["id"], "is_compare": "true",
    })
    assert resp.status_code == 200
    assert [session["title"] for session in resp.json()] == ["A comparison"]


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
    assert results[0]["models"] == []
    assert results[0]["comparison_models"] == []


class _RecordingWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


def test_compare_handler_persists_lineup_and_model_load_failure(mock_model_manager):
    from ui.backend.server import _handle_compare_message
    from ui.backend.session_store import get_messages, get_session

    mock_model_manager.load_model.side_effect = RuntimeError("unsupported architecture")
    ws = _RecordingWebSocket()

    asyncio.run(_handle_compare_message(ws, {
        "type": "message",
        "content": "Explain recursion",
        "models": [{"model_id": "org/broken-model", "revision": PINNED_A}],
        "project_id": "default",
    }))

    created = next(message for message in ws.messages if message["type"] == "session_created")
    session_id = created["session_id"]
    session = get_session(session_id)
    assert session["models"] == ["org/broken-model"]

    messages = get_messages(session_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["model_id"] == "org/broken-model"
    assert messages[1]["content"] == "Error loading model: unsupported architecture"

    outcome = next(message for message in ws.messages if message["type"] == "model_done")
    assert outcome["session_id"] == session_id
    assert outcome["response"] == "Error loading model: unsupported architecture"


def test_compare_handler_preserves_selected_backend(mock_model_manager):
    from ui.backend.server import _handle_compare_message
    from ui.backend.session_store import get_session

    mock_model_manager.load_model.side_effect = RuntimeError("not installed")
    ws = _RecordingWebSocket()

    asyncio.run(_handle_compare_message(ws, {
        "type": "message",
        "content": "Explain recursion",
        "models": [{
            "model_id": "org/hf-model",
            "backend": "hf",
            "revision": PINNED_B,
        }],
        "project_id": "default",
    }))

    session_id = next(
        message["session_id"]
        for message in ws.messages
        if message["type"] == "session_created"
    )
    assert get_session(session_id)["comparison_models"][0]["backend"] == "hf"
    mock_model_manager.load_model.assert_called_once_with(
        "org/hf-model", "hf", revision=PINNED_B
    )


def test_compare_handler_forwards_persisted_revision(mock_model_manager):
    from ui.backend.server import _handle_compare_message
    from ui.backend.session_store import get_session

    mock_model_manager.load_model.side_effect = RuntimeError("not installed")
    ws = _RecordingWebSocket()

    asyncio.run(_handle_compare_message(ws, {
        "type": "message",
        "content": "Explain recursion",
        "models": [{
            "model_id": "org/pinned-model",
            "backend": "hf",
            "revision": PINNED_C,
        }],
        "project_id": "default",
    }))

    session_id = next(
        message["session_id"]
        for message in ws.messages
        if message["type"] == "session_created"
    )
    assert get_session(session_id)["comparison_models"][0]["revision"] == PINNED_C
    mock_model_manager.load_model.assert_called_once_with(
        "org/pinned-model", "hf", revision=PINNED_C
    )


def test_compare_handler_persists_generation_failure(mock_model_manager):
    from ui.backend.server import _handle_compare_message
    from ui.backend.session_store import get_messages

    mock_model_manager.generate.side_effect = RuntimeError("generation crashed")
    ws = _RecordingWebSocket()

    asyncio.run(_handle_compare_message(ws, {
        "type": "message",
        "content": "Explain recursion",
        "models": [{"model_id": "org/crashing-model", "revision": PINNED_A}],
        "project_id": "default",
    }))

    session_id = next(
        message["session_id"]
        for message in ws.messages
        if message["type"] == "session_created"
    )
    messages = get_messages(session_id)
    assert messages[-1]["model_id"] == "org/crashing-model"
    assert messages[-1]["content"] == "Error generating response: generation crashed"

    outcome = next(message for message in ws.messages if message["type"] == "model_done")
    assert outcome["session_id"] == session_id
    assert outcome["response"] == "Error generating response: generation crashed"


def test_compare_handler_persists_empty_model_output(mock_model_manager):
    from ui.backend.server import _handle_compare_message
    from ui.backend.session_store import get_messages

    mock_model_manager.generate.return_value = iter([])
    ws = _RecordingWebSocket()

    asyncio.run(_handle_compare_message(ws, {
        "type": "message",
        "content": "Explain recursion",
        "models": [{"model_id": "org/empty-model", "revision": PINNED_A}],
        "project_id": "default",
    }))

    session_id = next(
        message["session_id"]
        for message in ws.messages
        if message["type"] == "session_created"
    )
    messages = get_messages(session_id)
    assert messages[-1]["model_id"] == "org/empty-model"
    assert messages[-1]["content"] == "Model returned empty response"

    outcome = next(message for message in ws.messages if message["type"] == "model_done")
    assert outcome["session_id"] == session_id
    assert outcome["response"] == "Model returned empty response"


def test_compare_handler_persists_successful_model_outcome(mock_model_manager):
    from ui.backend.server import _handle_compare_message
    from ui.backend.session_store import get_messages

    mock_model_manager.generate.side_effect = lambda _conversation, **_kwargs: iter([
        "A durable", " response",
    ])
    ws = _RecordingWebSocket()

    asyncio.run(_handle_compare_message(ws, {
        "type": "message",
        "content": "Explain persistence",
        "models": [{"model_id": "org/success-model", "revision": PINNED_A}],
        "project_id": "default",
    }))

    created = next(message for message in ws.messages if message["type"] == "session_created")
    session_id = created["session_id"]
    messages = get_messages(session_id)

    assert [message["role"] for message in messages] == ["user", "assistant"]
    outcome = messages[1]
    assert outcome["session_id"] == session_id
    assert outcome["model_id"] == "org/success-model"
    assert outcome["content"] == "A durable response"
    assert outcome["tokens_generated"] == 2
    assert isinstance(outcome["generation_time_ms"], int)

    done = next(message for message in ws.messages if message["type"] == "model_done")
    assert done["session_id"] == session_id
    assert done["model_id"] == "org/success-model"
    assert done["response"] == "A durable response"
    assert done["tokens"] == 2


def test_compare_treats_tool_syntax_as_plain_model_output(mock_model_manager):
    from ui.backend.server import _handle_compare_message
    from ui.backend.session_store import get_messages

    tool_syntax = '{"tool":"run_shell","args":{"command":"echo nope"}}'
    mock_model_manager.generate.return_value = iter([tool_syntax])
    ws = _RecordingWebSocket()

    asyncio.run(_handle_compare_message(ws, {
        "type": "message",
        "content": "Compare without tools",
        "models": [{"model_id": "org/model", "revision": PINNED_A}],
        "project_id": "default",
    }))

    session_id = next(
        message["session_id"]
        for message in ws.messages
        if message["type"] == "session_created"
    )
    assert get_messages(session_id)[-1]["content"] == tool_syntax
    assert not any(message["type"] == "tool_call" for message in ws.messages)
    assert any(message["type"] == "model_done" for message in ws.messages)


def test_compare_second_turn_reconstructs_model_specific_history(mock_model_manager):
    from ui.backend.server import _handle_compare_message

    observed_conversations = []
    responses = iter([
        ["Alpha first"],
        ["Beta first"],
        ["Alpha second"],
        ["Beta second"],
    ])

    def generate(conversation, **_kwargs):
        observed_conversations.append([dict(message) for message in conversation])
        return iter(next(responses))

    mock_model_manager.generate.side_effect = generate
    first_turn_ws = _RecordingWebSocket()
    asyncio.run(_handle_compare_message(first_turn_ws, {
        "type": "message",
        "content": "First shared prompt",
        "models": [
            {"model_id": "org/alpha", "revision": PINNED_A},
            {"model_id": "org/beta", "revision": PINNED_B},
        ],
        "project_id": "default",
    }))
    session_id = next(
        message["session_id"]
        for message in first_turn_ws.messages
        if message["type"] == "session_created"
    )

    second_turn_ws = _RecordingWebSocket()
    asyncio.run(_handle_compare_message(second_turn_ws, {
        "type": "message",
        "content": "Second shared prompt",
        "session_id": session_id,
    }))

    assert observed_conversations == [
        [
            {"role": "user", "content": "First shared prompt"},
        ],
        [
            {"role": "user", "content": "First shared prompt"},
        ],
        [
            {"role": "user", "content": "First shared prompt"},
            {"role": "assistant", "content": "Alpha first"},
            {"role": "user", "content": "Second shared prompt"},
        ],
        [
            {"role": "user", "content": "First shared prompt"},
            {"role": "assistant", "content": "Beta first"},
            {"role": "user", "content": "Second shared prompt"},
        ],
    ]

    assert second_turn_ws.messages[-1] == {
        "type": "compare_done",
        "session_id": session_id,
    }

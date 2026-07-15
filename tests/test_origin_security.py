"""Regression coverage for browser-origin boundaries on the local API."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ui.backend.server import app


TRUSTED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)

WEBSOCKET_PATHS = (
    "/ws/models/load",
    "/ws/models/install",
    "/ws/chat",
    "/ws/compare",
)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("origin", TRUSTED_ORIGINS)
def test_rest_cors_allows_only_configured_app_origins(client, origin):
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ("https://evil.example", "http://localhost:9999"))
def test_rest_cors_rejects_untrusted_origins(client, origin):
    preflight = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    simple_request = client.get("/health", headers={"Origin": origin})

    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in simple_request.headers


def test_rest_request_without_origin_remains_available_to_native_clients(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("path", WEBSOCKET_PATHS)
@pytest.mark.parametrize("origin", ("https://evil.example", "null"))
def test_every_websocket_rejects_untrusted_browser_origins(client, path, origin):
    with pytest.raises(WebSocketDisconnect) as rejection:
        with client.websocket_connect(path, headers={"Origin": origin}):
            pass

    assert rejection.value.code == 1008
    assert rejection.value.reason == "Origin not allowed"


@pytest.mark.parametrize("path", WEBSOCKET_PATHS)
def test_every_websocket_allows_missing_origin_for_native_clients(client, path):
    with client.websocket_connect(path):
        pass


@pytest.mark.parametrize("path", WEBSOCKET_PATHS)
def test_every_websocket_allows_the_tauri_origin(client, path):
    with client.websocket_connect(path, headers={"Origin": "tauri://localhost"}):
        pass

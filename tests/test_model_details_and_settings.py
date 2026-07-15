"""Regression coverage for safe model metadata and secret settings."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


def test_preferred_weight_size_uses_one_format_family():
    from ui.backend.server import _preferred_weight_size

    siblings = [
        SimpleNamespace(rfilename="a.safetensors", size=10),
        SimpleNamespace(rfilename="b.safetensors", size=20),
        SimpleNamespace(rfilename="pytorch_model.bin", size=100),
        SimpleNamespace(rfilename="model.gguf", size=50),
    ]
    assert _preferred_weight_size(siblings) == 30


def test_saving_display_mask_does_not_overwrite_secret(monkeypatch, tmp_path):
    from ui.backend import server

    env_file = tmp_path / ".env"
    env_file.write_text("HF_TOKEN=hf_very_secret_token\n")
    monkeypatch.setattr(server, "_ENV_FILE", env_file)
    masked = server._mask_secret("hf_very_secret_token")

    result = asyncio.run(server.save_api_key(server.SaveKeyRequest(
        key="HF_TOKEN", value=masked
    )))

    assert result == {
        "status": "ok",
        "unchanged": True,
        "masked": masked,
    }
    assert env_file.read_text() == "HF_TOKEN=hf_very_secret_token\n"


def test_api_keys_remain_masked_until_explicit_reveal(monkeypatch, tmp_path):
    from ui.backend import server

    env_file = tmp_path / ".env"
    raw_token = "hf_test_secret_value_123456"
    env_file.write_text(f"HF_TOKEN={raw_token}\n")
    monkeypatch.setattr(server, "_ENV_FILE", env_file)

    with TestClient(server.app) as client:
        listed = client.get("/settings/keys")
        revealed = client.post(
            "/settings/keys/reveal",
            headers={"Origin": "http://localhost:5173"},
            json={"key": "HF_TOKEN"},
        )

    assert listed.status_code == 200
    assert raw_token not in listed.text
    assert listed.json()["HF_TOKEN"] == server._mask_secret(raw_token)
    assert revealed.status_code == 200
    assert revealed.json() == {"key": "HF_TOKEN", "value": raw_token}
    assert "no-store" in revealed.headers["cache-control"]
    assert revealed.headers["pragma"] == "no-cache"


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_reveal_rejects_requests_outside_the_app(monkeypatch, tmp_path, origin):
    from ui.backend import server

    raw_token = "hf_must_not_leak"
    env_file = tmp_path / ".env"
    env_file.write_text(f"HF_TOKEN={raw_token}\n")
    monkeypatch.setattr(server, "_ENV_FILE", env_file)
    headers = {"Origin": origin} if origin else {}

    with TestClient(server.app) as client:
        response = client.post(
            "/settings/keys/reveal",
            headers=headers,
            json={"key": "HF_TOKEN"},
        )

    assert response.status_code == 403
    assert raw_token not in response.text


def test_reveal_rejects_unknown_key_before_reading_secret(monkeypatch, tmp_path):
    from ui.backend import server

    env_file = tmp_path / ".env"
    env_file.write_text("HF_TOKEN=hf_must_not_leak\n")
    monkeypatch.setattr(server, "_ENV_FILE", env_file)

    with TestClient(server.app) as client:
        response = client.post(
            "/settings/keys/reveal",
            headers={"Origin": "tauri://localhost"},
            json={"key": "NOT_ALLOWED"},
        )

    assert response.status_code == 400
    assert "hf_must_not_leak" not in response.text

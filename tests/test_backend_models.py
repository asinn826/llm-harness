"""Tests for the enriched model registry and list_models.

Covers:
- recommended_models.json schema (every entry has required fields)
- list_models() enrichment (cached-only models get size/last_used/author)
- _make_progress_tqdm factory (callback fires with expected progress values)
- _format_bytes helper
"""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


REQUIRED_RECOMMENDED_FIELDS = {
    "id", "name", "author", "backend", "parameters", "quantization",
    "size_bytes", "size_label", "context_window", "heat", "description",
    "license", "tags", "hf_url", "tool_use_tier",
}


# ── Registry schema ──────────────────────────────────────────────────────


def test_recommended_json_parses():
    path = Path(__file__).resolve().parent.parent / "ui" / "backend" / "recommended_models.json"
    assert path.exists(), "recommended_models.json missing"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, list), "registry must be a list"
    assert len(data) >= 1, "registry must have at least one entry"


def test_recommended_entries_have_required_fields():
    path = Path(__file__).resolve().parent.parent / "ui" / "backend" / "recommended_models.json"
    with open(path) as f:
        data = json.load(f)
    for entry in data:
        missing = REQUIRED_RECOMMENDED_FIELDS - set(entry.keys())
        assert not missing, f"entry {entry.get('id', '?')} missing fields: {missing}"
        assert entry["backend"] in ("mlx", "hf"), f"bad backend: {entry['backend']}"
        assert entry["tool_use_tier"] in ("verified", "likely", "unknown")


def test_main_loads_registry_from_json():
    """main.RECOMMENDED_MODELS should come from the JSON file."""
    from main import RECOMMENDED_MODELS
    assert len(RECOMMENDED_MODELS) >= 1
    # Every entry has the enriched fields
    for entry in RECOMMENDED_MODELS:
        assert "parameters" in entry
        assert "context_window" in entry
        assert "tool_use_tier" in entry


def test_cli_picker_back_compat():
    """CLI picker reads m["size"] — make sure we still provide it."""
    from main import RECOMMENDED_MODELS
    for entry in RECOMMENDED_MODELS:
        # The loader falls back to size_label if "size" absent; check both forms exist
        assert "size" in entry or "size_label" in entry


# ── list_models enrichment ────────────────────────────────────────────────


def test_list_models_enriches_recommended():
    from ui.backend.model_manager import model_manager
    data = model_manager.list_models()
    assert "recommended" in data
    for m in data["recommended"]:
        # Recommended come from JSON so they have the full schema
        assert "parameters" in m
        assert "context_window" in m
        assert "tool_use_tier" in m
        # Plus runtime fields
        assert "is_cached" in m
        assert "is_loaded" in m


def test_list_models_enriches_cached_only():
    """Cached-but-not-recommended models get size_bytes, author, last_used."""
    from ui.backend.model_manager import model_manager
    data = model_manager.list_models()
    for m in data["cached"]:
        assert "author" in m
        assert "size_bytes" in m
        assert "size_label" in m
        assert "last_used" in m
        assert m["tool_use_tier"] == "unknown"


# ── _format_bytes ────────────────────────────────────────────────────────


def test_format_bytes():
    from ui.backend.model_manager import _format_bytes
    assert _format_bytes(0) == ""
    assert _format_bytes(500) == "500 B"
    assert _format_bytes(1536) == "1.5 KB"
    assert "GB" in _format_bytes(3 * 1024 ** 3)


# ── _make_progress_tqdm ──────────────────────────────────────────────────


def test_make_progress_tqdm_fires_callback():
    """Simulate tqdm updates → callback receives LoadProgress with mapped %."""
    from ui.backend.model_manager import _make_progress_tqdm, LoadProgress

    received: list[LoadProgress] = []
    cb = lambda p: received.append(p)

    TqdmCls = _make_progress_tqdm("test/model", cb, is_cached=False)

    # Construct an instance with a known total, call update twice
    bar = TqdmCls(total=100)
    bar.update(50)  # 50%
    bar.update(50)  # 100%

    assert len(received) == 2
    # Progress is mapped into 0.3 → 0.9 range: 50% → 0.6, 100% → 0.9
    assert received[0].progress == pytest.approx(0.6, abs=0.01)
    assert received[1].progress == pytest.approx(0.9, abs=0.01)
    assert received[0].model_id == "test/model"
    assert "Downloading" in received[0].message


def test_make_progress_tqdm_cached_label():
    """When is_cached=True, label says 'Loading weights' instead of 'Downloading'."""
    from ui.backend.model_manager import _make_progress_tqdm

    received = []
    TqdmCls = _make_progress_tqdm("test/model", lambda p: received.append(p), is_cached=True)
    bar = TqdmCls(total=10)
    bar.update(5)

    assert "Loading weights" in received[0].message
    assert "Downloading" not in received[0].message


def test_make_progress_tqdm_no_total_no_callback():
    """When tqdm has no total, callback should not fire (avoid div-by-zero)."""
    from ui.backend.model_manager import _make_progress_tqdm

    received = []
    TqdmCls = _make_progress_tqdm("x", lambda p: received.append(p), is_cached=False)
    bar = TqdmCls()  # no total
    bar.update(5)
    # No callback because total is None
    assert len(received) == 0


# ── Chat-template inspection ──────────────────────────────────────────────


def test_inspect_chat_template_detects_tools():
    from ui.backend.model_manager import _inspect_chat_template

    class FakeTokenizer:
        chat_template = "{% if tool_calls %}{{ tools }}{% endif %}"

    assert _inspect_chat_template(FakeTokenizer()) == "likely"


def test_inspect_chat_template_none_if_no_hints():
    from ui.backend.model_manager import _inspect_chat_template

    class FakeTokenizer:
        chat_template = "{% for m in messages %}{{ m.content }}{% endfor %}"

    assert _inspect_chat_template(FakeTokenizer()) is None


def test_inspect_chat_template_handles_no_template():
    from ui.backend.model_manager import _inspect_chat_template

    class FakeTokenizer:
        pass

    assert _inspect_chat_template(FakeTokenizer()) is None


# ── Hub search endpoint ──────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from ui.backend.server import app
    return TestClient(app)


def test_hub_search_returns_200_on_exception(client):
    """When HfApi raises, endpoint returns 200 with empty results + error."""
    with patch("huggingface_hub.HfApi") as MockApi:
        MockApi.return_value.list_models.side_effect = RuntimeError("network down")
        resp = client.get("/models/search?q=test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert "error" in data


def test_hub_search_normalizes_hits(client):
    """Valid HfApi response gets normalized into our shape."""
    from datetime import datetime

    fake_hit = MagicMock()
    fake_hit.id = "org/my-model"
    fake_hit.downloads = 1234
    fake_hit.likes = 56
    fake_hit.last_modified = datetime(2025, 1, 1)
    fake_hit.tags = ["text-generation", "safetensors"]
    fake_hit.pipeline_tag = "text-generation"
    fake_hit.gated = False

    with patch("huggingface_hub.HfApi") as MockApi:
        MockApi.return_value.list_models.return_value = iter([fake_hit])
        # Clear cache so we actually hit our mock
        from ui.backend.server import _search_cache
        _search_cache.clear()
        resp = client.get("/models/search?q=unique-query-xyz")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        r = results[0]
        assert r["id"] == "org/my-model"
        assert r["author"] == "org"
        assert r["name"] == "my-model"
        assert r["downloads"] == 1234
        assert r["likes"] == 56
        assert r["backend_hint"] == "hf"  # no "mlx" tag
        assert r["tool_use_tier"] == "unknown"  # not in curated list
        assert r["compatible"] is True


def test_hub_search_mlx_tag_gets_mlx_hint(client):
    fake_hit = MagicMock()
    fake_hit.id = "mlx-community/something"
    fake_hit.downloads = 1
    fake_hit.likes = 0
    fake_hit.last_modified = None
    fake_hit.tags = ["mlx", "text-generation"]
    fake_hit.pipeline_tag = "text-generation"
    fake_hit.gated = False

    with patch("huggingface_hub.HfApi") as MockApi:
        MockApi.return_value.list_models.return_value = iter([fake_hit])
        from ui.backend.server import _search_cache
        _search_cache.clear()
        resp = client.get("/models/search?q=distinct-mlx-query")
        data = resp.json()
        assert data["results"][0]["backend_hint"] == "mlx"


# ── Path-traversal guard ──────────────────────────────────────────────────


def test_details_rejects_path_traversal(client):
    """../ in owner or repo returns 422 (FastAPI Path regex validation)."""
    resp = client.get("/models/..%2F..%2Fetc/repo/details")
    # FastAPI URL-decodes %2F which breaks the path; it should 404 or 422.
    # The important thing is we don't hit the backend.
    assert resp.status_code in (404, 422, 400)


def test_details_rejects_traversal_via_dots(client):
    """owner=".." returns 422 from the pattern validator."""
    resp = client.get("/models/.../repo/details")
    assert resp.status_code == 422


def test_details_rejects_empty_segment(client):
    """Empty owner or repo fails validation."""
    resp = client.get("/models//repo/details")
    assert resp.status_code in (404, 422)


# ── Settings: hub_search_enabled ──────────────────────────────────────────


def test_prefs_default_to_hub_disabled(client, tmp_path, monkeypatch):
    """Fresh install has hub_search_enabled=False."""
    # Point the prefs file at a temp location
    monkeypatch.setattr("ui.backend.server._PREFS_FILE", tmp_path / "preferences.json")
    resp = client.get("/settings/prefs")
    assert resp.status_code == 200
    assert resp.json()["hub_search_enabled"] is False


def test_set_hub_search_persists(client, tmp_path, monkeypatch):
    monkeypatch.setattr("ui.backend.server._PREFS_FILE", tmp_path / "preferences.json")
    resp = client.post("/settings/hub-search", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["hub_search_enabled"] is True

    # Round-trip
    resp = client.get("/settings/prefs")
    assert resp.json()["hub_search_enabled"] is True

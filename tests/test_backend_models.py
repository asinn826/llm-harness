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

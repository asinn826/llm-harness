"""Install pinned Hub artifacts without allocating a model runtime."""

from unittest.mock import MagicMock

import pytest

from ui.backend.model_installer import install_model


def _preflight(cache_status: str = "missing") -> dict:
    return {
        "model_id": "org/model",
        "backend": "hf",
        "resolved_revision": "sha-install",
        "can_install": True,
        "can_load": True,
        "cache_status": cache_status,
        "install_files": ["config.json", "tokenizer.json", "model.safetensors"],
        "error": None,
    }


def test_install_downloads_exact_pinned_artifact_plan(monkeypatch):
    snapshot_download = MagicMock(return_value="/cache/snapshot")
    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_download)
    preflight_fn = MagicMock(side_effect=[_preflight(), _preflight("complete")])
    progress = []

    result = install_model(
        "org/model",
        "hf",
        "sha-install",
        progress.append,
        preflight_fn=preflight_fn,
    )

    snapshot_download.assert_called_once()
    kwargs = snapshot_download.call_args.kwargs
    assert kwargs["repo_id"] == "org/model"
    assert kwargs["revision"] == "sha-install"
    assert kwargs["allow_patterns"] == [
        "config.json", "tokenizer.json", "model.safetensors"
    ]
    assert result["cache_status"] == "complete"
    assert progress[-1].status == "ready"


def test_install_skips_download_when_exact_revision_is_complete(monkeypatch):
    snapshot_download = MagicMock()
    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_download)

    result = install_model(
        "org/model",
        "hf",
        "sha-install",
        preflight_fn=MagicMock(return_value=_preflight("complete")),
    )

    snapshot_download.assert_not_called()
    assert result["cache_status"] == "complete"


def test_install_rejects_mutable_or_mismatched_revision():
    preflight = _preflight()
    preflight["resolved_revision"] = "different-sha"

    with pytest.raises(RuntimeError, match="changed since preflight"):
        install_model(
            "org/model",
            "hf",
            "release-tag",
            preflight_fn=MagicMock(return_value=preflight),
        )


def test_install_surfaces_preflight_block_without_downloading(monkeypatch):
    snapshot_download = MagicMock()
    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_download)
    blocked = _preflight()
    blocked["can_install"] = False
    blocked["can_load"] = False
    blocked["error"] = {"message": "Runtime unavailable"}

    with pytest.raises(RuntimeError, match="Runtime unavailable"):
        install_model(
            "org/model",
            "hf",
            "sha-install",
            preflight_fn=MagicMock(return_value=blocked),
        )

    snapshot_download.assert_not_called()


def test_install_is_not_blocked_by_transient_memory_pressure(monkeypatch):
    snapshot_download = MagicMock(return_value="/cache/snapshot")
    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_download)
    before = _preflight()
    before["can_load"] = False
    before["error"] = {"code": "insufficient_memory", "message": "Too large to load"}
    after = _preflight("complete")
    after["can_load"] = False
    after["error"] = before["error"]

    result = install_model(
        "org/model",
        "hf",
        "sha-install",
        preflight_fn=MagicMock(side_effect=[before, after]),
    )

    snapshot_download.assert_called_once()
    assert result["cache_status"] == "complete"
    assert result["can_load"] is False

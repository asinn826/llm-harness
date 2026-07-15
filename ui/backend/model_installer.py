"""Revision-pinned Hugging Face installation without runtime allocation."""

from __future__ import annotations

import os
from typing import Callable, Optional

from .model_manager import LoadProgress, _make_progress_tqdm
from .model_preflight import preflight_model


def install_model(
    model_id: str,
    backend: str,
    revision: str,
    progress_callback: Optional[Callable[[LoadProgress], None]] = None,
    *,
    preflight_fn=preflight_model,
) -> dict:
    """Install only the runnable artifact family for an immutable revision."""
    if not revision:
        raise RuntimeError("An immutable model revision is required. Run preflight first.")

    before = preflight_fn(model_id, backend=backend, revision=revision)
    resolved_revision = before.get("resolved_revision")
    if resolved_revision != revision:
        raise RuntimeError(
            "The model revision changed since preflight. Check the model again before installing."
        )
    # Loading may be blocked by the current memory budget, but installation is
    # a disk-only operation. Older injected preflight implementations expose
    # only ``can_load``, so retain that as a compatibility fallback.
    can_install = before.get("can_install")
    if can_install is None:
        can_install = before.get("can_load")
    if not can_install:
        error = before.get("error") or {}
        raise RuntimeError(error.get("message") or "This model cannot run in the selected runtime.")

    if before.get("cache_status") == "complete":
        if progress_callback:
            progress_callback(LoadProgress(
                model_id=model_id,
                progress=1.0,
                status="ready",
                message="Exact revision is already installed",
            ))
        return before

    install_files = list(before.get("install_files") or [])
    if not install_files:
        raise RuntimeError("Preflight did not find an installable artifact set.")

    if progress_callback:
        progress_callback(LoadProgress(
            model_id=model_id,
            progress=0.05,
            status="loading",
            message="Preparing pinned model download…",
        ))

    from huggingface_hub import snapshot_download

    token = os.environ.get("HF_TOKEN") or None
    progress_tqdm = _make_progress_tqdm(
        model_id,
        progress_callback,
        is_cached=before.get("cache_status") == "partial",
    )
    snapshot_download(
        repo_id=model_id,
        revision=revision,
        token=token,
        allow_patterns=install_files,
        tqdm_class=progress_tqdm,
    )

    after = preflight_fn(model_id, backend=backend, revision=revision)
    if after.get("cache_status") != "complete":
        raise RuntimeError("The download finished, but the pinned model installation is incomplete.")

    if progress_callback:
        progress_callback(LoadProgress(
            model_id=model_id,
            progress=1.0,
            status="ready",
            message="Pinned model installed",
        ))
    return after


__all__ = ["install_model"]

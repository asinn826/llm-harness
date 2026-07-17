"""Deterministic Hugging Face model preflight.

The service resolves a requested branch or tag to an immutable Hub commit,
checks whether the repository is accessible and runnable by the selected
backend, and estimates whether its weights fit in the post-unload memory budget.

It intentionally does not download or load a model. Callers can safely run
preflight before starting either operation and persist ``resolved_revision``
for reproducible comparisons.
"""

from __future__ import annotations

import math
import os
import importlib.util
import platform
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from huggingface_hub.constants import HF_HUB_CACHE
from huggingface_hub.file_download import repo_folder_name
from huggingface_hub.utils import (
    GatedRepoError,
    HfHubHTTPError,
    RepositoryNotFoundError,
    RevisionNotFoundError,
)
from requests import RequestException


MEMORY_MULTIPLIER = 1.2
MEMORY_OVERHEAD_BYTES = 512 * 1024 ** 2
TIGHT_MEMORY_FRACTION = 0.8
DISK_SAFETY_BYTES = 256 * 1024 ** 2

_SUPPORTED_PIPELINES = {"text-generation"}
_HF_TEXT_INPUT_PIPELINES = {"any-to-any", "image-text-to-text"}
_MLX_QWEN35_ARCHITECTURE = "Qwen3_5ForConditionalGeneration"
_MLX_QWEN35_MODULE = "mlx_lm.models.qwen3_5"
_WEIGHT_SUFFIXES = {
    "hf": (".safetensors", ".bin"),
    "mlx": (".safetensors", ".npz"),
}
_ALL_NATIVE_SUFFIXES = (".safetensors", ".bin", ".npz")
_MAX_SUPPORT_FILE_BYTES = 50 * 1024 ** 2
_RUNTIME_SUPPORT_NAMES = {
    "added_tokens.json",
    "chat_template.jinja",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "preprocessor_config.json",
    "processor_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
    "vocab.json",
    "vocab.txt",
}
_NON_MODEL_WEIGHT_NAMES = {
    "optimizer.bin",
    "optimizer.safetensors",
    "scheduler.bin",
    "training_args.bin",
}


class ModelPreflightError(RuntimeError):
    """A structured failure that prevented preflight from completing."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        http_status: int,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


def estimate_memory_bytes(model_size_bytes: int) -> int:
    """Conservative load-time estimate: weights, runtime overhead, and cache."""
    if model_size_bytes <= 0:
        return 0
    return math.ceil(model_size_bytes * MEMORY_MULTIPLIER) + MEMORY_OVERHEAD_BYTES


def _system_memory_budget_bytes() -> int:
    """Memory available after the harness unloads the current model.

    Comparisons run sequentially and ``ModelManager`` always releases the
    current runtime before loading the next model. Instantaneous free memory
    therefore undercounts the capacity available to the next comparison slot;
    total physical memory is the stable post-unload budget.
    """
    try:
        import psutil

        return max(0, int(psutil.virtual_memory().total))
    except Exception:
        return 0


def _normalize_backend(backend: Optional[str], tags: list[str]) -> str:
    if backend is None:
        return "mlx" if "mlx" in tags else "hf"
    normalized = backend.strip().lower()
    if normalized not in _WEIGHT_SUFFIXES:
        raise ModelPreflightError(
            "invalid_backend",
            f"Unsupported backend '{backend}'. Choose 'mlx' or 'hf'.",
            retryable=False,
            http_status=422,
        )
    return normalized


def _filename(sibling: Any) -> str:
    return str(getattr(sibling, "rfilename", "") or "").lower()


def _file_size(sibling: Any) -> int:
    try:
        return max(0, int(getattr(sibling, "size", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _matches_weight_suffix(sibling: Any, suffix: str) -> bool:
    filename = _filename(sibling)
    basename = PurePosixPath(filename).name
    if not filename.endswith(suffix):
        return False
    if basename in _NON_MODEL_WEIGHT_NAMES:
        return False
    if basename.startswith("adapter_"):
        return False
    return True


def _selected_weight_siblings(siblings: list[Any], backend: str) -> list[Any]:
    for suffix in _WEIGHT_SUFFIXES[backend]:
        matching = [s for s in siblings if _matches_weight_suffix(s, suffix)]
        if matching:
            return matching

    # Even when GGUF is incompatible, expose its download footprint.
    return [s for s in siblings if _filename(s).endswith(".gguf")]


def _selected_weight_bytes(siblings: list[Any], backend: str) -> int:
    """Sum one preferred runnable weight family, avoiding duplicate formats."""
    return sum(_file_size(s) for s in _selected_weight_siblings(siblings, backend))


def _is_runtime_support_file(sibling: Any) -> bool:
    filename = _filename(sibling)
    basename = PurePosixPath(filename).name
    if _file_size(sibling) > _MAX_SUPPORT_FILE_BYTES:
        return False
    if basename in _RUNTIME_SUPPORT_NAMES:
        return True
    if basename.endswith((".safetensors.index.json", ".bin.index.json")):
        return True
    # Some tokenizers use a model-specific SentencePiece filename.
    if basename.endswith(".model") and any(
        marker in basename for marker in ("tokenizer", "sentencepiece", "spiece")
    ):
        return True
    return False


def _install_files(siblings: list[Any], backend: str) -> list[str]:
    """Exact artifact plan: one weight family plus runtime support files."""
    weights = _selected_weight_siblings(siblings, backend)
    selected_ids = {id(sibling) for sibling in weights}
    all_weight_suffixes = (".safetensors", ".bin", ".npz", ".gguf")
    files: list[str] = []
    for sibling in siblings:
        filename = str(getattr(sibling, "rfilename", "") or "")
        lowered = filename.lower()
        if not filename:
            continue
        is_selected_weight = id(sibling) in selected_ids
        is_other_weight = lowered.endswith(all_weight_suffixes)
        is_runtime_support = not is_other_weight and _is_runtime_support_file(sibling)
        if is_selected_weight or is_runtime_support:
            files.append(filename)
    return files


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _hf_causal_loader_supports(
    architectures: list[Any],
    config: dict[str, Any],
) -> bool:
    """Return whether AutoModelForCausalLM supports this model configuration.

    Some multimodal repositories use a conditional-generation architecture
    even when invoked with text alone. Their Hub pipeline tag describes the
    full modality range, and AutoModel selects its concrete causal class from
    ``model_type`` rather than requiring the Hub architecture name to match.
    """
    model_type = str(config.get("model_type") or "")
    if model_type:
        try:
            from transformers.models.auto.modeling_auto import (
                MODEL_FOR_CAUSAL_LM_MAPPING_NAMES,
            )

            mapped = MODEL_FOR_CAUSAL_LM_MAPPING_NAMES.get(model_type)
            if mapped:
                return True
        except (ImportError, ModuleNotFoundError):
            pass

    return any(str(name).endswith("ForCausalLM") for name in architectures)


def _runtime_availability(backend: str) -> tuple[bool, str, Optional[str]]:
    """Return whether the selected local runtime can actually be invoked."""
    if backend == "mlx":
        machine = platform.machine().lower()
        if platform.system() != "Darwin" or machine not in {"arm64", "aarch64"}:
            return (
                False,
                "runtime_unsupported_platform",
                "The MLX runtime requires an Apple Silicon Mac.",
            )
        required = ("mlx", "mlx_lm")
    else:
        required = ("torch", "transformers")

    missing = [name for name in required if not _module_available(name)]
    if missing:
        return (
            False,
            "runtime_missing_dependencies",
            f"The {backend.upper()} runtime is unavailable; missing: {', '.join(missing)}.",
        )
    return True, "available", None


def _safe_snapshot_file(snapshot: Path, filename: str) -> Optional[Path]:
    relative = PurePosixPath(filename)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        return None
    return snapshot.joinpath(*relative.parts)


def _cache_file_is_complete(snapshot: Path, sibling: Any) -> bool:
    filename = str(getattr(sibling, "rfilename", "") or "")
    path = _safe_snapshot_file(snapshot, filename)
    if path is None or not path.is_file():
        return False
    expected_size = _file_size(sibling)
    if expected_size <= 0:
        return True
    try:
        return path.stat().st_size == expected_size
    except OSError:
        return False


def _exact_revision_cache_coverage(
    model_id: str,
    resolved_revision: str,
    siblings: list[Any],
    backend: str,
    cache_dir: Optional[Path],
) -> tuple[str, int, int]:
    """Return exact-SHA cache status, cached bytes, and missing bytes.

    A snapshot is complete only when every file in the exact install plan is
    present at the expected size. This includes support files such as a
    sharded-weight index, not just the preferred weight family.
    """
    install_files = set(_install_files(siblings, backend))
    required = [
        sibling
        for sibling in siblings
        if str(getattr(sibling, "rfilename", "") or "") in install_files
    ]
    total_bytes = sum(_file_size(sibling) for sibling in required)
    root = Path(cache_dir) if cache_dir is not None else Path(HF_HUB_CACHE)
    snapshot = (
        root
        / repo_folder_name(repo_id=model_id, repo_type="model")
        / "snapshots"
        / resolved_revision
    )
    if not snapshot.is_dir():
        return "missing", 0, total_bytes

    weights = _selected_weight_siblings(siblings, backend)
    if not weights:
        return "partial", 0, total_bytes

    complete_files = [
        sibling for sibling in required if _cache_file_is_complete(snapshot, sibling)
    ]
    cached_bytes = sum(_file_size(sibling) for sibling in complete_files)
    missing_bytes = max(0, total_bytes - cached_bytes)
    status = "complete" if len(complete_files) == len(required) else "partial"
    return status, cached_bytes, missing_bytes


def _exact_revision_cache_status(
    model_id: str,
    resolved_revision: str,
    siblings: list[Any],
    backend: str,
    cache_dir: Optional[Path],
) -> str:
    """Backwards-compatible status-only cache helper."""
    return _exact_revision_cache_coverage(
        model_id, resolved_revision, siblings, backend, cache_dir
    )[0]


def _filesystem_free_bytes(path: Path) -> int:
    """Return free bytes for the closest existing parent of ``path``."""
    candidate = path.expanduser()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    try:
        return max(0, int(shutil.disk_usage(candidate).free))
    except OSError:
        return 0


def _disk_fit(required_bytes: int, available_bytes: int) -> str:
    if required_bytes <= 0:
        return "fits"
    if available_bytes <= 0:
        return "unknown"
    return (
        "insufficient"
        if required_bytes + DISK_SAFETY_BYTES > available_bytes
        else "fits"
    )


def _compatibility(
    model_id: str,
    pipeline_tag: Optional[str],
    siblings: list[Any],
    backend: str,
    tags: list[str],
    config: dict[str, Any],
) -> tuple[bool, str, Optional[str]]:
    architectures = list(config.get("architectures") or [])
    mlx_identity = "mlx" in tags or model_id.lower().startswith("mlx-community/")
    mlx_qwen35_text_model = (
        backend == "mlx"
        and mlx_identity
        and config.get("model_type") == "qwen3_5"
        and _MLX_QWEN35_ARCHITECTURE in architectures
    )
    supported_pipeline = (
        pipeline_tag in _SUPPORTED_PIPELINES
        or (backend == "hf" and pipeline_tag in _HF_TEXT_INPUT_PIPELINES)
    ) or (
        pipeline_tag == "image-text-to-text" and mlx_qwen35_text_model
    )
    if pipeline_tag and not supported_pipeline:
        return (
            False,
            "unsupported_task",
            f"The '{pipeline_tag}' task is not supported by this prompt runner.",
        )

    if backend == "mlx" and not mlx_identity:
        return (
            False,
            "mlx_conversion_required",
            "This is a standard Hugging Face repository. Choose the HF runtime or an MLX-converted repository.",
        )
    if backend == "hf" and mlx_identity:
        return (
            False,
            "mlx_runtime_required",
            "This repository contains MLX-converted weights and must use the MLX runtime.",
        )

    if "custom_code" in tags or config.get("auto_map"):
        return (
            False,
            "remote_code_required",
            "This repository requires custom remote code, which the harness does not execute.",
        )

    if mlx_qwen35_text_model and not _module_available(_MLX_QWEN35_MODULE):
        return (
            False,
            "runtime_unsupported_model_type",
            "Update mlx-lm to 0.30.7 or newer to use Qwen3.5 models.",
        )

    supported_architecture = mlx_qwen35_text_model or (
        backend == "hf" and _hf_causal_loader_supports(architectures, config)
    ) or any(str(name).endswith("ForCausalLM") for name in architectures)
    if architectures and not supported_architecture:
        return (
            False,
            "unsupported_architecture",
            f"Architecture '{architectures[0]}' is not supported by the causal language-model loader.",
        )

    filenames = [_filename(s) for s in siblings]
    has_backend_weights = any(
        filename.endswith(_WEIGHT_SUFFIXES[backend]) for filename in filenames
    )
    if has_backend_weights:
        return True, "compatible", None

    has_native_weights = any(
        filename.endswith(_ALL_NATIVE_SUFFIXES) for filename in filenames
    )
    has_gguf = any(filename.endswith(".gguf") for filename in filenames)
    if has_gguf and not has_native_weights:
        return (
            False,
            "gguf_only",
            "This repository only contains GGUF weights, which this harness cannot run.",
        )

    return (
        False,
        "no_supported_weights",
        f"No weights compatible with the {backend.upper()} backend were found.",
    )


def _memory_fit(model_size_bytes: int, available_memory_bytes: int) -> tuple[int, str]:
    estimated = estimate_memory_bytes(model_size_bytes)
    if estimated <= 0 or available_memory_bytes <= 0:
        return estimated, "unknown"
    if estimated > available_memory_bytes:
        return estimated, "too_large"
    if estimated > available_memory_bytes * TIGHT_MEMORY_FRACTION:
        return estimated, "tight"
    return estimated, "fits"


def _gated_error(model_id: str, token: Optional[str]) -> dict[str, Any]:
    if token:
        return {
            "code": "gated_access_denied",
            "message": (
                f"The configured HF_TOKEN does not have access to {model_id}. "
                "Accept the model terms or use a token with access, then try again."
            ),
            "retryable": False,
        }
    return {
        "code": "gated_token_required",
        "message": (
            f"{model_id} is gated. Accept its terms on Hugging Face and "
            "configure HF_TOKEN, then try again."
        ),
        "retryable": False,
    }


def _probe_gated_access(
    model_id: str,
    resolved_revision: str,
    filename: str,
    token: str,
) -> None:
    """HEAD one pinned artifact so token presence is not mistaken for access."""
    from huggingface_hub import get_hf_file_metadata, hf_hub_url

    url = hf_hub_url(
        repo_id=model_id,
        filename=filename,
        revision=resolved_revision,
    )
    get_hf_file_metadata(url, token=token)


def _blocked_gated_result(
    model_id: str,
    backend: Optional[str],
    revision: Optional[str],
    token: Optional[str],
    available_memory_bytes: int,
    available_disk_bytes: int,
    runtime_probe,
) -> dict[str, Any]:
    selected_backend = _normalize_backend(backend, [])
    runtime_available, runtime_code, runtime_message = runtime_probe(selected_backend)
    return {
        "model_id": model_id,
        "backend": selected_backend,
        "requested_revision": revision,
        "resolved_revision": None,
        "access": "denied" if token else "token_required",
        "compatible": None,
        "compatibility_code": "not_checked",
        "runtime_available": runtime_available,
        "runtime_code": runtime_code,
        "runtime_message": runtime_message,
        "model_size_bytes": 0,
        "estimated_memory_bytes": 0,
        "available_memory_bytes": available_memory_bytes,
        "memory_budget_bytes": available_memory_bytes,
        "memory_fit": "unknown",
        "cache_status": "missing",
        "cached_bytes": 0,
        "required_download_bytes": 0,
        "available_disk_bytes": available_disk_bytes,
        "disk_fit": "unknown",
        "can_install": False,
        "can_load": False,
        "error": _gated_error(model_id, token),
    }


def _hub_http_error(error: HfHubHTTPError, model_id: str) -> ModelPreflightError:
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status in (401, 403):
        return ModelPreflightError(
            "hub_authentication_failed",
            f"Hugging Face rejected the configured token while checking {model_id}.",
            retryable=False,
            http_status=401,
        )
    retryable = status is None or status >= 500 or status == 429
    return ModelPreflightError(
        "hub_unreachable" if retryable else "hub_request_failed",
        f"Could not reach Hugging Face for {model_id}: {error}",
        retryable=retryable,
        http_status=503 if retryable else 502,
    )


def preflight_model(
    model_id: str,
    *,
    backend: Optional[str] = None,
    revision: Optional[str] = None,
    available_memory_bytes: Optional[int] = None,
    available_disk_bytes: Optional[int] = None,
    token: Optional[str] = None,
    api=None,
    cache_dir: Optional[Path] = None,
    runtime_probe=None,
    access_probe=None,
) -> dict[str, Any]:
    """Inspect a Hub model without downloading or loading it.

    ``resolved_revision`` is always the immutable commit SHA returned by the
    Hub for successful metadata requests. Expected product blocks (gated
    access, incompatible weights, insufficient memory) are returned as
    structured results. Failures that prevent inspection raise
    :class:`ModelPreflightError`.
    """
    model_id = model_id.strip()
    if not model_id:
        raise ModelPreflightError(
            "invalid_model_id",
            "Model ID cannot be empty.",
            retryable=False,
            http_status=422,
        )

    effective_token = token or os.environ.get("HF_TOKEN") or None
    effective_runtime_probe = runtime_probe or _runtime_availability
    available = (
        _system_memory_budget_bytes()
        if available_memory_bytes is None
        else max(0, int(available_memory_bytes))
    )
    cache_root = Path(cache_dir) if cache_dir is not None else Path(HF_HUB_CACHE)
    disk_available = (
        _filesystem_free_bytes(cache_root)
        if available_disk_bytes is None
        else max(0, int(available_disk_bytes))
    )

    api_was_injected = api is not None
    if api is None:
        from huggingface_hub import HfApi

        api = HfApi()

    try:
        info = api.model_info(
            model_id,
            revision=revision,
            files_metadata=True,
            token=effective_token,
        )
    except GatedRepoError:
        return _blocked_gated_result(
            model_id,
            backend,
            revision,
            effective_token,
            available,
            disk_available,
            effective_runtime_probe,
        )
    except RevisionNotFoundError as error:
        requested = revision or "main"
        raise ModelPreflightError(
            "revision_not_found",
            f"Revision '{requested}' was not found for {model_id}.",
            retryable=False,
            http_status=404,
        ) from error
    except RepositoryNotFoundError as error:
        raise ModelPreflightError(
            "model_not_found",
            f"Model {model_id} was not found on Hugging Face.",
            retryable=False,
            http_status=404,
        ) from error
    except HfHubHTTPError as error:
        raise _hub_http_error(error, model_id) from error
    except (RequestException, TimeoutError, OSError) as error:
        raise ModelPreflightError(
            "hub_unreachable",
            f"Could not reach Hugging Face for {model_id}: {error}",
            retryable=True,
            http_status=503,
        ) from error
    except Exception as error:
        raise ModelPreflightError(
            "hub_request_failed",
            f"Could not inspect {model_id} on Hugging Face: {error}",
            retryable=True,
            http_status=502,
        ) from error

    resolved_revision = str(getattr(info, "sha", "") or "").strip()
    if not resolved_revision:
        raise ModelPreflightError(
            "missing_resolved_revision",
            f"Hugging Face did not return an immutable revision for {model_id}.",
            retryable=True,
            http_status=502,
        )

    tags = list(getattr(info, "tags", []) or [])
    selected_backend = _normalize_backend(backend, tags)
    siblings = list(getattr(info, "siblings", []) or [])
    pipeline_tag = getattr(info, "pipeline_tag", None)
    raw_config = getattr(info, "config", None) or {}
    config = raw_config if isinstance(raw_config, dict) else {}
    compatible, compatibility_code, compatibility_message = _compatibility(
        model_id, pipeline_tag, siblings, selected_backend, tags, config
    )
    runtime_available, runtime_code, runtime_message = effective_runtime_probe(
        selected_backend
    )

    model_size = _selected_weight_bytes(siblings, selected_backend)
    estimated_memory, memory_fit = _memory_fit(model_size, available)
    cache_status, cached_bytes, required_download_bytes = _exact_revision_cache_coverage(
        model_id,
        resolved_revision,
        siblings,
        selected_backend,
        cache_dir,
    )
    disk_fit = _disk_fit(required_download_bytes, disk_available)

    gated = bool(getattr(info, "gated", False))
    if gated and not effective_token:
        access = "token_required"
    elif gated:
        access = "authorized"
        # Production preflight proves that the configured token can read one
        # pinned artifact. Tests can inject a deterministic probe alongside a
        # fake HfApi; otherwise fake model metadata would trigger the network.
        effective_access_probe = access_probe
        if effective_access_probe is None and not api_was_injected:
            effective_access_probe = _probe_gated_access
        if effective_access_probe is not None:
            probe_files = _selected_weight_siblings(siblings, selected_backend) or siblings
            probe_filename = str(
                getattr(probe_files[0], "rfilename", "") or ""
            ) if probe_files else "config.json"
            try:
                effective_access_probe(
                    model_id,
                    resolved_revision,
                    probe_filename,
                    effective_token,
                )
            except GatedRepoError:
                access = "denied"
            except HfHubHTTPError as probe_error:
                status = getattr(
                    getattr(probe_error, "response", None), "status_code", None
                )
                if status in (401, 403):
                    access = "denied"
                else:
                    raise _hub_http_error(probe_error, model_id) from probe_error
            except (RequestException, TimeoutError, OSError) as probe_error:
                raise ModelPreflightError(
                    "hub_unreachable",
                    f"Could not verify gated access for {model_id}: {probe_error}",
                    retryable=True,
                    http_status=503,
                ) from probe_error
    else:
        access = "public"

    error = None
    if access in {"token_required", "denied"}:
        error = _gated_error(model_id, effective_token)
    elif not compatible:
        error = {
            "code": compatibility_code,
            "message": compatibility_message,
            "retryable": False,
        }
    elif not runtime_available:
        error = {
            "code": runtime_code,
            "message": runtime_message,
            "retryable": False,
        }
    elif disk_fit == "insufficient":
        error = {
            "code": "insufficient_disk",
            "message": (
                f"{model_id} needs {required_download_bytes} more bytes plus "
                f"download headroom, but only {disk_available} bytes are free."
            ),
            "retryable": False,
        }
    elif memory_fit == "too_large":
        error = {
            "code": "insufficient_memory",
            "message": (
                f"{model_id} is estimated to need {estimated_memory} bytes, "
                f"but the runtime memory budget is {available} bytes."
            ),
            "retryable": False,
        }

    can_install = (
        access in {"public", "authorized"}
        and compatible
        and runtime_available
        and disk_fit != "insufficient"
    )
    can_load = (
        can_install
        and memory_fit != "too_large"
    )

    return {
        "model_id": model_id,
        "backend": selected_backend,
        "requested_revision": revision,
        "resolved_revision": resolved_revision,
        "access": access,
        "compatible": compatible,
        "compatibility_code": compatibility_code,
        "runtime_available": runtime_available,
        "runtime_code": runtime_code,
        "runtime_message": runtime_message,
        "model_size_bytes": model_size,
        "weight_files": [
            str(getattr(sibling, "rfilename", "") or "")
            for sibling in _selected_weight_siblings(siblings, selected_backend)
        ],
        "install_files": _install_files(siblings, selected_backend),
        "architectures": list(config.get("architectures") or []),
        "model_type": config.get("model_type"),
        "estimated_memory_bytes": estimated_memory,
        "available_memory_bytes": available,
        "memory_budget_bytes": available,
        "memory_fit": memory_fit,
        "cache_status": cache_status,
        "cached_bytes": cached_bytes,
        "required_download_bytes": required_download_bytes,
        "available_disk_bytes": disk_available,
        "disk_fit": disk_fit,
        "can_install": can_install,
        "can_load": can_load,
        "error": error,
    }


__all__ = [
    "MEMORY_MULTIPLIER",
    "MEMORY_OVERHEAD_BYTES",
    "ModelPreflightError",
    "estimate_memory_bytes",
    "preflight_model",
]

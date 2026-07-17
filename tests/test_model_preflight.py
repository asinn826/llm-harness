"""Focused tests for Hugging Face model preflight.

All Hub and hardware inputs are injected. These tests must never make a
network request or depend on the developer machine's available memory.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from huggingface_hub.utils import (
    GatedRepoError,
    RepositoryNotFoundError,
    RevisionNotFoundError,
)
from requests import ConnectionError as RequestsConnectionError

from ui.backend.model_preflight import (
    ModelPreflightError,
    estimate_memory_bytes,
    preflight_model,
)


GIB = 1024 ** 3


@pytest.fixture(autouse=True)
def _stable_disk_capacity(monkeypatch):
    """Keep unit tests independent from the host's actual free disk."""
    monkeypatch.setattr(
        "ui.backend.model_preflight._filesystem_free_bytes",
        lambda _path: 100 * GIB,
    )


def _sibling(filename: str, size: int):
    return SimpleNamespace(rfilename=filename, size=size)


def _hub_error(error_type, message: str):
    """Construct Hub errors across huggingface_hub versions."""
    response = MagicMock(status_code=403, headers={}, request=MagicMock())
    try:
        return error_type(message, response=response)
    except TypeError:
        return error_type(message)


def _info(
    *,
    sha: str = "commit-sha-123",
    gated=False,
    pipeline_tag: str | None = "text-generation",
    tags=None,
    siblings=None,
    config=None,
):
    return SimpleNamespace(
        sha=sha,
        gated=gated,
        pipeline_tag=pipeline_tag,
        tags=list(tags or ["text-generation", "safetensors"]),
        siblings=list(siblings or [_sibling("model.safetensors", 2 * GIB)]),
        config=dict(config or {}),
    )


def test_public_model_resolves_to_immutable_revision(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    api = MagicMock()
    api.model_info.return_value = _info(sha="resolved-abc")

    result = preflight_model(
        "org/public-model",
        backend="hf",
        revision="release-v1",
        available_memory_bytes=16 * GIB,
        api=api,
    )

    api.model_info.assert_called_once_with(
        "org/public-model",
        revision="release-v1",
        files_metadata=True,
        token=None,
    )
    assert result["requested_revision"] == "release-v1"
    assert result["resolved_revision"] == "resolved-abc"
    assert result["access"] == "public"
    assert result["compatible"] is True
    assert result["compatibility_code"] == "compatible"
    assert result["can_load"] is True
    assert result["error"] is None


def test_gated_model_without_token_is_actionable_result(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    api = MagicMock()
    api.model_info.return_value = _info(gated="manual")

    result = preflight_model(
        "org/gated-model",
        available_memory_bytes=16 * GIB,
        api=api,
    )

    assert result["access"] == "token_required"
    assert result["can_load"] is False
    assert result["error"] == {
        "code": "gated_token_required",
        "message": (
            "org/gated-model is gated. Accept its terms on Hugging Face and "
            "configure HF_TOKEN, then try again."
        ),
        "retryable": False,
    }


def test_gated_hub_error_without_token_is_actionable_result(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    api = MagicMock()
    api.model_info.side_effect = _hub_error(GatedRepoError, "access denied")

    result = preflight_model(
        "org/gated-model",
        revision="v2",
        available_memory_bytes=16 * GIB,
        api=api,
    )

    assert result["requested_revision"] == "v2"
    assert result["resolved_revision"] is None
    assert result["access"] == "token_required"
    assert result["compatible"] is None
    assert result["memory_fit"] == "unknown"
    assert result["can_load"] is False
    assert result["error"]["code"] == "gated_token_required"


def test_gated_model_with_token_is_authorized(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "secret-token")
    api = MagicMock()
    api.model_info.return_value = _info(gated="auto")
    access_probe = MagicMock()

    result = preflight_model(
        "org/gated-model",
        available_memory_bytes=16 * GIB,
        api=api,
        access_probe=access_probe,
    )

    api.model_info.assert_called_once_with(
        "org/gated-model",
        revision=None,
        files_metadata=True,
        token="secret-token",
    )
    assert result["access"] == "authorized"
    assert result["can_load"] is True
    access_probe.assert_called_once_with(
        "org/gated-model",
        "commit-sha-123",
        "model.safetensors",
        "secret-token",
    )


def test_gated_model_with_token_but_no_file_access_is_denied(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "secret-token")
    api = MagicMock()
    api.model_info.return_value = _info(gated="manual")
    access_probe = MagicMock(
        side_effect=_hub_error(GatedRepoError, "terms not accepted")
    )

    result = preflight_model(
        "org/gated-model",
        available_memory_bytes=16 * GIB,
        api=api,
        access_probe=access_probe,
    )

    assert result["access"] == "denied"
    assert result["can_install"] is False
    assert result["can_load"] is False
    assert result["error"]["code"] == "gated_access_denied"


@pytest.mark.parametrize(
    ("info", "expected_code"),
    [
        (
            _info(
                tags=["gguf", "text-generation"],
                siblings=[_sibling("model-q4.gguf", 3 * GIB)],
            ),
            "gguf_only",
        ),
        (
            _info(pipeline_tag="text-classification"),
            "unsupported_task",
        ),
        (
            _info(siblings=[_sibling("README.md", 100)]),
            "no_supported_weights",
        ),
    ],
)
def test_incompatible_repositories_are_blocked(info, expected_code):
    api = MagicMock()
    api.model_info.return_value = info

    result = preflight_model(
        "org/incompatible",
        backend="hf",
        available_memory_bytes=16 * GIB,
        api=api,
        token="test-token",
    )

    assert result["compatible"] is False
    assert result["compatibility_code"] == expected_code
    assert result["can_load"] is False


def test_hf_any_to_any_model_with_text_input_is_accepted():
    api = MagicMock()
    api.model_info.return_value = _info(
        pipeline_tag="any-to-any",
        tags=["any-to-any", "transformers", "safetensors"],
        config={
            "architectures": ["Gemma4ForConditionalGeneration"],
            "model_type": "gemma4",
            "text_config": {"model_type": "gemma4_text"},
        },
    )

    result = preflight_model(
        "google/gemma-4-E4B-it",
        backend="hf",
        available_memory_bytes=32 * GIB,
        api=api,
        token="test-token",
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["compatible"] is True
    assert result["compatibility_code"] == "compatible"
    assert result["can_load"] is True
    assert result["error"] is None


@pytest.mark.parametrize(
    "pipeline_tag",
    ["text-generation", "image-text-to-text"],
)
def test_mlx_qwen35_text_loader_accepts_hub_task_variants(
    monkeypatch, pipeline_tag
):
    monkeypatch.setattr(
        "ui.backend.model_preflight._module_available",
        lambda module: module == "mlx_lm.models.qwen3_5",
    )
    api = MagicMock()
    api.model_info.return_value = _info(
        pipeline_tag=pipeline_tag,
        tags=["mlx", pipeline_tag, "safetensors"],
        config={
            "architectures": ["Qwen3_5ForConditionalGeneration"],
            "model_type": "qwen3_5",
        },
    )

    result = preflight_model(
        "mlx-community/Qwen3.5-9B-MLX-4bit",
        backend="mlx",
        available_memory_bytes=16 * GIB,
        api=api,
        token="test-token",
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["compatible"] is True
    assert result["compatibility_code"] == "compatible"
    assert result["can_load"] is True
    assert result["error"] is None


def test_unrelated_mlx_vision_model_remains_blocked(monkeypatch):
    monkeypatch.setattr(
        "ui.backend.model_preflight._module_available",
        lambda _module: True,
    )
    api = MagicMock()
    api.model_info.return_value = _info(
        pipeline_tag="image-text-to-text",
        tags=["mlx", "image-text-to-text", "safetensors"],
        config={
            "architectures": ["LlavaForConditionalGeneration"],
            "model_type": "llava",
        },
    )

    result = preflight_model(
        "mlx-community/vision-model",
        backend="mlx",
        available_memory_bytes=16 * GIB,
        api=api,
        token="test-token",
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["compatibility_code"] == "unsupported_task"
    assert result["can_load"] is False


def test_qwen35_conditional_architecture_uses_registered_hf_causal_loader():
    api = MagicMock()
    api.model_info.return_value = _info(
        config={
            "architectures": ["Qwen3_5ForConditionalGeneration"],
            "model_type": "qwen3_5",
        },
    )

    result = preflight_model(
        "Qwen/Qwen3.5-9B",
        backend="hf",
        available_memory_bytes=16 * GIB,
        api=api,
        token="test-token",
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["compatible"] is True
    assert result["compatibility_code"] == "compatible"
    assert result["can_load"] is True
    assert result["error"] is None


def test_mlx_qwen35_requires_runtime_model_support(monkeypatch):
    monkeypatch.setattr(
        "ui.backend.model_preflight._module_available",
        lambda _module: False,
    )
    api = MagicMock()
    api.model_info.return_value = _info(
        pipeline_tag="image-text-to-text",
        tags=["mlx", "image-text-to-text", "safetensors"],
        config={
            "architectures": ["Qwen3_5ForConditionalGeneration"],
            "model_type": "qwen3_5",
        },
    )

    result = preflight_model(
        "mlx-community/Qwen3.5-9B-MLX-4bit",
        backend="mlx",
        available_memory_bytes=16 * GIB,
        api=api,
        token="test-token",
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["compatibility_code"] == "runtime_unsupported_model_type"
    assert result["can_load"] is False
    assert result["error"]["message"] == (
        "Update mlx-lm to 0.30.7 or newer to use Qwen3.5 models."
    )


def test_preflight_blocks_custom_remote_code():
    api = MagicMock()
    api.model_info.return_value = _info(
        tags=["text-generation", "custom_code", "safetensors"],
        config={"auto_map": {"AutoModelForCausalLM": "model.CustomModel"}},
    )

    result = preflight_model(
        "org/custom-model",
        backend="hf",
        available_memory_bytes=16 * GIB,
        api=api,
        token="test-token",
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["compatibility_code"] == "remote_code_required"
    assert result["can_load"] is False


def test_preflight_rejects_standard_hf_weights_for_mlx_runtime():
    api = MagicMock()
    api.model_info.return_value = _info(tags=["text-generation", "safetensors"])

    result = preflight_model(
        "Qwen/Qwen2.5-0.5B-Instruct",
        backend="mlx",
        available_memory_bytes=16 * GIB,
        api=api,
        token="test-token",
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["compatibility_code"] == "mlx_conversion_required"
    assert result["can_load"] is False


def test_preflight_returns_exact_install_artifact_plan():
    api = MagicMock()
    api.model_info.return_value = _info(siblings=[
        _sibling("model-00001-of-00002.safetensors", 1 * GIB),
        _sibling("model-00002-of-00002.safetensors", 1 * GIB),
        _sibling("pytorch_model.bin", 3 * GIB),
        _sibling("model.safetensors.index.json", 500),
        _sibling("tokenizer.json", 1000),
        _sibling("README.md", 2000),
        _sibling("trainer_state.json", 2000),
        _sibling("training_args.bin", 2000),
    ])

    result = preflight_model(
        "org/planned-model",
        backend="hf",
        available_memory_bytes=16 * GIB,
        api=api,
        token="test-token",
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["weight_files"] == [
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
    ]
    assert "pytorch_model.bin" not in result["install_files"]
    assert "model.safetensors.index.json" in result["install_files"]
    assert "tokenizer.json" in result["install_files"]
    assert "README.md" not in result["install_files"]
    assert "trainer_state.json" not in result["install_files"]
    assert "training_args.bin" not in result["weight_files"]
    assert "training_args.bin" not in result["install_files"]


@pytest.mark.parametrize(
    ("available_memory", "expected_fit", "expected_can_load"),
    [
        (8 * GIB, "fits", True),
        (3 * GIB, "tight", True),
        (2 * GIB, "too_large", False),
    ],
)
def test_size_uses_one_weight_family_and_computes_memory_fit(
    available_memory, expected_fit, expected_can_load
):
    api = MagicMock()
    api.model_info.return_value = _info(siblings=[
        _sibling("model-00001-of-00002.safetensors", 1 * GIB),
        _sibling("model-00002-of-00002.safetensors", 1 * GIB),
        # A duplicate PyTorch representation must not be double counted.
        _sibling("pytorch_model.bin", 3 * GIB),
        _sibling("README.md", 5000),
    ])

    result = preflight_model(
        "org/sized-model",
        backend="hf",
        available_memory_bytes=available_memory,
        api=api,
        token="test-token",
    )

    assert result["model_size_bytes"] == 2 * GIB
    assert result["estimated_memory_bytes"] == estimate_memory_bytes(2 * GIB)
    assert result["available_memory_bytes"] == available_memory
    assert result["memory_fit"] == expected_fit
    assert result["can_load"] is expected_can_load


def test_default_memory_budget_uses_total_physical_memory(monkeypatch, tmp_path):
    api = MagicMock()
    api.model_info.return_value = _info(
        siblings=[_sibling("model.safetensors", 8 * GIB)]
    )
    monkeypatch.setattr(
        "psutil.virtual_memory",
        lambda: SimpleNamespace(total=16 * GIB, available=2 * GIB),
    )

    result = preflight_model(
        "org/sequential-model",
        backend="hf",
        api=api,
        token="test-token",
        cache_dir=tmp_path,
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["memory_budget_bytes"] == 16 * GIB
    # Keep the established response field as a backwards-compatible alias.
    assert result["available_memory_bytes"] == 16 * GIB
    assert result["memory_fit"] == "fits"
    assert result["can_load"] is True


def test_model_that_cannot_fit_memory_can_still_be_installed(tmp_path):
    api = MagicMock()
    api.model_info.return_value = _info()

    result = preflight_model(
        "org/large-model",
        backend="hf",
        available_memory_bytes=1 * GIB,
        api=api,
        token="test-token",
        cache_dir=tmp_path,
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["memory_fit"] == "too_large"
    assert result["can_load"] is False
    assert result["can_install"] is True
    assert result["error"]["code"] == "insufficient_memory"


def test_insufficient_disk_blocks_install_before_download(tmp_path):
    api = MagicMock()
    api.model_info.return_value = _info(
        siblings=[
            _sibling("config.json", 1_000),
            _sibling("model.safetensors", 2 * GIB),
        ]
    )

    result = preflight_model(
        "org/disk-heavy-model",
        backend="hf",
        available_memory_bytes=16 * GIB,
        available_disk_bytes=2 * GIB,
        api=api,
        token="test-token",
        cache_dir=tmp_path,
        runtime_probe=lambda _backend: (True, "available", None),
    )

    assert result["required_download_bytes"] == 2 * GIB + 1_000
    assert result["disk_fit"] == "insufficient"
    assert result["can_install"] is False
    assert result["can_load"] is False
    assert result["error"]["code"] == "insufficient_disk"


def test_revision_not_found_is_non_retryable_structured_exception():
    api = MagicMock()
    api.model_info.side_effect = _hub_error(RevisionNotFoundError, "missing revision")

    with pytest.raises(ModelPreflightError) as raised:
        preflight_model(
            "org/model",
            revision="does-not-exist",
            available_memory_bytes=8 * GIB,
            api=api,
        )

    error = raised.value
    assert error.code == "revision_not_found"
    assert error.http_status == 404
    assert error.retryable is False
    assert error.to_dict() == {
        "code": "revision_not_found",
        "message": "Revision 'does-not-exist' was not found for org/model.",
        "retryable": False,
    }


def test_repository_not_found_is_non_retryable_structured_exception():
    api = MagicMock()
    api.model_info.side_effect = _hub_error(RepositoryNotFoundError, "missing repository")

    with pytest.raises(ModelPreflightError) as raised:
        preflight_model(
            "org/missing",
            available_memory_bytes=8 * GIB,
            api=api,
            token="test-token",
        )

    assert raised.value.to_dict() == {
        "code": "model_not_found",
        "message": "Model org/missing was not found on Hugging Face.",
        "retryable": False,
    }
    assert raised.value.http_status == 404


def test_network_failure_is_retryable_and_not_misclassified():
    api = MagicMock()
    api.model_info.side_effect = RequestsConnectionError("network down")

    with pytest.raises(ModelPreflightError) as raised:
        preflight_model(
            "org/model",
            available_memory_bytes=8 * GIB,
            api=api,
            token="test-token",
        )

    error = raised.value
    assert error.code == "hub_unreachable"
    assert error.http_status == 503
    assert error.retryable is True
    assert "network down" in error.message


def test_missing_resolved_sha_never_returns_a_mutable_preflight():
    api = MagicMock()
    api.model_info.return_value = _info(sha="")

    with pytest.raises(ModelPreflightError) as raised:
        preflight_model(
            "org/model",
            revision="main",
            available_memory_bytes=8 * GIB,
            api=api,
            token="test-token",
        )

    assert raised.value.code == "missing_resolved_revision"
    assert raised.value.http_status == 502
    assert raised.value.retryable is True


def test_runtime_unavailable_blocks_loading_with_actionable_result(tmp_path):
    api = MagicMock()
    api.model_info.return_value = _info()

    result = preflight_model(
        "org/model",
        backend="hf",
        available_memory_bytes=8 * GIB,
        api=api,
        token="test-token",
        cache_dir=tmp_path,
        runtime_probe=lambda _backend: (
            False,
            "runtime_missing_dependencies",
            "Install PyTorch and Transformers to use this runtime.",
        ),
    )

    assert result["runtime_available"] is False
    assert result["runtime_code"] == "runtime_missing_dependencies"
    assert result["runtime_message"] == (
        "Install PyTorch and Transformers to use this runtime."
    )
    assert result["can_load"] is False
    assert result["error"] == {
        "code": "runtime_missing_dependencies",
        "message": "Install PyTorch and Transformers to use this runtime.",
        "retryable": False,
    }


def _snapshot_dir(cache_root, model_id: str, revision: str):
    return (
        cache_root
        / f"models--{model_id.replace('/', '--')}"
        / "snapshots"
        / revision
    )


def _cache_info(sha="exact-sha"):
    return _info(
        sha=sha,
        siblings=[
            _sibling("config.json", 7),
            _sibling("tokenizer.json", 11),
            _sibling("model.safetensors.index.json", 19),
            _sibling("model-00001-of-00002.safetensors", 13),
            _sibling("model-00002-of-00002.safetensors", 17),
        ],
    )


def test_exact_revision_cache_status_is_missing_when_snapshot_absent(tmp_path):
    api = MagicMock()
    api.model_info.return_value = _cache_info()
    # A complete snapshot of another revision must not count.
    other = _snapshot_dir(tmp_path, "org/cached-model", "other-sha")
    other.mkdir(parents=True)
    (other / "model-00001-of-00002.safetensors").write_bytes(b"x" * 13)
    (other / "model-00002-of-00002.safetensors").write_bytes(b"x" * 17)

    result = preflight_model(
        "org/cached-model",
        backend="hf",
        available_memory_bytes=8 * GIB,
        api=api,
        token="test-token",
        cache_dir=tmp_path,
    )

    assert result["resolved_revision"] == "exact-sha"
    assert result["cache_status"] == "missing"
    assert result["cached_bytes"] == 0
    assert result["required_download_bytes"] == 67


def test_metadata_only_exact_revision_cache_is_partial(tmp_path):
    api = MagicMock()
    api.model_info.return_value = _cache_info()
    snapshot = _snapshot_dir(tmp_path, "org/cached-model", "exact-sha")
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_bytes(b"x" * 7)
    (snapshot / "tokenizer.json").write_bytes(b"x" * 11)

    result = preflight_model(
        "org/cached-model",
        backend="hf",
        available_memory_bytes=8 * GIB,
        api=api,
        token="test-token",
        cache_dir=tmp_path,
    )

    assert result["cache_status"] == "partial"
    assert result["cached_bytes"] == 18
    assert result["required_download_bytes"] == 49


def test_exact_revision_cache_is_complete_only_with_full_file_coverage(tmp_path):
    api = MagicMock()
    api.model_info.return_value = _cache_info()
    snapshot = _snapshot_dir(tmp_path, "org/cached-model", "exact-sha")
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_bytes(b"x" * 7)
    (snapshot / "tokenizer.json").write_bytes(b"x" * 11)
    (snapshot / "model.safetensors.index.json").write_bytes(b"x" * 19)
    (snapshot / "model-00001-of-00002.safetensors").write_bytes(b"x" * 13)
    (snapshot / "model-00002-of-00002.safetensors").write_bytes(b"x" * 17)

    result = preflight_model(
        "org/cached-model",
        backend="hf",
        available_memory_bytes=8 * GIB,
        api=api,
        token="test-token",
        cache_dir=tmp_path,
    )

    assert result["cache_status"] == "complete"
    assert result["cached_bytes"] == 67
    assert result["required_download_bytes"] == 0


def test_missing_sharded_weight_index_is_partial(tmp_path):
    api = MagicMock()
    api.model_info.return_value = _cache_info()
    snapshot = _snapshot_dir(tmp_path, "org/cached-model", "exact-sha")
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_bytes(b"x" * 7)
    (snapshot / "tokenizer.json").write_bytes(b"x" * 11)
    (snapshot / "model-00001-of-00002.safetensors").write_bytes(b"x" * 13)
    (snapshot / "model-00002-of-00002.safetensors").write_bytes(b"x" * 17)

    result = preflight_model(
        "org/cached-model",
        backend="hf",
        available_memory_bytes=8 * GIB,
        api=api,
        token="test-token",
        cache_dir=tmp_path,
    )

    assert result["cache_status"] == "partial"


def test_wrong_size_cached_weight_is_partial(tmp_path):
    api = MagicMock()
    api.model_info.return_value = _cache_info()
    snapshot = _snapshot_dir(tmp_path, "org/cached-model", "exact-sha")
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_bytes(b"x" * 7)
    (snapshot / "tokenizer.json").write_bytes(b"x" * 11)
    (snapshot / "model.safetensors.index.json").write_bytes(b"x" * 19)
    (snapshot / "model-00001-of-00002.safetensors").write_bytes(b"x" * 12)
    (snapshot / "model-00002-of-00002.safetensors").write_bytes(b"x" * 17)

    result = preflight_model(
        "org/cached-model",
        backend="hf",
        available_memory_bytes=8 * GIB,
        api=api,
        token="test-token",
        cache_dir=tmp_path,
    )

    assert result["cache_status"] == "partial"

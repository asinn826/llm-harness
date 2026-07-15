"""Revision pinning for model loading.

These tests keep a mutable Hub ref (``main`` or a tag) from leaking past
preflight.  Once a model has been resolved to a commit SHA, every cache lookup
and runtime loader must use that exact revision.
"""

from unittest.mock import MagicMock, patch


def test_same_model_different_revision_is_reloaded():
    from ui.backend.model_manager import ModelManager

    manager = ModelManager()
    tokenizer = MagicMock(chat_template=None)
    model = MagicMock()

    with (
        patch.object(manager, "_load_mlx", return_value=(tokenizer, model)) as load,
        patch.object(manager, "_unload_internal", wraps=manager._unload_internal),
    ):
        first = manager.load_model("org/model", "mlx", revision="sha-one")
        same = manager.load_model("org/model", "mlx", revision="sha-one")
        second = manager.load_model("org/model", "mlx", revision="sha-two")

    assert first.revision == "sha-one"
    assert same.revision == "sha-one"
    assert second.revision == "sha-two"
    assert load.call_count == 2
    assert load.call_args_list[0].kwargs["revision"] == "sha-one"
    assert load.call_args_list[1].kwargs["revision"] == "sha-two"


def test_mlx_loader_forwards_revision_to_cache_and_runtime():
    from ui.backend.model_manager import ModelManager

    manager = ModelManager()
    fake_model = object()
    fake_tokenizer = object()

    with (
        patch("huggingface_hub.try_to_load_from_cache", return_value="/cached/config") as cache,
        patch("mlx_lm.load", return_value=(fake_model, fake_tokenizer)) as load,
    ):
        tokenizer, model = manager._load_mlx("org/model", revision="sha-mlx")

    cache.assert_called_once_with("org/model", "config.json", revision="sha-mlx")
    load.assert_called_once_with("org/model", revision="sha-mlx")
    assert tokenizer is fake_tokenizer
    assert model is fake_model


def test_hf_loader_forwards_revision_to_cache_processor_and_model():
    from ui.backend.model_manager import ModelManager

    manager = ModelManager()
    processor = MagicMock()
    raw_model = MagicMock()
    loaded_model = MagicMock()
    raw_model.to.return_value = loaded_model

    with (
        patch("ui.backend.model_manager._HAS_TORCH", True),
        patch("ui.backend.model_manager.torch") as torch,
        patch("huggingface_hub.try_to_load_from_cache", return_value="/cached/config") as cache,
        patch("transformers.AutoProcessor.from_pretrained", return_value=processor) as load_processor,
        patch("transformers.AutoModelForCausalLM.from_pretrained", return_value=raw_model) as load_model,
        patch.dict("ui.backend.model_manager.os.environ", {"HF_TOKEN": "test-token"}, clear=False),
    ):
        torch.backends.mps.is_available.return_value = False
        torch.float16 = "float16"
        result_processor, result_model = manager._load_hf("org/model", revision="sha-hf")

    cache.assert_called_once_with("org/model", "config.json", revision="sha-hf")
    load_processor.assert_called_once_with(
        "org/model", token="test-token", revision="sha-hf"
    )
    load_model.assert_called_once_with(
        "org/model",
        torch_dtype="float16",
        token="test-token",
        revision="sha-hf",
    )
    assert result_processor is processor
    assert result_model is loaded_model

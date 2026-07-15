"""Downloaded-library discovery must ignore metadata-only Hub cache entries."""

from pathlib import Path


def _snapshot(root: Path, model_id: str) -> Path:
    path = root / f"models--{model_id.replace('/', '--')}" / "snapshots" / "sha"
    path.mkdir(parents=True)
    return path


def test_find_cached_models_requires_weight_artifact(monkeypatch, tmp_path):
    from main import find_cached_models

    hub = tmp_path / ".cache" / "huggingface" / "hub"
    metadata = _snapshot(hub, "org/metadata-only")
    (metadata / "README.md").write_text("model card")
    (metadata / "config.json").write_text("{}")

    installed = _snapshot(hub, "org/installed")
    (installed / "config.json").write_text("{}")
    (installed / "model.safetensors").write_bytes(b"weights")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert find_cached_models() == ["org/installed"]


def test_find_cached_models_accepts_sharded_weights(monkeypatch, tmp_path):
    from main import find_cached_models

    hub = tmp_path / ".cache" / "huggingface" / "hub"
    installed = _snapshot(hub, "org/sharded")
    shard_dir = installed / "weights"
    shard_dir.mkdir()
    (shard_dir / "model-00001-of-00002.safetensors").write_bytes(b"weights")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert find_cached_models() == ["org/sharded"]


def test_detect_backend_defaults_generic_hub_models_to_hf(monkeypatch):
    import main

    monkeypatch.setattr(main, "_USE_MLX", True)
    assert main.detect_backend("Qwen/Qwen2.5-0.5B-Instruct") == "hf"
    assert main.detect_backend("mlx-community/Qwen2.5-0.5B-Instruct-4bit") == "mlx"

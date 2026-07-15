"""Regression coverage for the packaged desktop's runnable recommendations."""

import json
from pathlib import Path


REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "ui" / "backend" / "recommended_models.json"
)

EXPECTED_DEFAULTS = {
    "mlx-community/Qwen2.5-0.5B-Instruct-4bit": {
        "size_bytes": 278064920,
        "context_window": 32768,
        "quantization": "4-bit",
    },
    "mlx-community/SmolLM2-360M-Instruct": {
        "size_bytes": 723674815,
        "context_window": 8192,
        "quantization": "bf16",
    },
    "mlx-community/SmolLM2-1.7B-Instruct": {
        "size_bytes": 3422777902,
        "context_window": 8192,
        "quantization": "bf16",
    },
}


def test_curated_defaults_match_live_preflight_verified_mlx_repositories():
    models = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    by_id = {model["id"]: model for model in models}

    assert set(by_id) == set(EXPECTED_DEFAULTS)
    for model_id, expected in EXPECTED_DEFAULTS.items():
        model = by_id[model_id]
        assert model["backend"] == "mlx"
        assert model["license"] == "apache-2.0"
        assert model["size_bytes"] == expected["size_bytes"]
        assert model["context_window"] == expected["context_window"]
        assert model["quantization"] == expected["quantization"]
        assert model["hf_url"] == f"https://huggingface.co/{model_id}"

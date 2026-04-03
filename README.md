# llm-harness

"We have claude code at home!"

Claude code at home: 

## Run

```bash
pip install -r requirements.txt
python3 main.py --model Qwen/Qwen2.5-1.5B-Instruct                 # fast, less capable
python3 main.py --model Qwen/Qwen2.5-7B-Instruct                   # good balance
python3 main.py --model mlx-community/Qwen2.5-14B-Instruct-4bit    # recommended sweet spot
python3.11 main.py --model google/gemma-4-E4B-it --no-mlx          # Gemma 4 (requires Python 3.11+)
```

## HuggingFace token

A token is optional for public models but required for gated ones (e.g. Llama). To use one, create a `.env` file in this directory:

```
HF_TOKEN=hf_...
```

Get a token at huggingface.co/settings/tokens. For gated models, you also need to accept the model's terms on its HuggingFace page.

## Model recommendations

Tested on Apple Silicon (36GB unified memory). Larger models follow instructions more reliably and need fewer few-shot examples in the prompt.

On Apple Silicon, [mlx-lm](https://github.com/ml-explore/mlx-examples/tree/main/llms) is used automatically (5-10x faster than HuggingFace transformers on MPS). Pass `--no-mlx` to force the HuggingFace backend.

Use pre-quantized `mlx-community` models — fp16 models are too large to run even at 14B on 36GB once you account for the KV cache and Metal overhead.

| Model | Size | Notes |
|---|---|---|
| `Qwen/Qwen2.5-1.5B-Instruct` | ~3GB | Struggles with tool use, needs heavy prompting |
| `Qwen/Qwen2.5-7B-Instruct` | ~14GB | Decent, still misses edge cases |
| `mlx-community/Qwen2.5-14B-Instruct-4bit` | ~8GB | Recommended — good tool use, fast |
| `mlx-community/Qwen2.5-32B-Instruct-4bit` | ~18GB | Best quality, still fits in 36GB |
| `mistralai/Mistral-7B-Instruct-v0.3` | ~14GB | Good alternative; strong JSON formatting |
| `meta-llama/Llama-3.1-8B-Instruct` | ~16GB | Another solid alternative at the 7-8B tier |

Models that support it (e.g. Gemma 4) are loaded via the `--no-mlx` HuggingFace backend. mlx-lm support for newer architectures lags a few days behind releases.

```bash
python3.11 main.py --model google/gemma-4-E4B-it --no-mlx
```

Gemma 4 requires Python 3.10+ and the following extras:

```bash
pip3.11 install torch accelerate torchvision pillow
pip3.11 install git+https://github.com/huggingface/transformers.git
```

## Chain-of-thought

Chain-of-thought (thinking mode) is disabled by default. For the current tool-use workload — short commands, message sending, lookups — it adds latency with no benefit.

If you expand the harness to handle more complex tasks (multi-step reasoning, coding, math), re-enable it by changing `enable_thinking=False` to `True` in `make_model_fn_hf` in `main.py`. Only models that explicitly support the `enable_thinking` flag (e.g. Gemma 4) will use it; others fall back gracefully.

## Python version

The HuggingFace backend requires Python 3.10+. mlx-lm works on 3.9+. If you're on the system Python (3.9), install a newer version:

```bash
brew install python@3.11
```

Then run with `python3.11` and `pip3.11`.

## Structure

| File | Purpose |
|---|---|
| `tools.py` | What the model can do |
| `harness.py` | The generation + tool-call loop |
| `cli.py` | Terminal UI |
| `main.py` | Entry point |

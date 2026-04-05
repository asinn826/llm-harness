# llm-harness

"We have claude code at home!"

Claude code at home: 

## Run

```bash
pip install -r requirements.txt
python3.11 main.py --model mlx-community/Qwen3.5-9B-MLX-4bit       # recommended — fast, reliable tool use
python3.11 main.py --model google/gemma-4-E4B-it --no-mlx          # Gemma 4 (requires --no-mlx)
```

## HuggingFace token

A token is optional for public models but required for gated ones (e.g. Llama). To use one, create a `.env` file in this directory:

```
HF_TOKEN=hf_...
```

Get a token at huggingface.co/settings/tokens. For gated models, you also need to accept the model's terms on its HuggingFace page.

## Model recommendations

Tested on Apple Silicon (36GB unified memory). Larger models follow instructions more reliably and handle longer tool chains.

On Apple Silicon, [mlx-lm](https://github.com/ml-explore/mlx-examples/tree/main/llms) is used automatically (5-10x faster than HuggingFace transformers on MPS). Pass `--no-mlx` to force the HuggingFace backend.

| Model | Size | Backend | Notes |
|---|---|---|---|
| `mlx-community/Qwen3.5-9B-MLX-4bit` | ~5GB | mlx-lm | **Recommended** — fast, reliable tool use, handles multi-step chains |
| `Qwen/Qwen3.5-4B` | ~8GB | mlx-lm | Smaller/faster, good for simple tasks |
| `mlx-community/Qwen3.5-27B-4bit-DWQ` | ~15GB | mlx-lm | Best quality, fits in 36GB |
| `google/gemma-4-E4B-it` | ~8GB | HF (`--no-mlx`) | Multimodal, creative but inconsistent tool call formatting |
| `mistralai/Mistral-7B-Instruct-v0.3` | ~14GB | mlx-lm | Good alternative; strong JSON formatting |
| `meta-llama/Llama-3.1-8B-Instruct` | ~16GB | mlx-lm | Solid at the 8B tier |

### Known model quirks

- **Gemma 4**: produces many `call:` format variations instead of clean JSON. The harness parser handles most of them, but multi-step chains (3+ tools) are unreliable at 4B. Requires `--no-mlx` and Python 3.11+.
- **Small models (<4B)**: prone to repetition loops (mitigated by repetition penalty), ignoring system prompt rules, and dropping tool chains mid-execution.
- **Qwen 3.5 9B**: most reliable for tool calling in our testing. Handles 3-4 step chains, follows message formatting rules, and produces clean JSON.

### Gemma 4 setup

Gemma 4 requires the HuggingFace backend (`--no-mlx`), Python 3.10+, and extra dependencies:

```bash
pip3.11 install torch accelerate torchvision pillow
pip3.11 install git+https://github.com/huggingface/transformers.git
python3.11 main.py --model google/gemma-4-E4B-it --no-mlx
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
| `tools.py` | What the model can do (shell, files, calculator, web, iMessage, calendar) |
| `harness.py` | The generation + tool-call loop + system prompt |
| `cli.py` | Terminal UI (raw input, Ctrl+O overlay, streaming, Markdown rendering) |
| `main.py` | Entry point (model loading, streaming, MLX/HF backend selection) |

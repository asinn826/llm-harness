# llm-harness

"We have claude code at home!"

Claude code at home: 

## Run

```bash
pip install -r requirements.txt
python3.11 main.py --model google/gemma-4-E4B-it --no-mlx          # daily use — runs cool, good quality
python3.11 main.py --model mlx-community/Qwen3.5-4B-OptiQ-4bit    # middle ground — clean tool calls
python3.11 main.py --model mlx-community/Qwen3.5-9B-MLX-4bit      # best quality — runs hot
```

## HuggingFace token

A token is optional for public models but required for gated ones (e.g. Llama). To use one, create a `.env` file in this directory:

```
HF_TOKEN=hf_...
```

Get a token at huggingface.co/settings/tokens. For gated models, you also need to accept the model's terms on its HuggingFace page.

## Model recommendations

Tested on Apple Silicon (36GB unified memory). Model choice is a tradeoff between tool-calling quality and laptop heat — mlx-lm is faster but pushes the GPU harder, while the HF backend (`--no-mlx`) runs cooler.

On Apple Silicon, [mlx-lm](https://github.com/ml-explore/mlx-examples/tree/main/llms) is used automatically (5-10x faster than HuggingFace transformers on MPS). Pass `--no-mlx` to force the HuggingFace backend (slower but cooler).

| Model | Memory | Backend | Heat | Quality | Best for |
|---|---|---|---|---|---|
| `google/gemma-4-E4B-it` | ~8GB | HF (`--no-mlx`) | 🟢 Low | Good reasoning, inconsistent formatting | **Daily use** — runs cool, parser handles quirks |
| `mlx-community/Qwen3.5-4B-OptiQ-4bit` | ~3GB | mlx-lm | 🟡 Medium | Clean JSON, good for 1-2 tool chains | Quick tasks, lower heat than 9B |
| `mlx-community/Qwen3.5-9B-MLX-4bit` | ~5GB | mlx-lm | 🔴 Hot | Best tool calling, reliable multi-step chains | **Best quality** — use for complex tasks |

> **Note**: fp16 models ≥9B (e.g. `Qwen/Qwen3.5-9B`) OOM on 36GB via `--no-mlx`. Use quantized mlx-community models for anything above 4B.

### Known model quirks

- **Gemma 4 E4B**: produces many `call:` format variations (`call:tool:name:`, `call:tool_name:`, missing quotes, etc.) instead of clean JSON. The harness parser handles most of them. Good reasoning but multi-step chains (3+ tools) sometimes stall. Requires `--no-mlx` and Python 3.11+.
- **Qwen 3.5 9B 4-bit**: most reliable for tool calling — handles 3-4 step chains, clean JSON, follows message formatting rules. Runs hot on sustained use due to mlx-lm saturating the GPU.
- **Qwen 3.5 4B 4-bit**: good middle ground. Better formatting than Gemma, less heat than 9B. May drop longer chains like Gemma.
- **Small models (<4B)**: prone to repetition loops, ignoring system prompt rules, and dropping tool chains mid-execution.

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

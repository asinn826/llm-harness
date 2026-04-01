# llm-harness

"We have claude code at home!"

Claude code at home: 

## Run

```bash
pip install -r requirements.txt
python3 main.py --model Qwen/Qwen2.5-1.5B-Instruct  # fast, less capable
python3 main.py --model Qwen/Qwen2.5-7B-Instruct    # slower, more capable
python3 main.py --model Qwen/Qwen2.5-14B-Instruct   # recommended sweet spot
```

## Model recommendations

Tested on Apple Silicon (36GB unified memory). Larger models follow instructions more reliably and need fewer few-shot examples in the prompt.

| Model | VRAM | Notes |
|---|---|---|
| `Qwen2.5-1.5B-Instruct` | ~3GB | Struggles with tool use, needs heavy prompting |
| `Qwen2.5-7B-Instruct` | ~14GB | Decent, still misses edge cases |
| `Qwen2.5-14B-Instruct` | ~28GB | Recommended — good tool use, fits comfortably |
| `Qwen2.5-32B-Instruct` | ~64GB (fp16) / ~20GB (4-bit) | Requires quantization; use `mlx-lm` for best performance on Apple Silicon |

For 32B+, [mlx-lm](https://github.com/ml-explore/mlx-examples/tree/main/llms) is faster than HuggingFace transformers on Apple Silicon.

## Structure

| File | Purpose |
|---|---|
| `tools.py` | What the model can do |
| `harness.py` | The generation + tool-call loop |
| `cli.py` | Terminal UI |
| `main.py` | Entry point |

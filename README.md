# llm-harness

"We have claude code at home!"

Claude code at home: 

## Run

```bash
pip install -r requirements.txt
python3 main.py --model Qwen/Qwen2.5-1.5B-Instruct                 # fast, less capable
python3 main.py --model Qwen/Qwen2.5-7B-Instruct                   # good balance
python3 main.py --model mlx-community/Qwen2.5-14B-Instruct-4bit    # recommended sweet spot
```

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

## Structure

| File | Purpose |
|---|---|
| `tools.py` | What the model can do |
| `harness.py` | The generation + tool-call loop |
| `cli.py` | Terminal UI |
| `main.py` | Entry point |

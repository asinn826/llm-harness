# llm-harness

"We have claude code at home!"

Claude code at home: 

## Run

```bash
pip3.11 install -r requirements.txt
python3.11 main.py                                                  # interactive model picker
python3.11 main.py --model google/gemma-4-E4B-it --no-mlx          # skip picker, load directly
```

Start without `--model` to get an interactive picker with recommended models and any you've already downloaded. Switch models mid-session with `/model`.

| Model | Size | Engine | Heat | Tool calling | Speed |
|---|---|---|---|---|---|
| Gemma 4 E4B | 4B | `--no-mlx` | 🟢 Cool | Good (parser helps) | Slower |
| Qwen 3.5 4B 4-bit | 4B | mlx-lm | 🟡 Warm | Clean | Fast |
| Qwen 3.5 9B 4-bit | 9B | mlx-lm | 🔴 Hot | Best | Fast |

### Gemma 4 setup

Gemma 4 requires the HuggingFace backend (`--no-mlx`), Python 3.10+, and extra dependencies:

```bash
pip3.11 install torch accelerate torchvision pillow
pip3.11 install git+https://github.com/huggingface/transformers.git
python3.11 main.py --model google/gemma-4-E4B-it --no-mlx
```

## HuggingFace token

A token is optional for public models but required for gated ones (e.g. Llama). To use one, create a `.env` file in this directory:

```
HF_TOKEN=hf_...
```

Get a token at huggingface.co/settings/tokens. For gated models, you also need to accept the model's terms on its HuggingFace page.

## API keys and permissions

Most tools work out of the box with no setup. A few need API keys or macOS permissions:

| Tool | Requirement | How to set up |
|---|---|---|
| Web search | `TAVILY_API_KEY` | Free tier at [tavily.com](https://tavily.com). Add `TAVILY_API_KEY=tvly-...` to `.env` |
| Weather | None | Uses [Open-Meteo](https://open-meteo.com) (free, no key needed) |
| GIF search | None | Uses Tenor (key is built in) |
| iMessage read | Full Disk Access | System Settings → Privacy & Security → Full Disk Access → enable for Terminal |
| iMessage send | None | Uses AppleScript via Messages.app (works automatically) |
| Calendar read | Full Disk Access | Same as iMessage read — enable once, covers both |
| Calendar write | None | Uses AppleScript via Calendar.app |

### .env file

Create a `.env` file in the project directory for any keys you need:

```
HF_TOKEN=hf_...              # optional — only for gated models (Llama, etc.)
TAVILY_API_KEY=tvly-...      # optional — only for web_search tool
```

Everything else works without any configuration.

## Choosing a model

Tested on a MacBook Pro with 36GB unified memory. Picking a model is a tradeoff between how well it follows instructions, how fast it responds, and how hot your laptop gets.

### Recommended models

**🟢 Google Gemma 4 E4B — best for everyday use**
- 4 billion parameters, instruction tuned by Google
- Runs cool — your laptop stays comfortable even after many turns
- Good at reasoning and understanding what you want
- Occasionally formats tool calls oddly, but the harness handles it
- Slower responses (runs on the HF backend, not the fast mlx engine)
- `python3.11 main.py --model google/gemma-4-E4B-it --no-mlx`

**🟡 Qwen 3.5 4B — good middle ground**
- 4 billion parameters (quantized to 4-bit), instruction tuned by Alibaba
- Moderate heat — warmer than Gemma, cooler than the 9B
- Clean, reliable tool call formatting — fewer parser workarounds needed
- Good for simple tasks (1-2 tool calls), may stall on complex multi-step chains
- `python3.11 main.py --model mlx-community/Qwen3.5-4B-OptiQ-4bit`

**🔴 Qwen 3.5 9B — best quality, runs hot**
- 9 billion parameters (quantized to 4-bit), instruction tuned by Alibaba
- Best at following instructions and chaining multiple tools together
- Handles 3-4 step chains reliably (e.g. read calendar → compose summary → send message)
- Runs hot — your fan will kick in after sustained use
- `python3.11 main.py --model mlx-community/Qwen3.5-9B-MLX-4bit`

### Why some models run hotter

Models marked mlx-lm use Apple's MLX framework, which compiles optimized GPU kernels for Apple Silicon. This makes inference 3-5x faster but pushes the chip harder — more speed means more heat. Models with `--no-mlx` use a more general-purpose engine (HuggingFace transformers) that's slower but gives the GPU more breathing room.

### MLX vs `--no-mlx`: which should I use?

- **Use mlx-lm (the default)** for `mlx-community/` quantized models. Faster responses, but more heat.
- **Use `--no-mlx`** for models that mlx-lm doesn't support yet (like Gemma 4), or when you want cooler operation at the cost of slower responses.
- You **cannot** mix them: `mlx-community/` models only work with mlx-lm, and some models (Gemma 4) only work with `--no-mlx`.

> **Note**: Full-precision (fp16) models 9B+ don't fit in 36GB memory via `--no-mlx`. Use quantized `mlx-community` models for anything above 4B.

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

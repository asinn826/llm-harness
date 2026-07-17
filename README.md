# LLM Harness

A local desktop workbench for running freely available Hugging Face language models side by side.

LLM Harness makes comparison the primary workflow: choose two or three models, send the same prompt to each, and keep the results in durable project history. Model revisions are pinned so a comparison can be reopened with the same lineup later.

## What it does

- Finds and installs compatible Hugging Face models from inside the app.
- Checks access, runtime support, download size, disk space, memory fit, and local cache state before installation.
- Runs the same multi-turn conversation across a fixed model lineup.
- Preserves per-model responses, latency, token counts, and comparison history.

## Quick start

Requires Python 3.11+, Node.js 20+, and Rust for the native Tauri window.

```bash
python3.11 -m pip install -r requirements.txt
python3.11 -m pip install -r ui/backend/requirements.txt
cd ui/frontend && npm install && cd ../..

./ui/dev.sh
```

Use `./ui/dev.sh --browser` to run without the native window.

## Run a comparison

1. Select or create a project.
2. Browse Hugging Face and open a model to check compatibility.
3. Install and add two or three models to the lineup.
4. Send a shared prompt, compare the responses, and reopen the thread later to continue.

Comparisons execute one model at a time so they work within local accelerator limits while keeping the prompt and conversation history consistent.

## Model access

Public models require no account. For gated models, accept the model terms on Hugging Face and add an `HF_TOKEN` in Settings or a local `.env` file.

The development app supports compatible MLX and Transformers repositories. The packaged macOS app is currently MLX-only.

## Build and verify

```bash
./ui/build.sh                  # build the macOS app
./ui/build.sh --install        # optionally install it

python3.11 -m pytest -q
cd ui/frontend
npm run lint
npm run build
```

## More

- [UI architecture and API reference](ui/README.md)
- [Comparison-first product design](docs/superpowers/specs/2026-07-13-comparison-first-product-design.md)
- Legacy terminal interface: `python3.11 main.py`

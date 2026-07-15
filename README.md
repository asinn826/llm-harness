# LLM Harness

A local, comparison-first workbench for running freely downloadable Hugging Face language models side by side.

The desktop product is organized around projects and durable comparison threads. Add two or three compatible models, resolve each Hub revision to an immutable commit, install the runnable artifacts, send one shared prompt, and compare the persisted outcomes in aligned columns.

Current product principles:

- Comparison is the default workflow; general agent chat is legacy functionality.
- Hugging Face models are checked for access, runtime support, weight format, exact download size, local cache completeness, and memory fit before installation.
- Model revisions are pinned to commit SHAs through install, execution, and restored history.
- Comparisons run sequentially with a shared tool-free prompt so local accelerator limits do not compromise the experiment.
- Projects own durable multi-turn comparison history and fixed ordered lineups.

## Desktop App (UI)

A native desktop app with Hugging Face discovery, preflighted model installation, project-scoped history, and side-by-side comparison.

### Prerequisites

- **Python 3.11+**: `brew install python@3.11`
- **Node.js 20+**: `brew install node`
- **Rust** (for native window): `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`

### Setup

```bash
# Python dependencies
pip3.11 install -r requirements.txt
pip3.11 install -r ui/backend/requirements.txt

# Frontend dependencies (includes the Tauri CLI)
cd ui/frontend && npm install && cd ../..
```

If you don't have `python3.11` on your PATH, substitute `python3 -m pip` / `python3` — `ui/dev.sh` auto-detects `python3.11` and falls back to `python3`.

### Launch

```bash
./ui/dev.sh                # native desktop window (requires Rust)
./ui/dev.sh --browser      # fallback: opens in your browser
```

The app starts a FastAPI backend on port 8000 and a Tauri native window (or browser at localhost:5173). Start a comparison, add models from the local library or Hub, and run a shared prompt once at least two pinned models are ready.

### Comparison workflow

1. Select or create a project.
2. Start a comparison and choose **Browse Hugging Face models**.
3. Open a model to run preflight. You can choose `main`, a tag, or a commit; the harness records the resolved commit SHA.
4. Select **Install & add**. Installation downloads only the selected runnable weight family and does not allocate the model into memory.
5. Add a second or third model, return to the comparison, and send the shared prompt.
6. Reopen the comparison later to continue with the same fixed lineup and per-model conversation histories.

### Troubleshooting

- **`python3.11: command not found`** — You don't have 3.11 installed. Either `brew install python@3.11`, or run with plain `python3` (the launcher falls back automatically). Note that the `requirements.txt` comments still say `pip3.11`; substitute `python3 -m pip` if needed.
- **`ModuleNotFoundError: No module named 'fastapi'`** — Backend deps not installed under the Python version `dev.sh` picked. Run `python3 -m pip install -r ui/backend/requirements.txt` (or `pip3.11 ...` if using 3.11). Easy to miss if you only installed the root `requirements.txt`.
- **`npm error could not determine executable to run`** after "Launching desktop app..." — The Tauri CLI wasn't installed. Run `npm install` inside `ui/frontend/` again; `@tauri-apps/cli@^2` is a devDependency and should pull in on install.
- **`Rust not found`** from `check_rust` — Install Rust (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`) or skip the native window with `./ui/dev.sh --browser`.
- **"Ready. Native window should open shortly." prints, then nothing** — `dev.sh` backgrounds the backend and frontend and prints the banner unconditionally; if either child errors, scroll up — the real failure is above the banner.
- **Vite spams `http proxy error: /models ECONNREFUSED`** — Something is squatting on :8000 (usually a uvicorn reloader from a previous run that didn't shut down cleanly). `dev.sh` now auto-clears it on launch; to do it manually: `pkill -9 -f 'uvicorn ui.backend.server'` then re-run.

### Build standalone .app

One command bundles Python + FastAPI + MLX + the React frontend into a self-contained `LLM Harness.app` that needs no Python or Node install:

```bash
./ui/build.sh            # build into src-tauri/target/release/bundle/
./ui/build.sh --install  # also copy to /Applications
```

Final size: ~93 MB. MLX-only — the HF backend is stripped to keep the binary small. Pipeline:

1. `vite build` the frontend
2. PyInstaller bundles the Python backend as a Tauri sidecar binary
3. `tauri build` produces the `.app` (and a `.dmg` next to it)
4. `codesign --sign -` with ad-hoc signature (avoids Gatekeeper warning on your own machine)

First launch takes ~7s — PyInstaller unpacks once to a temp dir, subsequent launches are fast.

### macOS permissions

The app checks permissions on startup and shows a banner if anything is missing:

- **Full Disk Access** — needed to read iMessage/calendar databases. System Settings → Privacy & Security → Full Disk Access → add Terminal (or python3.11).
- **Automation** — needed to send messages and create calendar events. Granted automatically on first use via system dialog.

See [ui/README.md](ui/README.md) for architecture details, API reference, and project structure.

---

## Model compatibility

LLM Harness supports compatible text-generation repositories with causal-language-model weights. Preflight blocks unsupported tasks, GGUF-only repositories, custom remote code, missing local runtimes, and models that will not fit the machine. It does not claim universal Hugging Face compatibility.

The curated starters are deliberately small, public, Apache-2.0 models hosted on Hugging Face and converted for MLX:

| Model | Runtime | Weight download | Purpose |
|---|---|---:|---|
| `mlx-community/Qwen2.5-0.5B-Instruct-4bit` | MLX | ~265 MB | Fast default with strong instruction following |
| `mlx-community/SmolLM2-360M-Instruct` | MLX | ~690 MB | Lightweight second opinion |
| `mlx-community/SmolLM2-1.7B-Instruct` | MLX | ~3.2 GB | Higher-capacity comparison candidate |

Catalog entries are discovery shortcuts, not version locks. Every selected model is resolved and persisted at an immutable Hub commit before a comparison starts.

## Hugging Face access

Public models need no account. For a gated model, accept its terms on Hugging Face and add `HF_TOKEN` in Settings or in a local `.env` file:

```text
HF_TOKEN=hf_...
```

The product shows access failures during preflight, before installation begins.

## Legacy CLI

The original tool-enabled terminal agent remains available for compatibility:

```bash
python3.11 main.py
```

It is maintenance-mode functionality, not the product direction. General agent chat, iMessage/calendar actions, tool calling, and chain-of-thought controls are intentionally outside the comparison-first desktop workflow.

## Verification

```bash
python3.11 -m pytest -q
cd ui/frontend
npm run lint
npm run build
```

## Structure

| Path | Purpose |
|---|---|
| `ui/backend/model_preflight.py` | Hub revision, access, compatibility, artifact, cache, and fit checks |
| `ui/backend/model_installer.py` | Exact-revision, install-only Hub downloads |
| `ui/backend/session_store.py` | Projects, comparison lineups, turns, outcomes, and migrations |
| `ui/backend/server.py` | Local REST and WebSocket product API |
| `ui/frontend/src/views/CompareView.tsx` | Side-by-side comparison and restored history |
| `ui/frontend/src/views/ModelsView.tsx` | Installed library and Hugging Face discovery |
| `main.py`, `harness.py`, `cli.py`, `tools.py` | Legacy terminal agent stack |

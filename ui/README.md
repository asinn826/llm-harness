# LLM Harness UI

The comparison-first desktop surface for selecting freely available Hugging Face models, installing exact revisions locally, and running the same conversation side by side.

## Architecture

```text
Tauri desktop shell
└── React + TypeScript
    ├── Projects and comparison history
    ├── Hub discovery and preflight
    └── Aligned answers and per-model tool traces
        ↕ trusted local REST/WebSockets
FastAPI sidecar
├── Hub preflight and pinned installer
├── Sequential MLX / Transformers runtime manager
├── Shared tool registry and iterative execution loop
└── SQLite projects, lineups, turns, and outcomes
```

The comparison executor intentionally loads one model at a time. This fits local accelerator constraints while keeping the prompt, tool registry, execution rules, ordered lineup, and conversation history stable across models.

Each model runs the same bounded tool loop. Read-only tools execute automatically; mutating tools pause for approval in that model's pane. Calls, arguments, results, and final answers are persisted with the model outcome. Hidden chain-of-thought text remains suppressed.

## Development

Prerequisites: Python 3.11+, Node.js 20+, and Rust for the native Tauri window.

```bash
python3.11 -m pip install -r requirements.txt
python3.11 -m pip install -r ui/backend/requirements.txt
cd ui/frontend && npm install && cd ../..
./ui/dev.sh
```

Use `./ui/dev.sh --browser` when a native window is unnecessary. The development frontend runs at `http://localhost:5173`; the local API runs at `http://127.0.0.1:8000`.

## Verification

```bash
python3.11 -m pytest -q
cd ui/frontend
npm run lint
npm run build
```

## Production build

From the repository root:

```bash
./ui/build.sh
./ui/build.sh --install   # optional: copy the app to /Applications
```

The packaged macOS app uses MLX. The curated starter catalog therefore points to compatible MLX repositories hosted on Hugging Face. Standard Transformers repositories remain available in development environments that install PyTorch and Transformers.

## Product API

### Models

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/models` | Recommended, installed, and current model state |
| `GET` | `/models/search` | Opt-in Hugging Face discovery |
| `GET` | `/models/{owner}/{repo}/details` | Revision-aware descriptive metadata |
| `POST` | `/models/preflight` | Resolve a revision and check access, runtime, artifacts, memory, disk, and cache |
| `POST` | `/models/load` | Load a model revision into the singleton runtime |
| `POST` | `/models/unload` | Release the current runtime |
| `GET` | `/models/current` | Current model, backend, revision, and status |
| `WS` | `/ws/models/install` | Install the exact preflighted artifact plan without loading it |
| `WS` | `/ws/models/load` | Stream runtime load progress |

### Projects and comparisons

| Method | Path | Purpose |
|---|---|---|
| `GET/POST` | `/projects` | List or create projects |
| `GET` | `/projects/{id}` | Project counts and metadata |
| `GET/POST` | `/sessions` | Filter or create project-owned sessions |
| `GET/PATCH/DELETE` | `/sessions/{id}` | Read, rename, or delete a session |
| `GET` | `/sessions/{id}/messages` | Restore durable turns and outcomes |
| `POST` | `/sessions/{id}/fork` | Preserve history while branching an experiment |
| `WS` | `/ws/compare` | Run a shared prompt and tool loop sequentially across a pinned ordered lineup |

New comparison lineups must provide a full immutable Hugging Face commit SHA for every model. Existing unpinned legacy sessions remain readable through a constrained migration path.

Browser access is restricted to the configured Vite and Tauri origins; native and CLI clients without an `Origin` header remain supported.

## Project structure

```text
ui/backend/
├── model_preflight.py    # Hub access, revision, artifact, cache, memory, disk
├── model_installer.py    # Pinned install-only downloads
├── model_manager.py      # Sequential MLX / Transformers runtime
├── session_store.py      # Projects and durable comparison history
└── server.py             # Trusted local product API

ui/frontend/src/
├── views/CompareView.tsx
├── views/ModelsView.tsx
├── components/ModelDetailsDrawer.tsx
├── contexts/DownloadsContext.tsx
└── lib/                  # API, domain types, and transfer identity
```

## Local data

- Project and comparison history: `~/.llm_harness/sessions.db`
- Hugging Face model cache: `~/.cache/huggingface/hub/`
- Optional Hub credential: `HF_TOKEN` in Settings or the repository-local `.env`

# LLM Harness UI

Desktop application for the LLM Harness — browse, compare, and chat with local models.

## Architecture

```
┌─────────────────────────────────────┐
│         Tauri Shell (Rust)          │  ← Native window, system tray
│     ┌───────────────────────┐       │
│     │  React + TypeScript   │       │  ← Webview frontend
│     │  Tailwind + Lucide    │       │
│     └───────────┬───────────┘       │
│                 │ WebSocket + REST   │
│     ┌───────────┴───────────┐       │
│     │   FastAPI (Python)    │       │  ← Wraps harness.py + tools.py
│     │   SQLite sessions     │       │
│     └───────────┬───────────┘       │
│                 │                   │
│     ┌───────────┴───────────┐       │
│     │  MLX / HuggingFace    │       │  ← Model backends
│     └───────────────────────┘       │
└─────────────────────────────────────┘
```

**Key principle:** `harness.py` and `tools.py` are used as-is. The backend wraps them with a FastAPI layer. The CLI (`cli.py`) is not used — the React frontend replaces it.

## Quick Start (Development)

### Prerequisites

- **Python 3.9+** with the harness dependencies installed (`pip install -r requirements.txt`)
- **Node.js 20+** and npm
- **FastAPI dependencies:** `pip install fastapi 'uvicorn[standard]' websockets`

### Run

```bash
# Install frontend dependencies (first time only)
cd ui/frontend && npm install && cd ../..

# Start both backend and frontend
./ui/dev.sh
```

This starts:
- **Backend** on `http://localhost:8000` (FastAPI with hot reload)
- **Frontend** on `http://localhost:5173` (Vite dev server with HMR)

The frontend proxies API requests to the backend automatically.

### Run individually

```bash
./ui/dev.sh --backend   # Backend only (port 8000)
./ui/dev.sh --frontend  # Frontend only (port 5173)
```

### Run tests

```bash
# Backend tests (from project root)
python3 -m pytest tests/test_session_store.py tests/test_server.py -v

# All tests
python3 -m pytest tests/ -v
```

## Building for Production

### Browser-based (no Tauri)

```bash
# Build the frontend
cd ui/frontend && npm run build && cd ../..

# Serve with FastAPI (production)
uvicorn ui.backend.server:app --host 0.0.0.0 --port 8000
```

Then add static file serving to the FastAPI app to serve the built frontend from `ui/frontend/dist/`.

### Desktop App (Tauri)

Requires [Rust](https://rustup.rs/) installed.

```bash
# Install Rust (if needed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Build the desktop app
cd ui/frontend
npx tauri build
```

The `.dmg` (macOS) or installer will be in `ui/frontend/src-tauri/target/release/bundle/`.

**Note:** The Tauri shell spawns the FastAPI backend as a child process. You need Python 3.9+ available on the system PATH for the desktop app to work.

## Project Structure

```
ui/
├── backend/
│   ├── __init__.py
│   ├── server.py          # FastAPI app (REST + WebSocket endpoints)
│   ├── model_manager.py   # Model load/unload/switch singleton
│   ├── session_store.py   # SQLite session/message persistence
│   └── requirements.txt   # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── components/    # Reusable UI components
│   │   │   ├── Sidebar.tsx
│   │   │   ├── ModelSwitcher.tsx
│   │   │   ├── ChatMessage.tsx
│   │   │   └── ChatInput.tsx
│   │   ├── views/         # Full-page views
│   │   │   ├── ChatView.tsx
│   │   │   ├── CompareView.tsx
│   │   │   ├── ModelsView.tsx
│   │   │   └── SessionsView.tsx
│   │   ├── hooks/
│   │   │   └── useWebSocket.ts
│   │   ├── lib/
│   │   │   ├── api.ts     # REST client
│   │   │   └── types.ts   # Shared TypeScript types
│   │   ├── App.tsx         # Root component
│   │   ├── main.tsx        # Entry point
│   │   └── index.css       # Design tokens + global styles
│   ├── src-tauri/          # Tauri desktop shell (Rust)
│   ├── vite.config.ts
│   └── package.json
├── dev.sh                  # Development launcher
└── README.md               # This file
```

## API Reference

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/models` | List recommended + cached models |
| POST | `/models/load` | Load a model (`{model_id, backend?}`) |
| POST | `/models/unload` | Unload current model |
| GET | `/models/current` | Get currently loaded model info |
| GET | `/sessions` | List sessions (paginated) |
| POST | `/sessions` | Create session (`{title, is_compare?}`) |
| GET | `/sessions/:id` | Get session by ID |
| DELETE | `/sessions/:id` | Delete session |
| PATCH | `/sessions/:id` | Update session title |
| POST | `/sessions/:id/fork` | Fork session (`{from_position}`) |
| GET | `/sessions/:id/messages` | Get messages for session |
| GET | `/sessions/search?q=` | Full-text search sessions |
| GET | `/health` | Health check |

### WebSocket: Chat (`/ws/chat`)

**Client → Server:**
```json
{"type": "message", "content": "...", "session_id": "...", "model_id": "..."}
{"type": "tool_response", "approved": true}
```

**Server → Client:**
```json
{"type": "token", "data": "..."}
{"type": "tool_call", "tool": "...", "args": {...}, "needs_confirmation": true}
{"type": "tool_result", "result": "...", "tool": "...", "args": {...}}
{"type": "done", "response": "...", "tokens": 147, "time_ms": 2300, "session_id": "..."}
{"type": "session_created", "session_id": "...", "title": "..."}
{"type": "error", "message": "..."}
```

### WebSocket: Compare (`/ws/compare`)

**Client → Server:**
```json
{"type": "message", "content": "...", "models": ["model_a", "model_b"]}
```

**Server → Client** (per model, identified by `index`):
```json
{"type": "model_start", "model_id": "...", "index": 0}
{"type": "token", "data": "...", "model_id": "...", "index": 0}
{"type": "model_done", "model_id": "...", "index": 0, "response": "...", "tokens": 147, "time_ms": 2300}
{"type": "compare_done", "session_id": "..."}
```

## Data Storage

- **Sessions & messages:** `~/.llm_harness/sessions.db` (SQLite with WAL mode)
- **Model cache:** `~/.cache/huggingface/hub/` (standard HuggingFace cache)
- **User memory:** `~/.llm_harness/memory.json` (shared with CLI)

## Design System

The UI uses an intentional dark palette inspired by Linear, Raycast, and Warp:

- **Icons:** Lucide React (no emoji)
- **Colors:** CSS custom properties defined in `index.css`
- **Typography:** System sans-serif for UI, monospace for code
- **Motion:** 120-180ms transitions with ease-out easing
- **Model colors:** Persistent per-model color assignment from an 8-color palette

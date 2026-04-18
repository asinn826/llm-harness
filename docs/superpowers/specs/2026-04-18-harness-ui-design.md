# LLM Harness Desktop UI — Design Spec

## Context

The LLM Harness is a local LLM agent framework that supports multiple HuggingFace models with MLX and HuggingFace backends, tool use, and mid-session model switching. Today it's CLI-only — sessions vanish on exit, there's no model comparison, and no visual model management. The UI complements the CLI by adding the things terminals can't do well: persistent sessions, side-by-side model comparison, and a visual model library. The key differentiator vs. other chat UIs is that **local models and model switching are first-class**.

**Audience:** Developer hobbyists who run local models. Familiar with ML basics (quantization, context windows) but shouldn't need to read source code to operate the UI.

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Desktop shell | **Tauri** | Small binary (~5MB), low memory, native window + system tray. Rust sidecar launches the Python backend. |
| Frontend | **React + TypeScript + Tailwind CSS** | Rich component model for dual-stream comparison, shadcn/ui for polished developer-tool aesthetic. |
| Backend | **FastAPI + WebSockets** | Already Python — reuses `harness.py` and `tools.py` directly. WebSockets for streaming model output. |
| Storage | **SQLite** | Sessions, model metadata, user preferences. Lightweight, no external DB. File lives in app data directory. |
| Build | **Vite** (frontend), **Tauri CLI** (desktop) | Standard tooling, fast dev server with HMR. |

---

## Architecture

```
┌──────────────────────────────────┐
│           Tauri Shell            │
│  (native window, system tray,   │
│   spawns Python backend)         │
├──────────────────────────────────┤
│     React Frontend (webview)     │
│  Chat │ Compare │ Models │ History│
├──────────────────────────────────┤
│        WebSocket + REST          │
├──────────────────────────────────┤
│       FastAPI Backend            │
│  ┌─────────┐  ┌───────────────┐ │
│  │harness.py│  │  tools.py     │ │
│  │(agent    │  │  (18 tools,   │ │
│  │ loop)    │  │   unchanged)  │ │
│  └─────────┘  └───────────────┘ │
│  ┌─────────┐  ┌───────────────┐ │
│  │ Model    │  │  Session      │ │
│  │ Manager  │  │  Store        │ │
│  │(load/    │  │  (SQLite)     │ │
│  │ unload/  │  └───────────────┘ │
│  │ switch)  │                    │
│  └─────────┘                    │
├──────────────────────────────────┤
│  MLX / HuggingFace backends      │
│  (Apple Silicon GPU / CPU)       │
└──────────────────────────────────┘
```

**Key principle:** `harness.py` and `tools.py` stay unchanged. The backend wraps them with a FastAPI layer. `cli.py` is not used — the React frontend replaces it entirely.

---

## Views

### 1. Chat View (default)

The primary conversation interface with a persistent sidebar.

**Sidebar (left, collapsible to icon rail):**
- **Model switcher** (top) — shows active model name, backend, quantization, status indicator (ready/loading). Click to open model picker dropdown. One-click switch without leaving the chat.
- **Session list** — grouped by time (Today, Yesterday, This Week). Each entry shows title, model color dot(s), turn count, relative time. Active session highlighted with accent border.
- **Bottom icon row** — Lucide icons for navigation: `Package` (Models), `Columns2` (Compare), `Settings` (Settings).

**Chat area (right):**
- User messages in subtle card style, assistant messages with markdown rendering.
- **Tool calls** displayed as collapsible cards: tool name + args summary, expandable to full result. Read-only tools auto-execute; confirmation-required tools show approve/deny inline.
- **Streaming output** — tokens stream via WebSocket, rendered paragraph-by-paragraph.
- **Input bar** at bottom — text input with send button. Supports Enter to send, Shift+Enter for newlines.

**Model switcher behavior:**
- Dropdown shows: recommended models (with badges), locally cached models, search bar for HuggingFace Hub.
- Switching mid-session: unloads current model, loads new one, conversation preserved (same as CLI `/model` command).
- Loading state shown inline: progress bar in the model switcher area.

### 2. Compare View

Side-by-side model comparison — the killer local-model feature.

**Layout:**
- Icon-only sidebar (collapsed, Lucide icons: `MessageSquare`, `Columns2`, `Package`, `Clock`, `Settings`) to maximize horizontal space.
- **Model selector bar** across top: colored chips for selected models, "+ Add model" button, max 3 models. Note: "Models run sequentially (one GPU)" displayed as a subtle hint.
- **Split panels** — one per model, each with:
  - Color-coded header: model name, backend, quantization.
  - Per-model metrics: generation time, token count.
  - Independent message stream with tool call display.
- **Shared input bar** at bottom — one prompt goes to all models.

**Execution model:**
- Models run sequentially on a single GPU: load model A → generate → unload → load model B → generate.
- UI shows a progress indicator per panel (waiting / generating / done).
- Tool calls execute once; the result is shared across all models.

**Compare sessions** are saved to history with multi-model dot indicators.

### 3. Models View

Visual model library for browsing, downloading, and managing local models.

**Sections:**
- **Recommended** — curated models tested with the harness. Each card shows: name, backend badge (MLX/HF), quantization badge, heat indicator (Cool/Warm/Hot), size, one-line quality description, cache status, Load/Download button.
- **Locally Cached** — auto-discovered from HuggingFace cache directory. Shows model ID, backend, download date, size, Load button, overflow menu (delete from cache, view on HuggingFace, copy model ID).

**Search bar:** Searches both local cache and HuggingFace Hub. Typing a full model ID (e.g., `mistralai/Mistral-7B-Instruct-v0.3`) allows downloading any model.

**Footer:** Total models cached, total disk usage, cache directory path.

**Download flow:** Progress bar with speed and ETA, cancel button. Downloads go to standard HuggingFace cache.

### 4. Sessions View

Persistent, searchable conversation history.

**Master-detail layout:**
- **Session list** (left panel): search bar, sessions grouped by time, each showing title, model color dot(s), turn count, relative time.
- **Session detail** (right panel): title, stats bar (turns, tool calls, tokens, start time), scrollable message preview, action buttons.

**Actions:**
- **Resume** — reopen session, continue chatting with same model and full context.
- **Fork** — branch from any point in the session to try a different model or approach.
- **Export** — download as JSON (full data) or Markdown (readable).
- **Delete** — with confirmation.

**Storage:** SQLite in the app data directory. Full-text search index on message content.

---

## Design Principles

This UI must feel hand-crafted — not like an AI-generated template. Reference points: Linear (density + clarity), Raycast (speed + polish), Warp (terminal aesthetics). Avoid the generic "dark mode chat app" look.

- **No emoji icons anywhere.** Sidebar navigation, badges, status indicators — all use Lucide icons (ships with shadcn/ui). Emoji in user-generated content only.
- **Intentional color palette** — not just "dark mode defaults." A tight palette with 2-3 accent colors, careful use of opacity layers for depth. Avoid pure black backgrounds — use warm or cool dark tones with subtle gradients where appropriate.
- **Model color coding** — each model gets a persistent muted color (assigned on first use) that appears everywhere: sidebar dots, compare panel headers, session list indicators. Colors should be desaturated enough to feel professional, not candy-colored.
- **Typography hierarchy** — Inter or system font stack for UI, JetBrains Mono for code/tool calls. Deliberate size scale (not just sm/md/lg). Use font weight and opacity for hierarchy, not just size.
- **Density done right** — information-dense without feeling cramped. Tight vertical rhythm, consistent 4px grid. Inspired by Linear's ability to show a lot without overwhelming.
- **Subtle motion** — transitions on sidebar collapse, panel switches, model loading states. 150-200ms, ease-out. No bouncing or spring physics. Motion should feel mechanical and precise.
- **Collapsible sidebar** — full sidebar in Chat and Sessions views, icon rail in Compare and Models views. User can toggle manually. Icon rail uses 16-20px Lucide icons, not emoji.
- **Component library** — shadcn/ui as a foundation, restyled to match the palette. Don't use shadcn defaults — they're recognizable.

---

## Backend API Surface

### WebSocket

- `ws://localhost:{port}/ws/chat` — streaming chat. Client sends `{message, session_id, model_id}`, server streams `{type: "token" | "tool_call" | "tool_result" | "done", data}`.

### REST

- `GET /models` — list recommended + cached models with status.
- `POST /models/load` — load a model by ID. Returns loading progress via WebSocket.
- `POST /models/unload` — unload current model, free GPU memory.
- `POST /models/download` — download a model from HuggingFace Hub. Progress via WebSocket.
- `DELETE /models/{id}/cache` — delete model from local cache.
- `GET /sessions` — list sessions with metadata.
- `GET /sessions/{id}` — full session with messages.
- `POST /sessions` — create new session.
- `POST /sessions/{id}/fork` — fork session from a message index.
- `DELETE /sessions/{id}` — delete session.
- `GET /sessions/search?q=` — full-text search.
- `POST /compare` — start comparison session with multiple model IDs.

---

## Data Model (SQLite)

```sql
-- Sessions
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    is_compare BOOLEAN DEFAULT FALSE
);

-- Messages
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    role TEXT,          -- 'user' | 'assistant' | 'tool'
    content TEXT,
    model_id TEXT,      -- which model generated this (NULL for user messages)
    tool_name TEXT,     -- for tool messages
    tool_args TEXT,     -- JSON
    tokens_generated INTEGER,
    generation_time_ms INTEGER,
    created_at TIMESTAMP,
    position INTEGER    -- ordering within session
);

-- Model registry
CREATE TABLE models (
    id TEXT PRIMARY KEY,            -- HuggingFace model ID
    display_name TEXT,
    backend TEXT,                   -- 'mlx' | 'hf'
    quantization TEXT,
    size_bytes INTEGER,
    is_recommended BOOLEAN DEFAULT FALSE,
    heat_level TEXT,                -- 'cool' | 'warm' | 'hot'
    description TEXT,
    color TEXT,                     -- assigned UI color
    last_used_at TIMESTAMP
);

-- FTS index
CREATE VIRTUAL TABLE messages_fts USING fts5(content, content=messages, content_rowid=rowid);
```

---

## Verification Plan

1. **Backend smoke test:** Start FastAPI server, load a model via REST, send a message via WebSocket, verify streaming tokens arrive.
2. **Frontend rendering:** Load each view (Chat, Compare, Models, Sessions), verify layout matches mockups.
3. **Model switching:** Load model A, chat, switch to model B via sidebar picker, verify conversation preserved and new model responds.
4. **Compare flow:** Select 2 models, send a prompt, verify sequential execution with per-panel timing and shared tool results.
5. **Session persistence:** Chat, close app, reopen, verify session appears in history and can be resumed.
6. **Model library:** Verify recommended models display correctly, cached models auto-discovered, search returns HuggingFace results.
7. **Tauri build:** `tauri build` produces a working .dmg, Python backend starts correctly on launch.

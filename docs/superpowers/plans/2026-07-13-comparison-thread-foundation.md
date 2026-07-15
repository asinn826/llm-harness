# Comparison Thread Foundation Implementation Plan

**Goal:** Establish project-scoped, durable comparison threads that reopen in the side-by-side UI and preserve every model outcome.

**Architecture:** Extend the existing SQLite store in place, retaining `sessions` and `messages` as the compatibility layer while adding `projects` and ordered `comparison_models`. The existing sequential executor remains, but it loads prior per-model conversation context and persists load/generation failures. React routes sessions by type and makes Compare the default creation surface.

**Tech Stack:** Python, SQLite, FastAPI, React, TypeScript, WebSockets, pytest, Vite

---

### Task 1: Project and lineup persistence

**Files:**
- Modify: `ui/backend/session_store.py`
- Modify: `tests/test_session_store.py`

- [x] Add failing tests for default-project migration, project CRUD, project-filtered session listing, and ordered comparison models.
- [x] Add `projects`, `comparison_models`, and a nullable `sessions.project_id` migration.
- [x] Create a stable default project and backfill existing sessions.
- [x] Add project repository functions and comparison-lineup functions.
- [x] Preserve all existing session-store behavior and tests.

### Task 2: Project-aware REST API

**Files:**
- Modify: `ui/backend/server.py`
- Modify: `tests/test_server.py`

- [x] Add failing endpoint tests for project listing/creation, project-scoped session listing, project-aware session creation, and comparison-lineup retrieval.
- [x] Add `GET /projects`, `POST /projects`, and `GET /projects/{id}`.
- [x] Extend `GET /sessions` with optional `project_id` and `is_compare` filters.
- [x] Extend `POST /sessions` with optional `project_id` and ordered model specifications.
- [x] Return persisted lineup metadata with comparison sessions.

### Task 3: Durable comparison execution

**Files:**
- Modify: `ui/backend/server.py`
- Modify: `ui/backend/session_store.py`
- Modify: `tests/test_server.py`

- [x] Add a handler test proving a failed model load is persisted as a model-attributed assistant outcome.
- [x] Persist project and ordered lineup before execution begins.
- [x] Build each model's conversation from shared user turns and only that model's prior assistant responses.
- [x] Run comparisons with a shared tool-free system prompt and preserve each model's selected backend.
- [x] Persist load failures, generation failures, and empty outputs.
- [x] Include `session_id` in all terminal comparison messages.

### Task 4: Frontend domain and routing

**Files:**
- Modify: `ui/frontend/src/lib/types.ts`
- Modify: `ui/frontend/src/lib/api.ts`
- Modify: `ui/frontend/src/App.tsx`
- Modify: `ui/frontend/src/components/Sidebar.tsx`

- [x] Add `Project`, comparison-lineup, and project-aware session types and API methods.
- [x] Load the default project at app startup.
- [x] Make Compare the default view and new-session destination.
- [x] Pass the selected `Session` to routing so compare sessions open Compare and legacy sessions open Chat.
- [x] Filter the visible history by active project.

### Task 5: Restorable multi-turn Compare view

**Files:**
- Modify: `ui/frontend/src/views/CompareView.tsx`
- Modify: `ui/frontend/src/lib/types.ts`

- [x] Accept `sessionId`, `projectId`, and session-created callbacks.
- [x] Load persisted lineup and messages when an existing comparison is selected.
- [x] Render every shared user turn in each model column and only that model's response beneath it.
- [x] Preserve existing panel history when a new turn starts.
- [x] Use `model_done.response` when no streamed text exists so load errors render.
- [x] Send `session_id` and `project_id` on every run.

### Task 6: Verification and handoff

**Files:**
- Modify only if verification exposes defects.

- [x] Run focused session-store and server tests.
- [x] Run all backend tests that do not require a live MLX device.
- [x] Run the frontend production build.
- [x] Run lint and fix errors in files touched by this slice.
- [x] Inspect new comparison, persisted failure, history restoration, and legacy-chat routing in the local UI.
- [x] Confirm `git status` contains only intended changes.

### Verification record

- Focused backend suite: 75 passed.
- Full Python suite: 208 passed; 2 unrelated calendar validation tests remain environment-dependent because Full Disk Access is checked before malformed dates.
- Frontend: production build passed and targeted lint passed for every touched file.
- Live UI: project creation/switching, active-project persistence, draft-lineup preservation, saved multi-turn restoration, persisted failure rendering, legacy-chat routing, and Hugging Face library handoff were exercised with a clean browser console.

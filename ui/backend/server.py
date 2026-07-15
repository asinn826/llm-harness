"""FastAPI server: REST + WebSocket endpoints for the LLM Harness UI.

Wraps model_manager and session_store to provide the full API surface.
Run with: uvicorn ui.backend.server:app --reload
"""
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .model_manager import model_manager, ModelInfo
from .model_installer import install_model
from .model_preflight import ModelPreflightError, preflight_model
from .session_store import (
    create_project, get_project, list_projects,
    create_session, get_session, list_sessions, delete_session,
    update_session_title, add_message, get_messages, search_sessions,
    fork_session, get_conversation_list, get_comparison_models,
    set_comparison_models,
)

app = FastAPI(title="LLM Harness", version="0.1.0")

_TRUSTED_ORIGINS = frozenset({
    # Vite development server (hostname and loopback variants).
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    # Tauri's production webview origins across supported platforms.
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
})

_COMPARISON_SYSTEM_PROMPT = (
    "You are participating in a side-by-side model evaluation. "
    "Answer the user's request directly and independently. "
    "Do not call tools or refer to the evaluation harness."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_TRUSTED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _accept_trusted_websocket(ws: WebSocket) -> bool:
    """Accept a WebSocket only from this app's browser surfaces.

    Native clients and CLI tools commonly omit ``Origin`` and remain allowed.
    Browser clients always send it, so an unrecognized value is rejected before
    the endpoint reads a message or performs any work.
    """
    origin = ws.headers.get("origin")
    if origin is not None and origin not in _TRUSTED_ORIGINS:
        await ws.close(code=1008, reason="Origin not allowed")
        return False
    await ws.accept()
    return True


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from model output."""
    return re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL).strip()


async def _generate_session_title(session_id: str, user_message: str, ws: WebSocket):
    """Generate a short title for a session using the loaded model, in the background.

    Sends a title_updated WebSocket message when done. Falls back to
    truncating the user message if generation fails.
    """
    try:
        def _gen():
            return model_manager.generate_short(
                system_prompt="You generate short titles. Reply with ONLY a 4-6 word title. No explanation, no quotes, no punctuation.",
                user_message=f"Title for this request: {user_message}",
                max_tokens=20,
            )

        raw_title = await asyncio.to_thread(_gen)
        title = _strip_think_tags(raw_title)

        # Clean up: remove quotes, trailing punctuation, limit length
        title = title.strip('"\'').strip('.!').strip()
        if not title or len(title) < 2:
            title = user_message[:50]

        # Cap at reasonable length
        if len(title) > 60:
            title = title[:57] + "..."

        update_session_title(session_id, title)

        try:
            await ws.send_json({
                "type": "title_updated",
                "session_id": session_id,
                "title": title,
            })
        except Exception:
            pass  # WebSocket might be closed

    except Exception:
        # Fallback: use truncated first message
        fallback = user_message[:50] + ("..." if len(user_message) > 50 else "")
        update_session_title(session_id, fallback)
        try:
            await ws.send_json({
                "type": "title_updated",
                "session_id": session_id,
                "title": fallback,
            })
        except Exception:
            pass


# ── Models endpoints ───────────────────────────────────────────────────────

class LoadModelRequest(BaseModel):
    model_id: str
    backend: Optional[str] = None
    revision: Optional[str] = None


class PreflightModelRequest(BaseModel):
    model_id: str
    backend: Optional[str] = None
    revision: Optional[str] = None


class DownloadModelRequest(BaseModel):
    model_id: str


@app.get("/models")
async def list_models():
    return model_manager.list_models()


@app.post("/models/preflight")
async def model_preflight(req: PreflightModelRequest):
    try:
        return await asyncio.to_thread(
            preflight_model,
            req.model_id,
            backend=req.backend,
            revision=req.revision,
        )
    except ModelPreflightError as error:
        raise HTTPException(
            status_code=error.http_status,
            detail=error.to_dict(),
        ) from error


@app.post("/models/load")
async def load_model(req: LoadModelRequest):
    try:
        revision_kwargs = {"revision": req.revision} if req.revision else {}
        info = await asyncio.to_thread(
            model_manager.load_model, req.model_id, req.backend, **revision_kwargs
        )
        return {"status": "ok", "model": {
            "model_id": info.model_id,
            "backend": info.backend,
            "revision": info.revision,
        }}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/models/load")
async def ws_load_model(ws: WebSocket):
    """Load a model with progress streaming.

    Client sends: {"model_id": "...", "backend": "...", "revision": "..."}
    Server sends:
        {"type": "progress", "progress": 0.3, "message": "Loading tokenizer..."}
        {"type": "done", "model_id": "...", "backend": "..."}
        {"type": "error", "message": "..."}
    """
    if not await _accept_trusted_websocket(ws):
        return
    try:
        raw = await ws.receive_text()
        msg = json.loads(raw)
        model_id = msg["model_id"]
        backend = msg.get("backend")
        revision = msg.get("revision")

        loop = asyncio.get_event_loop()

        def progress_callback(p):
            asyncio.run_coroutine_threadsafe(
                ws.send_json({
                    "type": "progress",
                    "progress": p.progress,
                    "status": p.status,
                    "message": p.message,
                    "model_id": model_id,
                    "revision": revision,
                }),
                loop,
            )

        revision_kwargs = {"revision": revision} if revision else {}
        info = await asyncio.to_thread(
            model_manager.load_model,
            model_id,
            backend,
            progress_callback,
            **revision_kwargs,
        )
        await ws.send_json({
            "type": "done",
            "model_id": info.model_id,
            "backend": info.backend,
            "revision": info.revision,
        })
    except Exception as e:
        try:
            await ws.send_json({
                "type": "error",
                "message": str(e),
                "model_id": locals().get("model_id"),
                "revision": locals().get("revision"),
            })
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@app.websocket("/ws/models/install")
async def ws_install_model(ws: WebSocket):
    """Install a preflighted model revision without loading it into memory."""
    if not await _accept_trusted_websocket(ws):
        return
    model_id = None
    backend = None
    revision = None
    try:
        raw = await ws.receive_text()
        msg = json.loads(raw)
        model_id = msg["model_id"]
        backend = msg["backend"]
        revision = msg.get("revision")
        if not revision:
            raise RuntimeError("An immutable revision is required. Run preflight first.")

        loop = asyncio.get_event_loop()

        def progress_callback(progress):
            asyncio.run_coroutine_threadsafe(
                ws.send_json({
                    "type": "progress",
                    "progress": progress.progress,
                    "status": progress.status,
                    "message": progress.message,
                    "model_id": model_id,
                    "revision": revision,
                }),
                loop,
            )

        result = await asyncio.to_thread(
            install_model,
            model_id,
            backend,
            revision,
            progress_callback,
        )
        await ws.send_json({
            "type": "done",
            "model_id": model_id,
            "backend": backend,
            "revision": revision,
            "cache_status": result.get("cache_status"),
        })
    except Exception as error:
        try:
            await ws.send_json({
                "type": "error",
                "message": str(error),
                "model_id": model_id,
                "revision": revision,
            })
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@app.post("/models/unload")
async def unload_model():
    model_manager.unload_model()
    return {"status": "ok"}


@app.get("/models/current")
async def current_model():
    info = model_manager.current_model
    if info is None:
        return {"loaded": False}
    return {
        "loaded": True,
        "model_id": info.model_id,
        "backend": info.backend,
        "revision": info.revision,
        "status": info.status,
    }


# ── Hub search + details ──────────────────────────────────────────────────
#
# Uses huggingface_hub.HfApi (already installed transitively via mlx-lm /
# transformers; no new dep). Results are normalized and cached briefly
# to avoid hammering the Hub. On any Hub error we return 200 with an
# empty result set + error message — the Models page should never crash
# because the Hub is down.

from fastapi import Path as FPath

# owner/repo validation — prevents path traversal and garbage IDs before
# they reach the Hub API or the local filesystem.
_HF_ID_RE = r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]{0,95}$"


def _load_curated_allowlist() -> set[str]:
    """Model IDs from recommended_models.json — get 'verified' tool_use_tier."""
    import json
    path = Path(__file__).resolve().parent / "recommended_models.json"
    try:
        with open(path) as f:
            return {m["id"] for m in json.load(f)}
    except Exception:
        return set()


_CURATED_IDS = _load_curated_allowlist()


def _infer_backend_hint(tags: list[str]) -> str:
    """'mlx' if the repo is MLX-specific, else 'hf'."""
    return "mlx" if "mlx" in (tags or []) else "hf"


def _is_gguf_only(siblings) -> bool:
    """True if all weight files are GGUF (not runnable by our harness)."""
    if not siblings:
        return False
    filenames = [getattr(s, "rfilename", "") for s in siblings]
    has_native = any(
        f.endswith(".safetensors") or f.endswith(".npz") or f.endswith(".bin")
        for f in filenames
    )
    has_gguf = any(f.endswith(".gguf") for f in filenames)
    return has_gguf and not has_native


def _tool_use_tier_for(model_id: str) -> str:
    """Default tier for a Hub hit — 'verified' if curated, else 'unknown'.

    PR 2 will add 'likely' via chat-template inspection on first load.
    """
    return "verified" if model_id in _CURATED_IDS else "unknown"


# In-process TTL cache for search — keyed on query params, 60s expiry.
_search_cache: dict[tuple, tuple[float, dict]] = {}
_SEARCH_TTL = 60.0


@app.get("/models/search")
async def hub_search(
    q: str = Query("", max_length=200),
    sort: str = Query("downloads", pattern="^(downloads|likes|lastModified|trending)$"),
    backend: str = Query("all", pattern="^(all|mlx|hf)$"),
    limit: int = Query(30, ge=1, le=100),
):
    """Search huggingface.co for text-generation models.

    Returns `{results: [...], error?: str}`. Never raises — on Hub error
    we return an empty list with the error surfaced to the client.
    """
    # Cache lookup
    cache_key = (q, sort, backend, limit)
    now = time.time()
    cached = _search_cache.get(cache_key)
    if cached and (now - cached[0]) < _SEARCH_TTL:
        return cached[1]

    def _do_search():
        from huggingface_hub import HfApi
        api = HfApi()
        hub_sort = {
            "lastModified": "last_modified",
            "trending": "trending_score",
        }.get(sort, sort)
        hub_filter = None
        if backend == "mlx":
            hub_filter = "mlx"  # tag filter
        kwargs = dict(
            pipeline_tag="text-generation",
            limit=limit,
            sort=hub_sort,
        )
        if q:
            kwargs["search"] = q
        if hub_filter:
            kwargs["filter"] = hub_filter
        return list(api.list_models(**kwargs))

    try:
        hits = await asyncio.to_thread(_do_search)
    except Exception as e:
        return {"results": [], "error": f"Could not reach HuggingFace: {e}"}

    # Set of locally cached model IDs (for is_cached flag on each hit)
    from main import find_cached_models
    cached_set = set(find_cached_models())

    results = []
    for h in hits:
        tags = getattr(h, "tags", []) or []
        hint = _infer_backend_hint(tags)
        if backend == "hf" and hint == "mlx":
            continue  # user filtered to HF-only
        # Skip if filtered to HF but the repo is tagged mlx — already handled.
        model_id = h.id
        author = model_id.split("/")[0] if "/" in model_id else ""
        name = model_id.split("/")[-1]
        last_mod = getattr(h, "last_modified", None) or getattr(h, "lastModified", None)
        last_mod_str = last_mod.isoformat() if hasattr(last_mod, "isoformat") else (str(last_mod) if last_mod else None)

        results.append({
            "id": model_id,
            "author": author,
            "name": name,
            "downloads": getattr(h, "downloads", 0) or 0,
            "likes": getattr(h, "likes", 0) or 0,
            "last_modified": last_mod_str,
            "tags": tags,
            "pipeline_tag": getattr(h, "pipeline_tag", None),
            "gated": bool(getattr(h, "gated", False)),
            "backend_hint": hint,
            "tool_use_tier": _tool_use_tier_for(model_id),
            "is_cached": model_id in cached_set,
            # compatible is determined per-hit only if we have siblings (full=true).
            # list_models doesn't return siblings; assume compatible by default.
            "compatible": True,
        })

    payload = {"results": results}
    _search_cache[cache_key] = (now, payload)
    return payload


# Per-model details (owner + repo path params — validated against regex)
_details_cache: dict[tuple[str, Optional[str]], tuple[float, dict]] = {}
_DETAILS_TTL = 600.0


def _preferred_weight_size(siblings) -> int:
    """Size one runnable weight family without counting alternate formats."""
    for suffix in (".safetensors", ".npz", ".bin", ".gguf"):
        matching = [
            sibling for sibling in (siblings or [])
            if str(getattr(sibling, "rfilename", "") or "").lower().endswith(suffix)
        ]
        if matching:
            return sum(int(getattr(sibling, "size", 0) or 0) for sibling in matching)
    return 0


@app.get("/models/{owner}/{repo}/details")
async def model_details(
    owner: str = FPath(..., pattern=_HF_ID_RE),
    repo: str = FPath(..., pattern=_HF_ID_RE),
    revision: Optional[str] = Query(None, max_length=200),
):
    """Detailed info for a single Hub model: stats, sibling sizes, README."""
    model_id = f"{owner}/{repo}"

    now = time.time()
    cache_key = (model_id, revision)
    cached = _details_cache.get(cache_key)
    if cached and (now - cached[0]) < _DETAILS_TTL:
        return cached[1]

    def _fetch():
        from huggingface_hub import HfApi
        import os as _os
        token = _os.environ.get("HF_TOKEN") or None
        api = HfApi()
        info = api.model_info(
            model_id, revision=revision, files_metadata=True, token=token
        )

        size = _preferred_weight_size(getattr(info, "siblings", []) or [])

        # Fetch the model card without writing a metadata-only Hub cache entry.
        readme = ""
        try:
            import requests as _requests
            resolved = getattr(info, "sha", None) or revision or "main"
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            response = _requests.get(
                f"https://huggingface.co/{model_id}/raw/{resolved}/README.md",
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            readme = response.text
        except Exception:
            readme = ""
        if len(readme) > 8192:
            readme = readme[:8192] + "\n\n… (truncated)"

        last_mod = getattr(info, "last_modified", None) or getattr(info, "lastModified", None)
        last_mod_str = last_mod.isoformat() if hasattr(last_mod, "isoformat") else (str(last_mod) if last_mod else None)
        card = getattr(info, "card_data", None) or getattr(info, "cardData", None)
        license_ = None
        if card:
            # card can be a dict-like or object
            license_ = getattr(card, "license", None) if not isinstance(card, dict) else card.get("license")

        return {
            "id": model_id,
            "description": (getattr(card, "model_summary", None) if not isinstance(card, dict) else (card or {}).get("model_summary")) or "",
            "tags": list(getattr(info, "tags", []) or []),
            "license": license_,
            "downloads": getattr(info, "downloads", 0) or 0,
            "likes": getattr(info, "likes", 0) or 0,
            "gated": bool(getattr(info, "gated", False)),
            "pipeline_tag": getattr(info, "pipeline_tag", None),
            "model_size_bytes": size,
            "last_modified": last_mod_str,
            "resolved_revision": getattr(info, "sha", None),
            "readme_markdown": readme,
        }

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch model details: {e}")

    _details_cache[cache_key] = (now, data)
    return data


# ── Lifecycle: hardware, cache deletion, update check ──────────────────

@app.get("/system/hardware")
async def system_hardware():
    """Memory and platform info — used to compute hardware-fit chips."""
    import psutil, platform as _pf
    vm = psutil.virtual_memory()
    machine = _pf.machine()
    return {
        "total_memory_bytes": int(vm.total),
        "available_memory_bytes": int(vm.available),
        "platform": _pf.system(),
        "is_apple_silicon": (_pf.system() == "Darwin" and machine in ("arm64", "aarch64")),
    }


@app.delete("/models/cache/{owner}/{repo}")
async def delete_cached_model(
    owner: str = FPath(..., pattern=_HF_ID_RE),
    repo: str = FPath(..., pattern=_HF_ID_RE),
    confirm: bool = False,
):
    """Remove a model from the HuggingFace cache.

    Refuses if the model is currently loaded (409). Requires confirm=true
    as a safety check. Validates the target path stays within the HF hub
    cache directory to guard against path traversal.
    """
    if not confirm:
        raise HTTPException(status_code=400, detail="confirm=true required")

    model_id = f"{owner}/{repo}"

    info = model_manager.current_model
    if info is not None and info.model_id == model_id:
        raise HTTPException(status_code=409, detail={"error": "loaded", "unload_hint": True})

    import shutil
    hub_root = (Path.home() / ".cache" / "huggingface" / "hub").resolve()
    target = (hub_root / f"models--{owner}--{repo}").resolve()

    # Path traversal guard — target must be a direct child of hub_root
    try:
        target.relative_to(hub_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cache path")

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not cached: {model_id}")

    # Measure before delete
    from ui.backend.model_manager import _disk_size_for_cached
    freed = _disk_size_for_cached(model_id)

    await asyncio.to_thread(shutil.rmtree, target, ignore_errors=False)

    return {"status": "ok", "freed_bytes": freed}


# Per-id update cache (60 min)
_updates_cache: dict[str, tuple[float, dict]] = {}
_UPDATES_TTL = 3600.0


@app.get("/models/updates")
async def models_updates():
    """For each locally cached model, check if a newer commit exists on the Hub.

    Returns a list: [{id, has_update, local_sha, remote_sha}]. Hub errors
    per-model are swallowed (has_update=false, remote_sha=null).
    """
    from main import find_cached_models

    def _local_sha(model_id: str) -> Optional[str]:
        entry = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{model_id.replace('/', '--')}"
        ref = entry / "refs" / "main"
        try:
            return ref.read_text().strip()
        except Exception:
            return None

    async def _remote_sha(model_id: str) -> Optional[str]:
        now = time.time()
        cached = _updates_cache.get(model_id)
        if cached and (now - cached[0]) < _UPDATES_TTL:
            return cached[1].get("remote_sha")

        def _fetch():
            from huggingface_hub import HfApi
            info = HfApi().model_info(model_id)
            return getattr(info, "sha", None)

        try:
            sha = await asyncio.to_thread(_fetch)
            _updates_cache[model_id] = (now, {"remote_sha": sha})
            return sha
        except Exception:
            return None

    results = []
    for model_id in find_cached_models():
        local = _local_sha(model_id)
        remote = await _remote_sha(model_id)
        has_update = bool(local and remote and local != remote)
        results.append({
            "id": model_id,
            "has_update": has_update,
            "local_sha": local,
            "remote_sha": remote,
        })
    return results


# ── Projects and sessions endpoints ──────────────────────────────────────

class CreateProjectRequest(BaseModel):
    name: str


class ComparisonModelRequest(BaseModel):
    model_id: str
    backend: Optional[str] = None
    revision: Optional[str] = None


class CreateSessionRequest(BaseModel):
    title: str = "New session"
    is_compare: bool = False
    project_id: Optional[str] = None
    models: list[ComparisonModelRequest] = Field(default_factory=list)


class UpdateSessionRequest(BaseModel):
    title: str


class ForkSessionRequest(BaseModel):
    from_position: int


@app.get("/projects")
async def api_list_projects():
    return list_projects()


@app.post("/projects")
async def api_create_project(req: CreateProjectRequest):
    try:
        return create_project(req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/projects/{project_id}")
async def api_get_project(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.get("/sessions")
async def api_list_sessions(
    limit: int = 50,
    offset: int = 0,
    project_id: Optional[str] = None,
    is_compare: Optional[bool] = None,
):
    return list_sessions(
        limit=limit,
        offset=offset,
        project_id=project_id,
        is_compare=is_compare,
    )


@app.post("/sessions")
async def api_create_session(req: CreateSessionRequest):
    try:
        return create_session(
            title=req.title,
            is_compare=req.is_compare,
            project_id=req.project_id,
            models=[model.model_dump() for model in req.models],
        )
    except ValueError as e:
        status_code = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(e))


@app.get("/sessions/search")
async def api_search_sessions(q: str = Query(..., min_length=1)):
    return search_sessions(q)


@app.get("/sessions/{session_id}")
async def api_get_session(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.delete("/sessions/{session_id}")
async def api_delete_session(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "ok"}


@app.patch("/sessions/{session_id}")
async def api_update_session(session_id: str, req: UpdateSessionRequest):
    update_session_title(session_id, req.title)
    return {"status": "ok"}


@app.post("/sessions/{session_id}/fork")
async def api_fork_session(session_id: str, req: ForkSessionRequest):
    try:
        return fork_session(session_id, req.from_position)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/sessions/{session_id}/messages")
async def api_get_messages(session_id: str, limit: int = 1000, offset: int = 0):
    return get_messages(session_id, limit=limit, offset=offset)


# ── WebSocket: Chat ───────────────────────────────────────────────────────

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    """Streaming chat over WebSocket.

    Client sends:
        {"type": "message", "content": "...", "session_id": "...", "model_id": "..."}
        {"type": "tool_response", "approved": true/false/"feedback string"}

    Server sends:
        {"type": "token", "data": "..."}
        {"type": "tool_call", "tool": "...", "args": {...}, "needs_confirmation": true/false}
        {"type": "tool_result", "result": "...", "tool": "...", "args": {...}}
        {"type": "done", "response": "..."}
        {"type": "error", "message": "..."}
    """
    if not await _accept_trusted_websocket(ws):
        return

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            if msg["type"] == "message":
                await _handle_chat_message(ws, msg)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


async def _handle_chat_message(ws: WebSocket, msg: dict):
    """Process a chat message: generate, handle tool calls, stream tokens."""
    import threading
    from .model_manager import parse_tool_call
    from tools import TOOLS
    from harness import _trim_stale_tool_results

    session_id = msg.get("session_id")
    content = msg["content"]
    model_id = msg.get("model_id")

    # Ensure model is loaded
    if not model_manager.is_loaded:
        if model_id:
            try:
                await asyncio.to_thread(model_manager.load_model, model_id)
            except Exception as e:
                await ws.send_json({"type": "error", "message": f"Failed to load model: {e}"})
                return
        else:
            await ws.send_json({"type": "error", "message": "No model loaded"})
            return

    current = model_manager.current_model

    # Create or load session
    if not session_id:
        session = create_session(title=content[:50])
        session_id = session["id"]
        await ws.send_json({"type": "session_created", "session_id": session_id, "title": session["title"]})

    # Get conversation history
    conversation = get_conversation_list(session_id)
    is_first_turn = len(conversation) == 0

    # Store user message
    add_message(session_id, "user", content)
    conversation.append({"role": "user", "content": content})

    max_iterations = 10
    for iteration in range(max_iterations):
        _trim_stale_tool_results(conversation)

        # Warn the model when it's running low on tool-call iterations
        # so it gives a best-effort answer instead of burning the rest
        remaining = max_iterations - iteration
        if remaining == 3:
            conversation.append({
                "role": "user",
                "content": "[System: You have 3 tool calls remaining. Wrap up with whatever information you have. Do NOT keep searching — summarize what you found and answer the question.]",
            })
        elif remaining == 1:
            conversation.append({
                "role": "user",
                "content": "[System: This is your LAST tool call. You MUST respond with a final answer now, not another tool call.]",
            })

        chunks: list[str] = []
        error_box: list[Exception] = []
        start_time = time.time()
        loop = asyncio.get_event_loop()
        token_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _generate_thread():
            try:
                for token in model_manager.generate(conversation):
                    chunks.append(token)
                    asyncio.run_coroutine_threadsafe(token_queue.put(token), loop)
            except Exception as e:
                error_box.append(e)
            finally:
                # Sentinel: None signals "generation finished"
                asyncio.run_coroutine_threadsafe(token_queue.put(None), loop)

        gen_thread = threading.Thread(target=_generate_thread, daemon=True)
        gen_thread.start()

        # Buffer tokens until we know whether a <think> block is present.
        # Bug fix: don't decide "no think block" on the first token —
        # models may emit whitespace before <think>. Wait for 50 chars
        # or the first non-whitespace content before deciding.
        full_text = ""
        think_done = False
        sent_count = 0  # chars already sent to client
        while True:
            token = await token_queue.get()
            if token is None:
                break
            full_text += token

            if not think_done:
                if "<think>" in full_text:
                    # Think block found — wait for it to close
                    if "</think>" in full_text:
                        think_done = True
                        after = full_text[full_text.index("</think>") + len("</think>"):]
                        cleaned = after.lstrip()
                        sent_count = len(full_text) - len(after) + (len(after) - len(cleaned))
                        if cleaned:
                            try:
                                await ws.send_json({"type": "token", "data": cleaned})
                                sent_count = len(full_text)
                            except Exception:
                                break
                    # else: still inside think block, keep buffering
                elif len(full_text.strip()) > 30:
                    # Enough non-whitespace content without <think> — no think block
                    think_done = True
                    try:
                        await ws.send_json({"type": "token", "data": full_text})
                        sent_count = len(full_text)
                    except Exception:
                        break
                # else: not enough content yet to decide, keep buffering
            else:
                # Past the think block — stream normally
                try:
                    await ws.send_json({"type": "token", "data": token})
                    sent_count = len(full_text)
                except Exception:
                    break

        gen_thread.join(timeout=10)

        if error_box:
            await ws.send_json({"type": "error", "message": str(error_box[0])})
            return

        elapsed_ms = int((time.time() - start_time) * 1000)
        response = _strip_think_tags(''.join(chunks).strip())
        token_count = len(chunks)

        if not response:
            await ws.send_json({"type": "error", "message": "Model returned empty response"})
            return

        tool_call = parse_tool_call(response)

        if tool_call is None:
            conversation.append({"role": "assistant", "content": response})
            add_message(session_id, "assistant", response,
                       model_id=current.model_id,
                       tokens_generated=token_count,
                       generation_time_ms=elapsed_ms)
            await ws.send_json({
                "type": "done",
                "response": response,
                "tokens": token_count,
                "time_ms": elapsed_ms,
                "session_id": session_id,
            })

            # Generate a descriptive title after the first completed turn
            if is_first_turn:
                await _generate_session_title(session_id, content, ws)

            return

        # Tool call
        conversation.append({"role": "assistant", "content": response})
        add_message(session_id, "assistant", response,
                   model_id=current.model_id,
                   tokens_generated=token_count,
                   generation_time_ms=elapsed_ms)

        tool_name = tool_call.get("tool", "")
        args = {k: v for k, v in tool_call.get("args", {}).items() if v is not None}
        needs_confirmation = tool_name in TOOLS and getattr(TOOLS[tool_name], "needs_confirmation", True)

        await ws.send_json({
            "type": "tool_call",
            "tool": tool_name,
            "args": args,
            "needs_confirmation": needs_confirmation,
        })

        if needs_confirmation:
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=300)
                client_msg = json.loads(raw)
                approved = client_msg.get("approved", False) if client_msg["type"] == "tool_response" else False
            except (asyncio.TimeoutError, WebSocketDisconnect):
                approved = False
        else:
            approved = True

        if tool_name not in TOOLS:
            result = f"Error: unknown tool '{tool_name}'"
        elif isinstance(approved, str):
            result = f"User feedback (do NOT run the tool — adjust and try again): {approved}"
        elif not approved:
            result = "Tool call denied by user."
        else:
            try:
                result = await asyncio.to_thread(TOOLS[tool_name], **args)
                result = str(result)
            except Exception as e:
                result = f"Error running tool: {e}"

        await ws.send_json({
            "type": "tool_result",
            "result": result,
            "tool": tool_name,
            "args": args,
        })

        conversation.append({"role": "tool", "content": result})
        add_message(session_id, "tool", result, tool_name=tool_name, tool_args=args)

    # Max iterations
    fallback = "Reached maximum tool call iterations."
    conversation.append({"role": "assistant", "content": fallback})
    add_message(session_id, "assistant", fallback, model_id=current.model_id)
    await ws.send_json({"type": "done", "response": fallback, "session_id": session_id})


# ── WebSocket: Compare ────────────────────────────────────────────────────

@app.websocket("/ws/compare")
async def ws_compare(ws: WebSocket):
    """Side-by-side model comparison over WebSocket.

    Client sends:
        {"type": "message", "content": "...", "models": [{"model_id": "...", "backend": "hf"}], "session_id": "..."}

    Server sends (per model):
        {"type": "model_start", "model_id": "...", "index": 0}
        {"type": "token", "data": "...", "model_id": "...", "index": 0}
        {"type": "model_done", "model_id": "...", "index": 0, "response": "...", "tokens": N, "time_ms": N}
        {"type": "compare_done", "session_id": "..."}
    """
    if not await _accept_trusted_websocket(ws):
        return

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            if msg["type"] == "message":
                await _handle_compare_message(ws, msg)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


async def _handle_compare_message(ws: WebSocket, msg: dict):
    """Run one turn against a comparison's stable, ordered model lineup."""
    import threading

    content = msg["content"]
    raw_models = msg.get("models", [])
    model_specs = []
    for model in raw_models:
        if isinstance(model, str):
            model_specs.append({"model_id": model})
        elif isinstance(model, dict):
            model_specs.append({
                "model_id": model.get("model_id") or model.get("id"),
                "backend": model.get("backend"),
                "revision": model.get("revision"),
            })
        else:
            await ws.send_json({"type": "error", "message": "Invalid comparison model"})
            return
    session_id = msg.get("session_id")
    project_id = msg.get("project_id")

    # A comparison owns its lineup. The client supplies it once at creation;
    # reopening the thread always restores the persisted order.
    if not session_id:
        if not model_specs:
            await ws.send_json({"type": "error", "message": "No models specified"})
            return
        try:
            session = create_session(
                title=f"Compare: {content[:30]}",
                is_compare=True,
                project_id=project_id,
                models=model_specs,
            )
        except ValueError as e:
            await ws.send_json({"type": "error", "message": str(e)})
            return
        session_id = session["id"]
        await ws.send_json({
            "type": "session_created",
            "session_id": session_id,
            "project_id": session["project_id"],
            "title": session["title"],
        })
    else:
        session = get_session(session_id)
        if not session:
            await ws.send_json({"type": "error", "message": "Comparison not found"})
            return
        if not session["is_compare"]:
            await ws.send_json({"type": "error", "message": "Session is not a comparison"})
            return

        saved_lineup = get_comparison_models(session_id)
        if not saved_lineup and model_specs:
            try:
                set_comparison_models(session_id, model_specs)
            except ValueError as e:
                await ws.send_json({"type": "error", "message": str(e)})
                return

    lineup = get_comparison_models(session_id)
    if not lineup:
        await ws.send_json({"type": "error", "message": "No models specified"})
        return
    model_ids = [model["model_id"] for model in lineup]
    lineup_by_id = {model["model_id"]: model for model in lineup}

    add_message(session_id, "user", content)

    def _conversation_for_model(model_id: str) -> list[dict]:
        """Return shared user turns plus only this model's prior responses."""
        conversation = []
        failure_prefixes = (
            "Error loading model:",
            "Error generating response:",
            "Model returned empty response",
        )
        for message in get_messages(session_id):
            if message["role"] == "user":
                conversation.append({"role": "user", "content": message["content"]})
            elif (
                message["role"] == "assistant"
                and message["model_id"] == model_id
                and not message["tool_name"]
                and not message["content"].startswith(failure_prefixes)
            ):
                conversation.append({"role": "assistant", "content": message["content"]})
        return conversation

    for idx, model_id in enumerate(model_ids):
        await ws.send_json({
            "type": "model_start",
            "session_id": session_id,
            "model_id": model_id,
            "index": idx,
        })

        # Load model
        try:
            backend = lineup_by_id[model_id].get("backend")
            revision = lineup_by_id[model_id].get("revision")
            revision_kwargs = {"revision": revision} if revision else {}
            await asyncio.to_thread(
                model_manager.load_model, model_id, backend, **revision_kwargs
            )
        except Exception as e:
            response = f"Error loading model: {e}"
            add_message(
                session_id,
                "assistant",
                response,
                model_id=model_id,
                tokens_generated=0,
                generation_time_ms=0,
            )
            await ws.send_json({
                "type": "model_done",
                "session_id": session_id,
                "model_id": model_id,
                "index": idx,
                "response": response,
                "tokens": 0,
                "time_ms": 0,
            })
            continue

        conversation = _conversation_for_model(model_id)
        chunks = []
        error_box = []
        start_time = time.time()

        loop = asyncio.get_event_loop()
        token_queue = asyncio.Queue()

        def _generate_thread(mgr=model_manager, conv=conversation,
                             q=token_queue, c=chunks, errors=error_box, lp=loop):
            try:
                for token in mgr.generate(conv, system_prompt=_COMPARISON_SYSTEM_PROMPT):
                    c.append(token)
                    asyncio.run_coroutine_threadsafe(q.put(token), lp)
            except Exception as e:
                errors.append(e)
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), lp)

        async def _stream(q=token_queue, mid=model_id, i=idx):
            while True:
                token = await q.get()
                if token is None:
                    break
                await ws.send_json({
                    "type": "token",
                    "session_id": session_id,
                    "data": token,
                    "model_id": mid,
                    "index": i,
                })

        gen_thread = threading.Thread(target=_generate_thread, daemon=True)
        gen_thread.start()
        await _stream()
        gen_thread.join(timeout=10)

        elapsed_ms = int((time.time() - start_time) * 1000)
        response = _strip_think_tags(''.join(chunks).strip())
        token_count = len(chunks)

        if error_box:
            response = f"Error generating response: {error_box[0]}"
            token_count = 0
        elif not response:
            response = "Model returned empty response"
            token_count = 0

        add_message(
            session_id,
            "assistant",
            response,
            model_id=model_id,
            tokens_generated=token_count,
            generation_time_ms=elapsed_ms,
        )
        await ws.send_json({
            "type": "model_done",
            "session_id": session_id,
            "model_id": model_id,
            "index": idx,
            "response": response,
            "tokens": token_count,
            "time_ms": elapsed_ms,
        })

    await ws.send_json({"type": "compare_done", "session_id": session_id})


# ── Settings: API keys ────────────────────────────────────────────────────

_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"
_ALLOWED_KEYS = {"TAVILY_API_KEY", "HF_TOKEN"}


def _read_env() -> dict[str, str]:
    """Read key=value pairs from .env file."""
    result = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in _ALLOWED_KEYS:
                result[key] = value
    return result


def _write_env(updates: dict[str, str]):
    """Update specific keys in .env, preserving other content."""
    lines = []
    if _ENV_FILE.exists():
        lines = _ENV_FILE.read_text().splitlines()

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # Append any keys that weren't already in the file
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    _ENV_FILE.write_text("\n".join(new_lines) + "\n")

    # Also update os.environ so changes take effect immediately
    import os
    for key, value in updates.items():
        if value:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]


class SaveKeyRequest(BaseModel):
    key: str
    value: str


class RevealKeyRequest(BaseModel):
    key: str


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) > 10:
        return value[:4] + "•" * (len(value) - 8) + value[-4:]
    return "•" * len(value)


@app.get("/settings/keys")
async def get_api_keys():
    """Return current API key values (masked for display)."""
    raw = _read_env()
    result = {}
    for key in _ALLOWED_KEYS:
        val = raw.get(key, "")
        result[key] = _mask_secret(val)
    return result


@app.post("/settings/keys/reveal")
async def reveal_api_key(req: RevealKeyRequest, request: Request, response: Response):
    """Return one secret only after an explicit request from an app surface."""
    origin = request.headers.get("origin")
    if origin not in _TRUSTED_ORIGINS:
        raise HTTPException(status_code=403, detail="Origin not allowed")
    if req.key not in _ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown key: {req.key}")

    response.headers["Cache-Control"] = "no-store, private, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return {"key": req.key, "value": _read_env().get(req.key, "")}


@app.post("/settings/keys")
async def save_api_key(req: SaveKeyRequest):
    if req.key not in _ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown key: {req.key}")
    current = _read_env().get(req.key, "")
    if "•" in req.value:
        if req.value == _mask_secret(current):
            return {
                "status": "ok",
                "unchanged": True,
                "masked": _mask_secret(current),
            }
        raise HTTPException(
            status_code=400,
            detail="Masked key values cannot be saved. Enter a new token or leave the existing value unchanged.",
        )
    _write_env({req.key: req.value})
    return {"status": "ok", "masked": _mask_secret(req.value)}


# Small JSON-backed preference store for non-secret app settings.
_PREFS_FILE = Path.home() / ".llm_harness" / "preferences.json"


def _read_prefs() -> dict:
    try:
        import json as _json
        with open(_PREFS_FILE) as f:
            return _json.load(f)
    except Exception:
        return {}


def _write_prefs(updates: dict):
    import json as _json
    prefs = _read_prefs()
    prefs.update(updates)
    _PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_PREFS_FILE, "w") as f:
        _json.dump(prefs, f, indent=2)


class HubSearchRequest(BaseModel):
    enabled: bool


@app.get("/settings/prefs")
async def get_prefs():
    """User preferences (non-secret). Currently: hub_search_enabled."""
    prefs = _read_prefs()
    return {
        "hub_search_enabled": bool(prefs.get("hub_search_enabled", False)),
    }


@app.post("/settings/hub-search")
async def set_hub_search(req: HubSearchRequest):
    _write_prefs({"hub_search_enabled": bool(req.enabled)})
    return {"status": "ok", "hub_search_enabled": bool(req.enabled)}


# ── Permissions check ─────────────────────────────────────────────────────

import subprocess as _sp
import platform as _platform


def _check_automation(app_name: str) -> bool:
    """Test if this process has macOS Automation permission for an app.

    Runs a harmless osascript command. If macOS blocks it, the command
    fails with 'not allowed' in stderr. First run triggers the system
    permission dialog.
    """
    if _platform.system() != "Darwin":
        return True
    try:
        r = _sp.run(
            ["osascript", "-e", f'tell application "{app_name}" to get name'],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _check_full_disk_access() -> bool:
    """Check if this process can read Messages chat.db (requires Full Disk Access)."""
    import os
    db_path = os.path.expanduser("~/Library/Messages/chat.db")
    return os.access(db_path, os.R_OK)


@app.get("/permissions")
async def check_permissions():
    """Check macOS Automation + Full Disk Access permissions."""
    if _platform.system() != "Darwin":
        return {"messages": True, "contacts": True, "full_disk_access": True}

    messages = await asyncio.to_thread(_check_automation, "Messages")
    contacts = await asyncio.to_thread(_check_automation, "Contacts")
    fda = await asyncio.to_thread(_check_full_disk_access)
    return {"messages": messages, "contacts": contacts, "full_disk_access": fda}


@app.post("/permissions/open-settings")
async def open_automation_settings():
    """Open macOS System Settings to the Automation privacy pane."""
    if _platform.system() != "Darwin":
        return {"status": "not_macos"}
    _sp.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"])
    return {"status": "ok"}


@app.post("/permissions/open-full-disk")
async def open_full_disk_settings():
    """Open macOS System Settings to the Full Disk Access pane."""
    if _platform.system() != "Darwin":
        return {"status": "not_macos"}
    _sp.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])
    return {"status": "ok"}


# ── Health check ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}

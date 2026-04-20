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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .model_manager import model_manager, ModelInfo
from .session_store import (
    create_session, get_session, list_sessions, delete_session,
    update_session_title, add_message, get_messages, search_sessions,
    fork_session, get_conversation_list,
)

app = FastAPI(title="LLM Harness", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tauri webview and dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class DownloadModelRequest(BaseModel):
    model_id: str


@app.get("/models")
async def list_models():
    return model_manager.list_models()


@app.post("/models/load")
async def load_model(req: LoadModelRequest):
    try:
        info = await asyncio.to_thread(
            model_manager.load_model, req.model_id, req.backend
        )
        return {"status": "ok", "model": {"model_id": info.model_id, "backend": info.backend}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/models/load")
async def ws_load_model(ws: WebSocket):
    """Load a model with progress streaming.

    Client sends: {"model_id": "...", "backend": "..."}
    Server sends:
        {"type": "progress", "progress": 0.3, "message": "Loading tokenizer..."}
        {"type": "done", "model_id": "...", "backend": "..."}
        {"type": "error", "message": "..."}
    """
    await ws.accept()
    try:
        raw = await ws.receive_text()
        msg = json.loads(raw)
        model_id = msg["model_id"]
        backend = msg.get("backend")

        loop = asyncio.get_event_loop()

        def progress_callback(p):
            asyncio.run_coroutine_threadsafe(
                ws.send_json({
                    "type": "progress",
                    "progress": p.progress,
                    "status": p.status,
                    "message": p.message,
                }),
                loop,
            )

        info = await asyncio.to_thread(
            model_manager.load_model, model_id, backend, progress_callback
        )
        await ws.send_json({
            "type": "done",
            "model_id": info.model_id,
            "backend": info.backend,
        })
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
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
        "status": info.status,
    }


# ── Sessions endpoints ────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    title: str = "New session"
    is_compare: bool = False


class UpdateSessionRequest(BaseModel):
    title: str


class ForkSessionRequest(BaseModel):
    from_position: int


@app.get("/sessions")
async def api_list_sessions(limit: int = 50, offset: int = 0):
    return list_sessions(limit=limit, offset=offset)


@app.post("/sessions")
async def api_create_session(req: CreateSessionRequest):
    return create_session(title=req.title, is_compare=req.is_compare)


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
    await ws.accept()

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
        {"type": "message", "content": "...", "models": ["model_id_1", "model_id_2"], "session_id": "..."}

    Server sends (per model):
        {"type": "model_start", "model_id": "...", "index": 0}
        {"type": "token", "data": "...", "model_id": "...", "index": 0}
        {"type": "tool_call", "tool": "...", "args": {...}, "model_id": "...", "index": 0, "needs_confirmation": bool}
        {"type": "tool_result", "result": "...", "model_id": "...", "index": 0}
        {"type": "model_done", "model_id": "...", "index": 0, "response": "...", "tokens": N, "time_ms": N}
        {"type": "compare_done", "session_id": "..."}
    """
    await ws.accept()

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
    """Run the same prompt against multiple models sequentially."""
    content = msg["content"]
    model_ids = msg.get("models", [])
    session_id = msg.get("session_id")

    if not model_ids:
        await ws.send_json({"type": "error", "message": "No models specified"})
        return

    # Create compare session
    if not session_id:
        session = create_session(title=f"Compare: {content[:30]}", is_compare=True)
        session_id = session["id"]
        await ws.send_json({"type": "session_created", "session_id": session_id})

    add_message(session_id, "user", content)

    from tools import TOOLS
    from harness import _trim_stale_tool_results

    shared_tool_results = {}  # cache tool results to share across models

    for idx, model_id in enumerate(model_ids):
        await ws.send_json({
            "type": "model_start",
            "model_id": model_id,
            "index": idx,
        })

        # Load model
        try:
            backend = None
            await asyncio.to_thread(model_manager.load_model, model_id, backend)
        except Exception as e:
            await ws.send_json({
                "type": "model_done",
                "model_id": model_id,
                "index": idx,
                "response": f"Error loading model: {e}",
                "tokens": 0,
                "time_ms": 0,
            })
            continue

        # Build conversation for this model (shared user message, independent responses)
        conversation = [{"role": "user", "content": content}]

        for iteration in range(10):
            _trim_stale_tool_results(conversation)

            chunks = []
            start_time = time.time()

            loop = asyncio.get_event_loop()
            token_queue = asyncio.Queue()
            done_event = asyncio.Event()

            def _generate_thread(mgr=model_manager, conv=conversation,
                                 q=token_queue, c=chunks, evt=done_event, lp=loop):
                try:
                    for token in mgr.generate(conv):
                        c.append(token)
                        asyncio.run_coroutine_threadsafe(q.put(token), lp)
                finally:
                    evt.set()

            async def _stream(q=token_queue, evt=done_event, mid=model_id, i=idx):
                while not evt.is_set() or not q.empty():
                    try:
                        token = await asyncio.wait_for(q.get(), timeout=0.1)
                        await ws.send_json({"type": "token", "data": token, "model_id": mid, "index": i})
                    except asyncio.TimeoutError:
                        continue

            import threading
            gen_thread = threading.Thread(target=_generate_thread, daemon=True)
            gen_thread.start()
            await _stream()
            gen_thread.join(timeout=5)

            elapsed_ms = int((time.time() - start_time) * 1000)
            response = _strip_think_tags(''.join(chunks).strip())
            token_count = len(chunks)

            tool_call = parse_tool_call(response)

            if tool_call is None:
                conversation.append({"role": "assistant", "content": response})
                add_message(session_id, "assistant", response,
                           model_id=model_id,
                           tokens_generated=token_count,
                           generation_time_ms=elapsed_ms)
                await ws.send_json({
                    "type": "model_done",
                    "model_id": model_id,
                    "index": idx,
                    "response": response,
                    "tokens": token_count,
                    "time_ms": elapsed_ms,
                })
                break

            # Tool call — shared execution
            conversation.append({"role": "assistant", "content": response})
            tool_name = tool_call.get("tool", "")
            args = {k: v for k, v in tool_call.get("args", {}).items() if v is not None}
            needs_confirmation = tool_name in TOOLS and getattr(TOOLS[tool_name], "needs_confirmation", True)

            await ws.send_json({
                "type": "tool_call",
                "tool": tool_name,
                "args": args,
                "model_id": model_id,
                "index": idx,
                "needs_confirmation": needs_confirmation,
            })

            # Check shared cache
            cache_key = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
            if cache_key in shared_tool_results:
                result = shared_tool_results[cache_key]
            elif needs_confirmation:
                # Wait for approval
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=300)
                    client_msg = json.loads(raw)
                    approved = client_msg.get("approved", False) if client_msg["type"] == "tool_response" else False
                except (asyncio.TimeoutError, WebSocketDisconnect):
                    approved = False

                if tool_name not in TOOLS:
                    result = f"Error: unknown tool '{tool_name}'"
                elif isinstance(approved, str):
                    result = f"User feedback: {approved}"
                elif not approved:
                    result = "Tool call denied by user."
                else:
                    try:
                        result = await asyncio.to_thread(TOOLS[tool_name], **args)
                        result = str(result)
                    except Exception as e:
                        result = f"Error: {e}"
                shared_tool_results[cache_key] = result
            else:
                # Read-only — auto execute
                if tool_name not in TOOLS:
                    result = f"Error: unknown tool '{tool_name}'"
                else:
                    try:
                        result = await asyncio.to_thread(TOOLS[tool_name], **args)
                        result = str(result)
                    except Exception as e:
                        result = f"Error: {e}"
                shared_tool_results[cache_key] = result

            await ws.send_json({
                "type": "tool_result",
                "result": result,
                "tool": tool_name,
                "model_id": model_id,
                "index": idx,
            })
            conversation.append({"role": "tool", "content": result})
            chunks = []  # reset for next iteration

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


@app.get("/settings/keys")
async def get_api_keys():
    """Return current API key values (masked for display)."""
    raw = _read_env()
    result = {}
    for key in _ALLOWED_KEYS:
        val = raw.get(key, "")
        if val:
            # Show first 4 and last 4 chars, mask the rest
            if len(val) > 10:
                result[key] = val[:4] + "•" * (len(val) - 8) + val[-4:]
            else:
                result[key] = "•" * len(val)
        else:
            result[key] = ""
    return result


@app.post("/settings/keys")
async def save_api_key(req: SaveKeyRequest):
    if req.key not in _ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown key: {req.key}")
    _write_env({req.key: req.value})
    return {"status": "ok"}


# ── Health check ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}

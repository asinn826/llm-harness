"""FastAPI server: REST + WebSocket endpoints for the LLM Harness UI.

Wraps model_manager and session_store to provide the full API surface.
Run with: uvicorn ui.backend.server:app --reload
"""
import asyncio
import json
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

    # Store user message
    add_message(session_id, "user", content)
    conversation.append({"role": "user", "content": content})

    for iteration in range(10):
        _trim_stale_tool_results(conversation)

        # Generate with streaming — run generator in a thread,
        # ferry tokens to the async world via a queue.
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

        # Stream tokens to the client until we get the sentinel
        while True:
            token = await token_queue.get()
            if token is None:
                break
            try:
                await ws.send_json({"type": "token", "data": token})
            except Exception:
                break

        gen_thread.join(timeout=10)

        # Check for generation errors
        if error_box:
            await ws.send_json({"type": "error", "message": str(error_box[0])})
            return

        elapsed_ms = int((time.time() - start_time) * 1000)
        response = ''.join(chunks).strip()
        token_count = len(chunks)

        if not response:
            await ws.send_json({"type": "error", "message": "Model returned empty response"})
            return

        tool_call = parse_tool_call(response)

        if tool_call is None:
            # Plain text response — done
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
            response = ''.join(chunks).strip()
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


# ── Health check ──────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}

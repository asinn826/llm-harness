"""Model manager: load, unload, switch, and list models.

Wraps main.py's model loading logic into a singleton that the FastAPI
server can call. Thread-safe — only one model loaded at a time.
"""
import gc
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import torch
from dotenv import load_dotenv
load_dotenv()

# Add project root to path so we can import harness modules
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from harness import build_system_prompt, run_conversation_turn, parse_tool_call
from tools import TOOLS

# Import model loading functions and registry from main
from main import (
    RECOMMENDED_MODELS,
    detect_backend,
    find_cached_models,
    load_model_mlx as _load_model_mlx_raw,
    load_model_hf as _load_model_hf_raw,
    _mlx_stream_kwargs,
)


@dataclass
class ModelInfo:
    model_id: str
    backend: str  # "mlx" or "hf"
    status: str = "ready"  # "loading", "ready", "error"
    error: Optional[str] = None


@dataclass
class LoadProgress:
    model_id: str
    progress: float = 0.0  # 0.0 to 1.0
    status: str = "loading"
    message: str = ""


class ModelManager:
    """Manages a single loaded model at a time.

    Thread-safe: all operations acquire _lock. Only one model
    can be loaded — loading a new one unloads the current one first.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._model = None  # raw model object (mlx or HF)
        self._tokenizer = None  # tokenizer/processor
        self._info: Optional[ModelInfo] = None
        self._system_prompt = build_system_prompt(TOOLS)
        self._progress_callbacks: list = []

    @property
    def current_model(self) -> Optional[ModelInfo]:
        return self._info

    @property
    def is_loaded(self) -> bool:
        return self._info is not None and self._info.status == "ready"

    def list_models(self) -> dict:
        """List recommended and cached models with their status."""
        recommended_ids = {m["id"] for m in RECOMMENDED_MODELS}
        cached = find_cached_models()
        cached_set = set(cached)

        recommended = []
        for m in RECOMMENDED_MODELS:
            recommended.append({
                **m,
                "is_cached": m["id"] in cached_set,
                "is_loaded": self._info is not None and self._info.model_id == m["id"],
            })

        other_cached = []
        for model_id in cached:
            if model_id not in recommended_ids:
                backend = detect_backend(model_id)
                other_cached.append({
                    "id": model_id,
                    "name": model_id.split("/")[-1],
                    "backend": backend,
                    "is_cached": True,
                    "is_loaded": self._info is not None and self._info.model_id == model_id,
                })

        return {
            "recommended": recommended,
            "cached": other_cached,
            "current": self._info.model_id if self._info else None,
            "current_backend": self._info.backend if self._info else None,
        }

    def load_model(self, model_id: str, backend: Optional[str] = None,
                    progress_callback=None) -> ModelInfo:
        """Load a model, unloading the current one if needed.

        progress_callback: optional callable(LoadProgress) called during loading.
        """
        with self._lock:
            if backend is None:
                backend = detect_backend(model_id)

            # Already loaded?
            if self._info and self._info.model_id == model_id and self._info.status == "ready":
                return self._info

            # Unload current
            self._unload_internal()

            self._info = ModelInfo(model_id=model_id, backend=backend, status="loading")
            if progress_callback:
                progress_callback(LoadProgress(model_id=model_id, progress=0.0, status="loading",
                                               message=f"Loading {model_id}..."))

            try:
                if backend == "mlx":
                    tokenizer, model = self._load_mlx(model_id, progress_callback)
                    self._tokenizer = tokenizer
                    self._model = model
                else:
                    processor, model = self._load_hf(model_id, progress_callback)
                    self._tokenizer = processor
                    self._model = model

                self._info.status = "ready"
                if progress_callback:
                    progress_callback(LoadProgress(model_id=model_id, progress=1.0,
                                                   status="ready", message="Model loaded"))
                return self._info

            except Exception as e:
                self._info.status = "error"
                self._info.error = str(e)
                self._model = None
                self._tokenizer = None
                if progress_callback:
                    progress_callback(LoadProgress(model_id=model_id, progress=0.0,
                                                   status="error", message=str(e)))
                raise

    def _load_mlx(self, model_id: str, progress_callback=None):
        """Load via mlx-lm without CLI spinners."""
        from mlx_lm import load
        model, tokenizer = load(model_id)
        return tokenizer, model

    def _load_hf(self, model_id: str, progress_callback=None):
        """Load via HuggingFace transformers with progress tracking.

        Patches HF's tqdm to report download/load progress via callback.
        Mirrors main.py's load_model_hf but without CLI spinners.
        """
        import os
        import logging
        import importlib
        import warnings
        from transformers import AutoProcessor, AutoModelForCausalLM, logging as hf_logging
        from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError

        hf_logging.set_verbosity_error()
        logging.getLogger("transformers").setLevel(logging.ERROR)
        warnings.filterwarnings("ignore", message=".*unauthenticated.*", category=UserWarning)

        token = os.environ.get("HF_TOKEN") or None

        # Patch HF's tqdm to report progress via callback
        _hf_tqdm_module = importlib.import_module('huggingface_hub.utils.tqdm')
        _orig_hf_tqdm = _hf_tqdm_module.tqdm

        class _ProgressTqdm(_orig_hf_tqdm):
            def __init__(self, *args, **kwargs):
                kwargs['file'] = open(os.devnull, 'w')
                super().__init__(*args, **kwargs)

            def update(self, n=1):
                super().update(n)
                if self.total and progress_callback:
                    pct = self.n / self.total
                    desc = getattr(self, 'desc', None) or model_id
                    progress_callback(LoadProgress(
                        model_id=model_id, progress=pct,
                        status="loading", message=f"Downloading {desc}",
                    ))

        _hf_tqdm_module.tqdm = _ProgressTqdm

        # Also patch transformers' internal tqdm (for "Loading checkpoint shards")
        from transformers.utils import logging as tf_logging
        _orig_tf_tqdm = tf_logging.tqdm_lib.tqdm
        tf_logging.tqdm_lib.tqdm = _ProgressTqdm

        try:
            if progress_callback:
                progress_callback(LoadProgress(
                    model_id=model_id, progress=0.1,
                    status="loading", message="Loading tokenizer...",
                ))

            processor = AutoProcessor.from_pretrained(model_id, token=token)

            if progress_callback:
                progress_callback(LoadProgress(
                    model_id=model_id, progress=0.3,
                    status="loading", message="Loading model weights...",
                ))

            device = "mps" if torch.backends.mps.is_available() else "cpu"
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                torch_dtype=torch.float16,
                token=token,
            ).to(device)
            model.eval()
            return processor, model

        except GatedRepoError:
            raise RuntimeError(
                f"{model_id} is a gated model. Accept terms at huggingface.co/{model_id} "
                "and add HF_TOKEN to your .env file."
            )
        except RepositoryNotFoundError:
            raise RuntimeError(f"Model not found: {model_id}")
        finally:
            _hf_tqdm_module.tqdm = _orig_hf_tqdm
            tf_logging.tqdm_lib.tqdm = _orig_tf_tqdm

    def unload_model(self):
        """Unload the current model and free GPU memory."""
        with self._lock:
            self._unload_internal()

    def _unload_internal(self):
        """Unload without acquiring lock (caller must hold it)."""
        self._model = None
        self._tokenizer = None
        self._info = None
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

    def generate(self, conversation: list) -> str:
        """Run one generation step. Returns the raw model output string.

        Does NOT handle tool calls — that's the harness's job.
        Raises RuntimeError if no model is loaded.
        """
        if not self.is_loaded:
            raise RuntimeError("No model loaded")

        if self._info.backend == "mlx":
            return self._generate_mlx(conversation)
        else:
            return self._generate_hf(conversation)

    def _generate_mlx(self, conversation: list) -> str:
        """Generate with mlx-lm, collecting all tokens into a string."""
        from mlx_lm import stream_generate
        extra_kwargs = _mlx_stream_kwargs()

        messages = [{"role": "system", "content": self._system_prompt}] + conversation

        if hasattr(self._tokenizer, "apply_chat_template") and self._tokenizer.chat_template:
            prompt = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
        else:
            prompt = self._fallback_prompt(messages)

        chunks = []
        for response in stream_generate(self._model, self._tokenizer, prompt=prompt,
                                        max_tokens=2048, **extra_kwargs):
            token = response.text if hasattr(response, 'text') else response
            chunks.append(token)
            yield token

    def _generate_hf(self, conversation: list):
        """Generate with HuggingFace transformers, yielding tokens."""
        from transformers import TextIteratorStreamer
        import threading
        import queue

        messages = [{"role": "system", "content": self._system_prompt}] + conversation

        if hasattr(self._tokenizer, "apply_chat_template") and self._tokenizer.chat_template:
            try:
                prompt = self._tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True,
                    enable_thinking=False,
                )
            except TypeError:
                prompt = self._tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True,
                )
            inputs = self._tokenizer(text=prompt, return_tensors="pt").to(self._model.device)
        else:
            prompt = self._fallback_prompt(messages)
            inputs = self._tokenizer(text=prompt, return_tensors="pt").to(self._model.device)

        _MULTIMODAL_KEYS = {'mm_token_type_ids', 'pixel_values', 'image_sizes',
                            'pixel_attention_mask', 'image_grid_thw'}
        gen_inputs = {k: v for k, v in inputs.items() if k not in _MULTIMODAL_KEYS}

        streamer = TextIteratorStreamer(self._tokenizer, skip_prompt=True, skip_special_tokens=True)
        error_box = []

        def _generate():
            try:
                with torch.no_grad():
                    self._model.generate(**gen_inputs, max_new_tokens=2048, do_sample=False,
                                         repetition_penalty=1.2, streamer=streamer)
            except Exception as e:
                error_box.append(e)
                # Unblock the streamer by signaling end-of-stream
                streamer.text_queue.put(streamer.stop_signal)

        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()

        for token in streamer:
            yield token

        thread.join(timeout=5)

        # If generation failed, raise the error after the streamer unblocks
        if error_box:
            raise error_box[0]

    def _fallback_prompt(self, messages: list) -> str:
        lines = []
        for m in messages:
            if m["role"] == "tool":
                lines.append(f"USER: [Tool result] {m['content']}")
            else:
                lines.append(f"{m['role'].upper()}: {m['content']}")
        return "\n".join(lines) + "\nASSISTANT:"

    def run_turn(self, user_message: str, conversation: list,
                 on_token=None, on_tool_call=None, on_tool_result=None,
                 auto_approve_readonly=True) -> str:
        """Run a full conversation turn with streaming callbacks.

        on_token: callable(token: str) — called for each generated token
        on_tool_call: callable(tool_name: str, args: dict) -> bool|str
            Returns True to approve, False to deny, str for feedback.
            If None, auto-approves read-only tools and denies others.
        on_tool_result: callable(result: str) — called after tool execution

        Returns the final assistant response text.
        """
        if not self.is_loaded:
            raise RuntimeError("No model loaded")

        conversation.append({"role": "user", "content": user_message})

        from harness import _trim_stale_tool_results

        for _ in range(10):
            _trim_stale_tool_results(conversation)

            # Generate with streaming
            chunks = []
            for token in self.generate(conversation):
                chunks.append(token)
                if on_token:
                    on_token(token)

            response = ''.join(chunks).strip()
            tool_call = parse_tool_call(response)

            if tool_call is None:
                conversation.append({"role": "assistant", "content": response})
                return response

            # Tool call
            conversation.append({"role": "assistant", "content": response})
            tool_name = tool_call.get("tool")
            args = tool_call.get("args", {})
            args = {k: v for k, v in args.items() if v is not None}

            if tool_name not in TOOLS:
                result = f"Error: unknown tool '{tool_name}'"
            else:
                needs_confirmation = getattr(TOOLS[tool_name], "needs_confirmation", True)

                if needs_confirmation:
                    if on_tool_call:
                        approved = on_tool_call(tool_name, args)
                    else:
                        approved = False  # deny by default in web UI without explicit approval
                else:
                    approved = True  # read-only tools auto-approve
                    if on_tool_call:
                        on_tool_call(tool_name, args)  # notify but don't block

                if isinstance(approved, str):
                    result = f"User feedback (do NOT run the tool — adjust and try again): {approved}"
                elif not approved:
                    result = "Tool call denied by user."
                else:
                    try:
                        result = str(TOOLS[tool_name](**args))
                    except Exception as e:
                        result = f"Error running tool: {e}"

            if on_tool_result:
                on_tool_result(result, tool_name, args)

            conversation.append({"role": "tool", "content": result})

        fallback = "Reached maximum tool call iterations."
        conversation.append({"role": "assistant", "content": fallback})
        return fallback


# Singleton
model_manager = ModelManager()

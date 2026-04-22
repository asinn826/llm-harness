"""Entry point: load model and start CLI loop.

This file wires together three independent pieces:
  - tools.py    : what the model can do
  - harness.py  : the generation + tool-call loop
  - cli.py      : what the user sees

Keeping them separate means you can swap any one piece without touching the others.
For example: replace cli.py with a FastAPI server to get a web interface, or swap
the HuggingFace model for an API call — the harness and tools don't change at all.
"""
import argparse
import logging
from dotenv import load_dotenv
load_dotenv()

try:
    import torch  # type: ignore
    _HAS_TORCH = True
except ImportError:
    torch = None  # type: ignore
    _HAS_TORCH = False

from harness import build_system_prompt, run_conversation_turn
from tools import TOOLS
import sys

# rich/cli are needed only for the CLI entry — optional in the packaged
# standalone backend (which doesn't call main()).
try:
    from rich.markdown import Markdown
    from cli import (
        console, print_banner, print_assistant, print_tool_call, print_tool_result,
        confirm_tool, get_user_input, thinking_spinner, expand_last_tool_result,
    )
    _HAS_CLI = True
except ImportError:
    _HAS_CLI = False

import gc
from pathlib import Path

# Apple Silicon? MLX is the native path. If torch isn't bundled (standalone
# build), assume yes — the .app only ships on Apple Silicon anyway.
_USE_MLX = torch.backends.mps.is_available() if _HAS_TORCH else True

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ── Model registry ──────────────────────────────────────────────────────────

def _load_recommended_models() -> list[dict]:
    """Load the recommended model registry from JSON.

    The source of truth is ui/backend/recommended_models.json — enriched
    with parameters, quantization, context_window, description, license,
    tags, hf_url, tool_use_tier, etc. Used by both the CLI picker (which
    only reads name/id/size_label/heat/quality/backend) and the web UI's
    Models page (which reads the full schema).
    """
    registry_path = Path(__file__).resolve().parent / "ui" / "backend" / "recommended_models.json"
    try:
        import json
        with open(registry_path) as f:
            entries = json.load(f)
        # Back-compat: CLI picker expects `size` field; use size_label as fallback.
        for entry in entries:
            if "size" not in entry:
                entry["size"] = entry.get("size_label", "")
        return entries
    except (FileNotFoundError, json.JSONDecodeError):
        # Fallback: minimal hardcoded list so the CLI still works if the
        # JSON is missing or malformed.
        return [
            {"name": "Gemma 4 E4B", "id": "google/gemma-4-E4B-it",
             "size": "~8GB", "heat": "Cool", "quality": "Good quality", "backend": "hf"},
            {"name": "Qwen 3.5 4B 4-bit", "id": "mlx-community/Qwen3.5-4B-OptiQ-4bit",
             "size": "~3GB", "heat": "Warm", "quality": "Clean tools", "backend": "mlx"},
            {"name": "Qwen 3.5 9B 4-bit", "id": "mlx-community/Qwen3.5-9B-MLX-4bit",
             "size": "~5GB", "heat": "Hot", "quality": "Best quality", "backend": "mlx"},
        ]


RECOMMENDED_MODELS = _load_recommended_models()


def detect_backend(model_id: str) -> str:
    """Determine whether to use mlx-lm or HF for a given model."""
    if not _USE_MLX:
        return "hf"
    if model_id.startswith("mlx-community/"):
        return "mlx"
    _HF_ONLY = {"google/gemma-4-E4B-it"}
    if model_id in _HF_ONLY:
        return "hf"
    return "mlx"


def find_cached_models() -> list[str]:
    """Find HF model IDs already downloaded to ~/.cache/huggingface/hub/."""
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    models = []
    if cache_dir.exists():
        for d in cache_dir.iterdir():
            if d.name.startswith("models--"):
                model_id = d.name.replace("models--", "").replace("--", "/")
                models.append(model_id)
    return sorted(models)


def show_model_picker(current: str = None) -> tuple[str, str]:
    """Show an interactive model picker and return (model_id, backend)."""
    recommended_ids = {m["id"] for m in RECOMMENDED_MODELS}
    cached = [m for m in find_cached_models() if m not in recommended_ids]

    if current:
        console.print(f"\n[dim]Current model: {current}[/dim]\n")

    console.print("[bold]Choose a model:[/bold]\n")
    choices = []
    for i, m in enumerate(RECOMMENDED_MODELS, 1):
        marker = "  [dim]← current[/dim]" if m["id"] == current else ""
        backend_label = "HF backend" if m["backend"] == "hf" else "mlx"
        console.print(f"  [bold]{i}.[/bold] {m['name']:<25} {m['heat']:<8} {m['quality']:<18} ({backend_label}){marker}")
        choices.append(m)

    if cached:
        console.print(f"\n  [dim]Locally cached:[/dim]")
        for j, model_id in enumerate(cached, len(RECOMMENDED_MODELS) + 1):
            backend = detect_backend(model_id)
            backend_label = "HF backend" if backend == "hf" else "mlx"
            marker = "  [dim]← current[/dim]" if model_id == current else ""
            console.print(f"  [bold]{j}.[/bold] [dim]{model_id:<40}[/dim] ({backend_label}){marker}")
            choices.append({"id": model_id, "backend": backend})

    console.print(f"\n  [dim]Or enter a HuggingFace model ID[/dim]\n")

    while True:
        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(0)
        if not raw:
            continue
        # Number selection
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                c = choices[idx]
                return c["id"], c.get("backend", detect_backend(c["id"]))
        except ValueError:
            pass
        # Arbitrary model ID
        if "/" in raw:
            return raw, detect_backend(raw)
        console.print(f"  [dim]Invalid selection. Enter a number (1-{len(choices)}) or a model ID like 'org/model-name'.[/dim]")


def unload_model():
    """Free model memory before loading a new one."""
    gc.collect()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()


def load_and_build(model_id: str, backend: str, system_prompt: str):
    """Load a model and return (model_fn, model_id, backend)."""
    if backend == "mlx":
        tokenizer, model = load_model_mlx(model_id)
        model_fn = make_model_fn_mlx(tokenizer, model, system_prompt)
    else:
        processor, model = load_model_hf(model_id)
        model_fn = make_model_fn_hf(processor, model, system_prompt)
    return model_fn, model_id, backend


def _stream_response(token_iter) -> str:
    """Consume a token iterator, showing a spinner with paragraph-level progress.

    The spinner runs the entire time. As complete paragraphs (delimited by
    blank lines) accumulate, they're flushed above the spinner so the user
    sees meaningful progress without the jitter of token-by-token streaming.
    Tool calls (starting with {, ```, or call:) stay entirely behind the spinner.
    Ctrl+O opens the tool-output overlay during generation.
    Returns the full response string.
    """
    import os as _os
    import select as _select
    import termios as _termios
    import cli

    chunks: list[str] = []
    displayed_up_to = 0     # char index into full text already shown
    is_tool_call = None      # None = undecided, True/False once decided
    frame = 0

    # Set up stdin monitoring for Ctrl+O during generation
    is_tty = sys.stdin.isatty()
    fd = sys.stdin.fileno() if is_tty else -1
    old_term = _termios.tcgetattr(fd) if is_tty else None

    def _spin():
        nonlocal frame
        sys.stdout.write(f"\r\033[2m{_SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]} Thinking...\033[0m\033[K")
        sys.stdout.flush()
        frame += 1

    def _check_stdin():
        """Non-blocking check for Ctrl+O (expand) and Ctrl+C (cancel) on stdin."""
        nonlocal interrupted
        if not is_tty:
            return
        r, _, _ = _select.select([fd], [], [], 0)
        if r:
            ch = _os.read(fd, 1)
            if ch == b'\x03':  # Ctrl+C — cancel generation
                interrupted = True
            elif ch == b'\x0f':  # Ctrl+O — expand tool output
                sys.stdout.write('\r\033[K')
                sys.stdout.flush()
                _termios.tcsetattr(fd, _termios.TCSADRAIN, old_term)
                _termios.tcflush(fd, _termios.TCIFLUSH)
                cli.expand_last_tool_result()
                cli._setcbreak(fd)

    interrupted = False

    try:
        if is_tty:
            cli._setcbreak(fd)

        for response in token_iter:
            token = response.text if hasattr(response, 'text') else response
            chunks.append(token)
            _spin()
            _check_stdin()
            if interrupted:
                break

            full = ''.join(chunks)

            # Decide tool-call vs. plain text once we have enough chars.
            # Wait for at least 6 chars so "call:" prefix is fully visible
            # before deciding — if we check too early, "call" without the
            # colon gets classified as plain text.
            if is_tool_call is None:
                stripped = full.lstrip()
                if len(stripped) < 6:
                    continue
                is_tool_call = (
                    stripped[0] in ('{', '`')
                    or stripped.startswith('call:')
                    or stripped.startswith('call ')
                )

            if is_tool_call:
                continue

            # Check for paragraph breaks (\n\n) in the un-displayed portion.
            # When found, flush everything up to the last break above the spinner.
            undisplayed = full[displayed_up_to:]
            last_break = undisplayed.rfind('\n\n')
            if last_break > 0:
                to_show = undisplayed[:last_break].rstrip()
                if to_show:
                    sys.stdout.write('\r\033[K')  # clear spinner line
                    if displayed_up_to == 0:
                        console.print()
                    console.print(Markdown(to_show))
                    console.print()
                displayed_up_to += last_break + 2

    finally:
        if is_tty:
            _termios.tcsetattr(fd, _termios.TCSADRAIN, old_term)

    # Generation complete (or interrupted) — clear spinner
    sys.stdout.write('\r\033[K')
    sys.stdout.flush()

    if interrupted:
        console.print("[dim]Cancelled.[/dim]")
        raise KeyboardInterrupt()

    full = ''.join(chunks).strip()

    if is_tool_call or is_tool_call is None:
        return full

    # Flush any remaining text after the last paragraph break
    remaining = full[displayed_up_to:].strip()
    if displayed_up_to == 0:
        # Short response with no paragraph breaks — let print_assistant handle it
        return full

    if remaining:
        console.print(Markdown(remaining))
        console.print()
    cli._last_was_streamed = True
    return full


def load_model_mlx(model_id: str):
    """Load a model using mlx-lm (Apple Silicon only).

    mlx-lm uses the MLX framework which compiles Metal kernels for the
    Apple Neural Engine / GPU — much faster than transformers on MPS.
    Shows a spinner until huggingface_hub's tqdm progress kicks in (for
    downloads), then hands off to a compact progress bar.
    """
    import importlib
    import threading

    _spinner_stop = [False]

    def _pre_load_spinner():
        import time
        frame = 0
        while not _spinner_stop[0]:
            sys.stdout.write(f"\r\033[2m{_SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]} Loading {model_id}...\033[0m")
            sys.stdout.flush()
            frame += 1
            time.sleep(0.08)

    # Patch huggingface_hub's tqdm to show a compact progress bar instead
    _hf_tqdm_module = importlib.import_module('huggingface_hub.utils.tqdm')
    _orig_hf_tqdm = _hf_tqdm_module.tqdm

    class _CompactTqdm(_orig_hf_tqdm):
        """Single-line progress bar for weight downloading."""
        def __init__(self, *args, **kwargs):
            _spinner_stop[0] = True  # kill the spinner
            kwargs['disable'] = True
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            super().update(n)
            if self.total:
                pct = self.n / self.total
                filled = int(20 * pct)
                bar = '█' * filled + '░' * (20 - filled)
                sys.stdout.write(f"\r\033[2mLoading {model_id}  {bar} {pct:>4.0%}\033[0m")
                sys.stdout.flush()

    _hf_tqdm_module.tqdm = _CompactTqdm
    spinner_thread = threading.Thread(target=_pre_load_spinner, daemon=True)
    spinner_thread.start()

    try:
        from mlx_lm import load
        model, tokenizer = load(model_id)
        sys.stdout.write('\r\033[K')
        sys.stdout.flush()
    finally:
        _spinner_stop[0] = True
        _hf_tqdm_module.tqdm = _orig_hf_tqdm

    console.print(f"[dim]✓ Model loaded ({model_id}) via mlx-lm[/dim]\n")
    return tokenizer, model


def _mlx_stream_kwargs():
    """Build kwargs for mlx-lm stream_generate, adapting to API version.

    Older mlx-lm accepts repetition_penalty as a direct kwarg.
    Newer mlx-lm (0.31+) requires it via logits_processors.
    """
    try:
        from mlx_lm.sample_utils import make_logits_processors
        lp = make_logits_processors(repetition_penalty=1.2, repetition_context_size=100)
        return {"logits_processors": lp}
    except ImportError:
        return {"repetition_penalty": 1.2, "repetition_context_size": 100}


def make_model_fn_mlx(tokenizer, model, system_prompt: str):
    """Return a model_fn backed by mlx-lm streaming generate."""
    from mlx_lm import stream_generate
    extra_kwargs = _mlx_stream_kwargs()

    def model_fn(conversation: list) -> str:
        messages = [{"role": "system", "content": system_prompt}] + conversation

        if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template:
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            lines = []
            for m in messages:
                if m["role"] == "tool":
                    lines.append(f"USER: [Tool result] {m['content']}")
                else:
                    lines.append(f"{m['role'].upper()}: {m['content']}")
            prompt = "\n".join(lines) + "\nASSISTANT:"

        return _stream_response(
            stream_generate(model, tokenizer, prompt=prompt, max_tokens=2048,
                            **extra_kwargs),
        )

    return model_fn


def load_model_hf(model_id: str):
    """Load a HuggingFace model and processor onto the best available device.

    Uses AutoProcessor (superset of AutoTokenizer — handles multimodal models
    like Gemma 4 that have vision/audio processors alongside the tokenizer).
    device_map="auto" with accelerate handles device placement, which avoids
    the MPS caching_allocator_warmup bug triggered by explicit device_map="mps".
    """
    import os
    from transformers import AutoProcessor, AutoModelForCausalLM, logging as hf_logging
    from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError
    import warnings

    # Suppress noisy but harmless transformers warnings about generation flags
    hf_logging.set_verbosity_error()
    logging.getLogger("transformers").setLevel(logging.ERROR)

    # HF_TOKEN is optional — public models work without it. Gated models (e.g.
    # Llama) require accepting terms on huggingface.co and setting HF_TOKEN in .env.
    token = os.environ.get("HF_TOKEN") or None

    # Suppress the unauthenticated-request warning when no token is configured —
    # it's just noise for public models.
    warnings.filterwarnings("ignore", message=".*unauthenticated.*", category=UserWarning)

    try:
        # Patch HF's tqdm wrapper to show a compact single-line progress bar.
        # HF imports tqdm from huggingface_hub.utils.tqdm, not from tqdm directly,
        # so we must patch that specific class.
        import importlib
        _hf_tqdm_module = importlib.import_module('huggingface_hub.utils.tqdm')
        _orig_hf_tqdm = _hf_tqdm_module.tqdm

        _spinner_stop = [False]

        def _pre_load_spinner():
            """Show a spinner until the first tqdm progress bar appears."""
            import time
            frame = 0
            while not _spinner_stop[0]:
                sys.stdout.write(f"\r\033[2m{_SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]} Loading {model_id}...\033[0m")
                sys.stdout.flush()
                frame += 1
                time.sleep(0.08)

        import threading
        spinner_thread = threading.Thread(target=_pre_load_spinner, daemon=True)
        spinner_thread.start()

        _progress_lock = threading.Lock()

        def _kill_spinner():
            """Stop the spinner and clear its line (safe to call multiple times)."""
            if not _spinner_stop[0]:
                _spinner_stop[0] = True
                import time
                time.sleep(0.1)  # let spinner thread finish its cycle
                sys.stdout.write('\r\033[K')
                sys.stdout.flush()

        class _CompactTqdm(_orig_hf_tqdm):
            """Single-line progress bar that replaces all HF/transformers tqdm bars."""
            def __init__(self, *args, **kwargs):
                _kill_spinner()
                # Keep tqdm enabled so __iter__ calls update(), but suppress
                # its default output by routing it to /dev/null.
                kwargs['file'] = open(os.devnull, 'w')
                super().__init__(*args, **kwargs)

            def update(self, n=1):
                super().update(n)
                if self.total:
                    with _progress_lock:
                        pct = self.n / self.total
                        filled = int(20 * pct)
                        bar = '█' * filled + '░' * (20 - filled)
                        desc = getattr(self, 'desc', None) or model_id
                        sys.stdout.write(f"\r\033[2m{desc}  {bar} {pct:>4.0%}\033[0m")
                        sys.stdout.flush()

        _hf_tqdm_module.tqdm = _CompactTqdm

        # Transformers has its own tqdm wrapper (for "Loading checkpoint shards")
        # that goes through tqdm.auto, not huggingface_hub. Patch it too.
        from transformers.utils import logging as tf_logging
        _orig_tqdm_active = tf_logging._tqdm_active
        _orig_tqdm_lib_tqdm = tf_logging.tqdm_lib.tqdm
        tf_logging.tqdm_lib.tqdm = _CompactTqdm

        try:
            processor = AutoProcessor.from_pretrained(model_id, token=token)
            # Load to MPS directly. device_map="auto" with accelerate can
            # offload layers to disk on memory-constrained Macs, causing
            # 10x slowdown as weights shuttle between disk and GPU.
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                torch_dtype=torch.float16,
                token=token,
            ).to(device)
            model.eval()
            sys.stdout.write('\r\033[K')
            sys.stdout.flush()
        finally:
            _spinner_stop[0] = True
            _hf_tqdm_module.tqdm = _orig_hf_tqdm
            tf_logging.tqdm_lib.tqdm = _orig_tqdm_lib_tqdm
    except GatedRepoError:
        console.print(
            f"[red]✗ {model_id} is a gated model.[/red]\n"
            "  Accept the terms at huggingface.co/[bold]{model_id}[/bold] then add your token to .env:\n"
            "  [dim]HF_TOKEN=hf_...[/dim]"
        )
        raise SystemExit(1)
    except RepositoryNotFoundError:
        console.print(f"[red]✗ Model not found: {model_id}[/red]")
        raise SystemExit(1)

    console.print(f"[dim]✓ Model loaded ({model_id}) on {model.device}[/dim]\n")
    return processor, model


def make_model_fn_hf(processor, model, system_prompt: str):
    """Return a callable(conversation) -> str that runs one generation step."""
    from transformers import TextIteratorStreamer
    import threading

    def model_fn(conversation: list) -> str:
        messages = [{"role": "system", "content": system_prompt}] + conversation

        # apply_chat_template with tokenize=False returns a formatted string;
        # processor() then converts it to tensors. This two-step approach works
        # for both text-only models (Qwen, Llama) and multimodal ones (Gemma 4).
        if hasattr(processor, "apply_chat_template") and processor.chat_template:
            # enable_thinking=False: skip chain-of-thought for tool-use scenarios.
            # The kwarg is ignored by models that don't support it.
            try:
                prompt = processor.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                    enable_thinking=False,
                )
            except TypeError:
                prompt = processor.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            inputs = processor(text=prompt, return_tensors="pt").to(model.device)
        else:
            lines = []
            for m in messages:
                if m["role"] == "tool":
                    lines.append(f"USER: [Tool result] {m['content']}")
                else:
                    lines.append(f"{m['role'].upper()}: {m['content']}")
            text = "\n".join(lines) + "\nASSISTANT:"
            inputs = processor(text=text, return_tensors="pt").to(model.device)

        # Filter out multimodal-only keys that AutoProcessor adds for
        # vision/audio but text-only generation rejects. Blocklist approach
        # so we don't accidentally drop keys a new model needs.
        _MULTIMODAL_KEYS = {'mm_token_type_ids', 'pixel_values', 'image_sizes',
                            'pixel_attention_mask', 'image_grid_thw'}
        gen_inputs = {k: v for k, v in inputs.items() if k not in _MULTIMODAL_KEYS}

        streamer = TextIteratorStreamer(processor, skip_prompt=True, skip_special_tokens=True)

        def _generate():
            with torch.no_grad():
                model.generate(**gen_inputs, max_new_tokens=2048, do_sample=False,
                               repetition_penalty=1.2, streamer=streamer)

        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()
        response = _stream_response(streamer)
        thread.join(timeout=1)  # don't block forever if cancelled
        return response

    return model_fn


def main():
    parser = argparse.ArgumentParser(description="A minimal LLM harness with tool use")
    parser.add_argument(
        "--model",
        default=None,
        help="HuggingFace model ID. If omitted, shows an interactive picker.",
    )
    parser.add_argument(
        "--no-mlx",
        action="store_true",
        help="Force HuggingFace transformers backend even on Apple Silicon",
    )
    args = parser.parse_args()

    system_prompt = build_system_prompt(TOOLS)

    if args.model:
        # Flag given — show banner with model info and load directly
        backend = detect_backend(args.model) if not args.no_mlx else "hf"
        backend_label = "MLX" if backend == "mlx" else "HF"
        print_banner(args.model, backend_label)
        model_fn, model_id, backend = load_and_build(args.model, backend, system_prompt)
    else:
        # No flag — show banner immediately, then picker
        print_banner()
        model_id, backend = show_model_picker()
        model_fn, model_id, backend = load_and_build(model_id, backend, system_prompt)
        backend_label = "MLX" if backend == "mlx" else "HF"
        console.print(f"[dim]✓ Ready — {model_id} · {backend_label}[/dim]\n")

    conversation = []  # persists across turns — the model sees full history

    while True:
        user_input = get_user_input()
        if user_input is None or user_input.lower() == "quit":
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() == "expand":
            expand_last_tool_result()
            continue

        if user_input.lower() == "/model":
            new_model_id, new_backend = show_model_picker(current=model_id)
            if new_model_id != model_id:
                console.print(f"\n[dim]Unloading {model_id}...[/dim]")
                unload_model()
                model_fn, model_id, backend = load_and_build(new_model_id, new_backend, system_prompt)
                console.print(f"[dim]Conversation history preserved ({len(conversation)} messages).[/dim]\n")
            else:
                console.print(f"\n[dim]Already using {model_id}.[/dim]\n")
            continue

        try:
            response = run_conversation_turn(
                user_input,
                conversation,
                model_fn,
                TOOLS,
                confirm_fn=confirm_tool,
                result_fn=print_tool_result,
                display_fn=print_tool_call,
            )
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
            continue

        print_assistant(response)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.stdout.write("\r\033[K")
        console.print("\n[dim]Goodbye.[/dim]")
        sys.exit(0)

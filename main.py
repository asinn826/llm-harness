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
import torch

from harness import build_system_prompt, run_conversation_turn
from tools import TOOLS
from cli import (
    console, print_banner, print_assistant, print_tool_result,
    confirm_tool, get_user_input, thinking_spinner, expand_last_tool_result,
)

_USE_MLX = torch.backends.mps.is_available()


def load_model_mlx(model_id: str):
    """Load a model using mlx-lm (Apple Silicon only).

    mlx-lm uses the MLX framework which compiles Metal kernels for the
    Apple Neural Engine / GPU — much faster than transformers on MPS.
    """
    from mlx_lm import load
    with thinking_spinner(f"Loading {model_id}..."):
        model, tokenizer = load(model_id)
    console.print(f"[dim]✓ Model loaded ({model_id}) via mlx-lm[/dim]\n")
    return tokenizer, model


def make_model_fn_mlx(tokenizer, model, system_prompt: str):
    """Return a model_fn backed by mlx-lm generate."""
    from mlx_lm import generate

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

        response = thinking_spinner(
            fn=lambda: generate(model, tokenizer, prompt=prompt, max_tokens=512, verbose=False,
                                repetition_penalty=1.2, repetition_context_size=100),
        )
        return response.strip()

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
        with thinking_spinner(f"Loading {model_id}..."):
            processor = AutoProcessor.from_pretrained(model_id, token=token)
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                dtype="auto",
                device_map="auto",
                token=token,
            )
            model.eval()
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

        input_len = inputs["input_ids"].shape[-1]

        def _generate():
            with torch.no_grad():
                return model.generate(**inputs, max_new_tokens=512, do_sample=False,
                                      repetition_penalty=1.2)

        output = thinking_spinner(fn=_generate)
        return processor.decode(output[0][input_len:], skip_special_tokens=True).strip()

    return model_fn


def main():
    parser = argparse.ArgumentParser(description="A minimal LLM harness with tool use")
    parser.add_argument(
        "--model",
        default="Qwen/Qwen2.5-0.5B-Instruct",
        help="HuggingFace model ID (default: Qwen/Qwen2.5-0.5B-Instruct)",
    )
    parser.add_argument(
        "--no-mlx",
        action="store_true",
        help="Force HuggingFace transformers backend even on Apple Silicon",
    )
    args = parser.parse_args()

    use_mlx = _USE_MLX and not args.no_mlx

    print_banner()

    if use_mlx:
        tokenizer, model = load_model_mlx(args.model)
        model_fn_factory = make_model_fn_mlx
    else:
        tokenizer, model = load_model_hf(args.model)
        model_fn_factory = make_model_fn_hf

    system_prompt = build_system_prompt(TOOLS)
    model_fn = model_fn_factory(tokenizer, model, system_prompt)
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

        response = run_conversation_turn(
            user_input,
            conversation,
            model_fn,
            TOOLS,
            confirm_fn=confirm_tool,
            result_fn=print_tool_result,
        )

        print_assistant(response)


if __name__ == "__main__":
    main()

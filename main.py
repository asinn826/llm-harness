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
from transformers import AutoTokenizer, AutoModelForCausalLM, logging as hf_logging
import torch

# Suppress noisy but harmless transformers warnings about generation flags
hf_logging.set_verbosity_error()
logging.getLogger("transformers").setLevel(logging.ERROR)
from harness import build_system_prompt, run_conversation_turn
from tools import TOOLS
from cli import (
    console, print_banner, print_assistant, print_tool_result,
    confirm_tool, get_user_input, thinking_spinner,
)


def load_model(model_id: str):
    """Load a HuggingFace model and tokenizer onto the best available device.

    Uses float16 on CUDA/MPS for speed, float32 on CPU (float16 causes numerical
    issues on some CPU implementations).
    """
    if torch.cuda.is_available():
        device = torch.device("cuda")
        dtype = torch.float16
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
        dtype = torch.float16
    else:
        device = torch.device("cpu")
        dtype = torch.float32

    with thinking_spinner(f"Loading {model_id}..."):
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=dtype,
        ).to(device)
        model.eval()
    console.print(f"[dim]✓ Model loaded ({model_id}) on {device}[/dim]\n")
    return tokenizer, model


def make_model_fn(tokenizer, model, system_prompt: str):
    """Return a callable(conversation) -> str that runs one generation step.

    The harness calls this in a loop — it doesn't know or care whether the
    model is running locally, via API, or is a test stub. Anything callable
    that takes a conversation list and returns a string works.
    """
    def model_fn(conversation: list) -> str:
        messages = [{"role": "system", "content": system_prompt}] + conversation

        # apply_chat_template formats the conversation in the model's expected
        # format (e.g. ChatML, Llama-3 tokens). Fall back to a manual format
        # if the tokenizer doesn't support it.
        if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template:
            input_ids = tokenizer.apply_chat_template(
                messages,
                return_tensors="pt",
                add_generation_prompt=True,
            ).to(model.device)
        else:
            lines = []
            for m in messages:
                if m["role"] == "tool":
                    # In fallback mode, present tool results as user context
                    lines.append(f"USER: [Tool result] {m['content']}")
                else:
                    lines.append(f"{m['role'].upper()}: {m['content']}")
            text = "\n".join(lines)
            text += "\nASSISTANT:"
            input_ids = tokenizer(text, return_tensors="pt").input_ids.to(model.device)

        # Build attention mask explicitly to avoid the pad==eos warning
        attention_mask = torch.ones_like(input_ids)

        # Spinner only wraps generation — NOT confirmation prompts
        with thinking_spinner():
            with torch.no_grad():
                output = model.generate(
                    input_ids,
                    attention_mask=attention_mask,
                    max_new_tokens=512,
                    do_sample=False,
                    pad_token_id=tokenizer.eos_token_id,
                )

        # Slice off the input tokens — we only want the newly generated ones
        new_tokens = output[0][input_ids.shape[-1]:]
        return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    return model_fn


def main():
    parser = argparse.ArgumentParser(description="A minimal LLM harness with tool use")
    parser.add_argument(
        "--model",
        default="Qwen/Qwen2.5-0.5B-Instruct",
        help="HuggingFace model ID (default: Qwen/Qwen2.5-0.5B-Instruct)",
    )
    args = parser.parse_args()

    print_banner()
    tokenizer, model = load_model(args.model)

    system_prompt = build_system_prompt(TOOLS)
    model_fn = make_model_fn(tokenizer, model, system_prompt)
    conversation = []  # persists across turns — the model sees full history

    while True:
        user_input = get_user_input()
        if not user_input or user_input.lower() == "quit":
            console.print("\n[dim]Goodbye.[/dim]")
            break

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

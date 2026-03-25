# LLM Harness Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a minimal but complete LLM harness that lets developers accomplish real tasks through a polished CLI, while being simple enough to read top-to-bottom in an afternoon and understand exactly how it works. The "aha" moment: reading the generation loop and thinking "this is basically what Claude Code is doing."

**Architecture:** Tools are defined as Python functions whose signatures are serialized into the system prompt as JSON schemas. The model outputs JSON tool calls; the harness parses them, confirms with the user, runs them, and injects results back into the conversation until the model produces a plain text response. A dedicated `cli.py` handles all presentation (colors, spinners, confirmations) separately from harness logic.

**Tech Stack:** Python 3.10+, `transformers`, `torch`, `requests`, `rich`, `pytest`

---

### Task 1: Project scaffolding

**Files:**
- Create: `main.py`
- Create: `harness.py`
- Create: `tools.py`
- Create: `cli.py`
- Create: `requirements.txt`
- Create: `tests/test_tools.py`
- Create: `tests/test_harness.py`

**Step 1: Create requirements.txt**

```
transformers>=4.40
torch>=2.2
requests>=2.31
rich>=13.0
pytest>=8.0
```

**Step 2: Create empty module files**

Create `tools.py`, `harness.py`, `cli.py`, `main.py` with just a module docstring each:

```python
"""Tools available to the LLM harness."""
```

```python
"""LLM harness: generation loop and tool call handling."""
```

```python
"""CLI presentation: colors, spinners, confirmations, and startup banner."""
```

```python
"""Entry point: load model and start CLI loop."""
```

**Step 3: Create test files**

```python
# tests/test_tools.py
"""Tests for tool functions."""
```

```python
# tests/test_harness.py
"""Tests for harness logic (no model loading required)."""
```

**Step 4: Install dependencies**

```bash
pip install -r requirements.txt
```

**Step 5: Commit**

```bash
git add .
git commit -m "chore: scaffold project structure"
```

---

### Task 2: Implement tools

**Files:**
- Modify: `tools.py`
- Modify: `tests/test_tools.py`

**Step 1: Write failing tests**

```python
# tests/test_tools.py
import pytest
from tools import run_shell, read_file, write_file, calculator, web_search, TOOLS

def test_run_shell_returns_output():
    result = run_shell("echo hello")
    assert "hello" in result

def test_run_shell_returns_stderr_on_error():
    result = run_shell("cat nonexistent_file_xyz")
    assert result  # non-empty error message

def test_read_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    result = read_file(str(f))
    assert result == "hello world"

def test_read_file_missing():
    result = read_file("/nonexistent/path/file.txt")
    assert "Error" in result

def test_write_file(tmp_path):
    path = str(tmp_path / "out.txt")
    result = write_file(path, "hello")
    assert result == "OK"
    assert open(path).read() == "hello"

def test_calculator_basic():
    assert calculator("2 + 2") == "4"

def test_calculator_bad_expression():
    result = calculator("import os")
    assert "Error" in result

def test_tools_registry_has_all_tools():
    assert set(TOOLS.keys()) == {"run_shell", "read_file", "write_file", "calculator", "web_search"}
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tools.py -v
```
Expected: FAIL with `ImportError: cannot import name 'run_shell' from 'tools'`

**Step 3: Implement tools.py**

```python
"""Tools available to the LLM harness."""
import subprocess
import requests


def run_shell(command: str) -> str:
    """Run a shell command and return stdout+stderr. Args: command (str)."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    return (result.stdout + result.stderr).strip() or "(no output)"


def read_file(path: str) -> str:
    """Read a file and return its contents. Args: path (str)."""
    try:
        return open(path).read()
    except Exception as e:
        return f"Error: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to a file. Args: path (str), content (str)."""
    try:
        with open(path, "w") as f:
            f.write(content)
        return "OK"
    except Exception as e:
        return f"Error: {e}"


def calculator(expression: str) -> str:
    """Evaluate a math expression. Args: expression (str)."""
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        return "Error: only basic math expressions allowed"
    try:
        return str(eval(expression))
    except Exception as e:
        return f"Error: {e}"


def web_search(query: str) -> str:
    """Search the web using DuckDuckGo and return results. Args: query (str)."""
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_redirect": 1},
            timeout=10,
        )
        data = resp.json()
        results = []
        if data.get("AbstractText"):
            results.append(data["AbstractText"])
        for r in data.get("RelatedTopics", [])[:3]:
            if isinstance(r, dict) and r.get("Text"):
                results.append(r["Text"])
        return "\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Error: {e}"


TOOLS = {
    "run_shell": run_shell,
    "read_file": read_file,
    "write_file": write_file,
    "calculator": calculator,
    "web_search": web_search,
}
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tools.py -v
```
Expected: all PASS (web_search may vary by network)

**Step 5: Commit**

```bash
git add tools.py tests/test_tools.py
git commit -m "feat: implement tools with tests"
```

---

### Task 3: Implement harness logic

**Files:**
- Modify: `harness.py`
- Modify: `tests/test_harness.py`

**Step 1: Write failing tests**

```python
# tests/test_harness.py
import pytest
from harness import build_system_prompt, parse_tool_call, get_tool_schemas
from tools import TOOLS


def test_get_tool_schemas_includes_all_tools():
    schemas = get_tool_schemas(TOOLS)
    assert "run_shell" in schemas
    assert "calculator" in schemas


def test_build_system_prompt_contains_tool_names():
    prompt = build_system_prompt(TOOLS)
    assert "run_shell" in prompt
    assert "calculator" in prompt
    assert "JSON" in prompt


def test_parse_tool_call_detects_valid_json():
    response = '{"tool": "calculator", "args": {"expression": "2+2"}}'
    result = parse_tool_call(response)
    assert result is not None
    assert result["tool"] == "calculator"
    assert result["args"] == {"expression": "2+2"}


def test_parse_tool_call_returns_none_for_plain_text():
    result = parse_tool_call("The answer is 42.")
    assert result is None


def test_parse_tool_call_returns_none_for_bad_json():
    result = parse_tool_call("{ not valid json }")
    assert result is None


def test_parse_tool_call_returns_none_for_json_without_tool_key():
    result = parse_tool_call('{"foo": "bar"}')
    assert result is None
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_harness.py -v
```
Expected: FAIL with `ImportError`

**Step 3: Implement harness.py**

```python
"""LLM harness: generation loop and tool call handling."""
import json
import inspect
import re


def get_tool_schemas(tools: dict) -> dict:
    """Extract name and docstring from each tool function."""
    schemas = {}
    for name, fn in tools.items():
        schemas[name] = {
            "name": name,
            "description": inspect.getdoc(fn) or "",
        }
    return schemas


def build_system_prompt(tools: dict) -> str:
    """Build a system prompt that describes available tools."""
    schemas = get_tool_schemas(tools)
    tool_descriptions = json.dumps(list(schemas.values()), indent=2)
    return f"""You are a helpful assistant with access to tools.

To use a tool, respond with ONLY a JSON object in this exact format:
{{"tool": "<tool_name>", "args": {{"<arg_name>": "<value>"}}}}

Available tools:
{tool_descriptions}

If you don't need a tool, just respond normally in plain text.
Only call one tool at a time. Wait for the result before calling another."""


def parse_tool_call(response: str) -> dict | None:
    """Try to parse a tool call JSON from the model response. Returns None if plain text."""
    # Strip markdown code blocks if present
    text = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", response, flags=re.DOTALL).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "tool" in data:
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def confirm_and_run(tool_call: dict, tools: dict) -> str:
    """Ask user to confirm, then run the tool. Returns the result string."""
    tool_name = tool_call.get("tool")
    args = tool_call.get("args", {})

    if tool_name not in tools:
        return f"Error: unknown tool '{tool_name}'"

    print(f"\n[Tool call] {tool_name}({args})")
    answer = input("Run this? [y/n]: ").strip().lower()
    if answer != "y":
        return "Tool call denied by user."

    try:
        return str(tools[tool_name](**args))
    except Exception as e:
        return f"Error running tool: {e}"


def run_conversation_turn(user_message: str, conversation: list, model_fn, tools: dict, max_iterations: int = 10) -> str:
    """
    Run one full conversation turn: append user message, loop through tool calls
    until a plain text response, return the final assistant message.

    model_fn: callable(conversation: list[dict]) -> str
    """
    conversation.append({"role": "user", "content": user_message})

    for _ in range(max_iterations):
        response = model_fn(conversation)
        tool_call = parse_tool_call(response)

        if tool_call is None:
            conversation.append({"role": "assistant", "content": response})
            return response

        # It's a tool call
        conversation.append({"role": "assistant", "content": response})
        result = confirm_and_run(tool_call, tools)
        conversation.append({"role": "tool", "content": result})

    # Hit max iterations
    return "Reached maximum tool call iterations."
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_harness.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add harness.py tests/test_harness.py
git commit -m "feat: implement harness logic with tests"
```

---

### Task 4: Implement cli.py (polished CLI presentation)

**Files:**
- Modify: `cli.py`

No unit tests — visual output. Manual verification instead.

**Step 1: Implement cli.py**

```python
"""CLI presentation: colors, spinners, confirmations, and startup banner.

This module owns everything the user sees. Harness logic lives in harness.py —
keeping presentation separate means you can swap out the CLI for an API or web
interface without touching any core logic.
"""
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text
from rich import print as rprint

console = Console()

BANNER = """[bold cyan]LLM Harness[/bold cyan] — a minimal agent loop

How it works:
  1. Your message is added to a conversation list
  2. The model generates a response
  3. If the response is a JSON tool call, the harness runs it and feeds the result back
  4. This repeats until the model responds in plain text
  5. That's it — this is what Claude Code does too, just with more tools

Type [bold]quit[/bold] to exit.
"""


def print_banner():
    """Print the startup banner explaining how the harness works."""
    console.print(Panel(BANNER, border_style="cyan"))


def print_user(message: str):
    """Display the user's message."""
    console.print(f"\n[bold green]You:[/bold green] {message}")


def print_assistant(message: str):
    """Display the assistant's final response."""
    console.print(f"\n[bold blue]Assistant:[/bold blue] {message}\n")


def print_tool_call(tool_name: str, args: dict):
    """Display an incoming tool call request."""
    args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
    console.print(f"\n[bold yellow]⚙ Tool call:[/bold yellow] [cyan]{tool_name}[/cyan]({args_str})")


def print_tool_result(result: str):
    """Display the result returned by a tool."""
    # Truncate long results for readability
    display = result if len(result) < 500 else result[:500] + "\n[dim]... (truncated)[/dim]"
    console.print(f"[dim]  → {display}[/dim]")


def confirm_tool(tool_name: str, args: dict) -> bool:
    """Ask the user whether to run a tool. Returns True if approved."""
    print_tool_call(tool_name, args)
    return Confirm.ask("  Run this?", default=True)


def get_user_input() -> str:
    """Get input from the user. Returns empty string on EOF."""
    try:
        return Prompt.ask("\n[bold green]You[/bold green]").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def thinking_spinner(label: str = "Thinking..."):
    """Return a Live context manager showing a spinner while the model generates."""
    return Live(Spinner("dots", text=f"[dim]{label}[/dim]"), console=console, transient=True)
```

**Step 2: Update confirm_and_run in harness.py to accept a confirm_fn**

The harness should not import from `cli.py` directly — instead, `confirm_and_run` should accept a `confirm_fn` callable so it stays testable and presentation-agnostic:

```python
def confirm_and_run(tool_call: dict, tools: dict, confirm_fn=None) -> str:
    """Ask user to confirm, then run the tool. Returns the result string.

    confirm_fn: callable(tool_name, args) -> bool. Defaults to a plain input() prompt.
    """
    tool_name = tool_call.get("tool")
    args = tool_call.get("args", {})

    if tool_name not in tools:
        return f"Error: unknown tool '{tool_name}'"

    if confirm_fn is None:
        # Fallback for testing / non-CLI use
        print(f"[Tool call] {tool_name}({args})")
        answer = input("Run this? [y/n]: ").strip().lower()
        approved = answer == "y"
    else:
        approved = confirm_fn(tool_name, args)

    if not approved:
        return "Tool call denied by user."

    try:
        return str(tools[tool_name](**args))
    except Exception as e:
        return f"Error running tool: {e}"
```

Also update `run_conversation_turn` signature to pass `confirm_fn` through:

```python
def run_conversation_turn(user_message, conversation, model_fn, tools, confirm_fn=None, max_iterations=10):
    ...
    result = confirm_and_run(tool_call, tools, confirm_fn=confirm_fn)
    ...
```

**Step 3: Verify manually**

```bash
python -c "from cli import print_banner; print_banner()"
```
Expected: colored banner printed to terminal.

**Step 4: Commit**

```bash
git add cli.py harness.py
git commit -m "feat: add rich CLI presentation layer"
```

---

### Task 5: Implement main.py (model loading + CLI)

**Files:**
- Modify: `main.py`

No unit tests for this task — it requires a real model. Manual testing instead.

**Step 1: Implement main.py**

```python
"""Entry point: load model and start CLI loop.

This file wires together three independent pieces:
  - tools.py    : what the model can do
  - harness.py  : the generation + tool-call loop
  - cli.py      : what the user sees

Keeping them separate means you can swap any one piece without touching the others.
For example: replace cli.py with a FastAPI server to get a web interface.
"""
import argparse
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
from harness import build_system_prompt, run_conversation_turn
from tools import TOOLS
from cli import (
    console, print_banner, print_assistant, print_tool_result,
    confirm_tool, get_user_input, thinking_spinner
)


def load_model(model_id: str):
    """Load a HuggingFace model and tokenizer onto the best available device."""
    with thinking_spinner(f"Loading {model_id}..."):
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto",
        )
        model.eval()
    console.print(f"[dim]✓ Model loaded ({model_id})[/dim]\n")
    return tokenizer, model


def make_model_fn(tokenizer, model, system_prompt: str):
    """Return a callable(conversation) -> str that runs one generation step.

    The harness calls this in a loop. Keeping it as a plain callable means the
    harness doesn't need to know anything about HuggingFace internals.
    """
    def model_fn(conversation: list) -> str:
        messages = [{"role": "system", "content": system_prompt}] + conversation
        if hasattr(tokenizer, "apply_chat_template"):
            input_ids = tokenizer.apply_chat_template(
                messages,
                return_tensors="pt",
                add_generation_prompt=True,
            ).to(model.device)
        else:
            text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
            text += "\nASSISTANT:"
            input_ids = tokenizer(text, return_tensors="pt").input_ids.to(model.device)

        with torch.no_grad():
            output = model.generate(
                input_ids,
                max_new_tokens=512,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )

        new_tokens = output[0][input_ids.shape[-1]:]
        return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    return model_fn


def on_tool_result(result: str):
    """Callback invoked by the harness after a tool runs — we print the result."""
    print_tool_result(result)


def main():
    parser = argparse.ArgumentParser(description="A minimal LLM harness with tool use")
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct", help="HuggingFace model ID")
    args = parser.parse_args()

    print_banner()
    tokenizer, model = load_model(args.model)
    system_prompt = build_system_prompt(TOOLS)
    model_fn = make_model_fn(tokenizer, model, system_prompt)
    conversation = []

    while True:
        user_input = get_user_input()
        if not user_input or user_input.lower() == "quit":
            console.print("\n[dim]Goodbye.[/dim]")
            break

        with thinking_spinner():
            response = run_conversation_turn(
                user_input,
                conversation,
                model_fn,
                TOOLS,
                confirm_fn=confirm_tool,
            )

        print_assistant(response)


if __name__ == "__main__":
    main()
```

**Step 2: Run manually with a small model**

```bash
python main.py --model Qwen/Qwen2.5-0.5B-Instruct
```

Try prompts like:
- `"what is 123 * 456?"` — should trigger calculator tool
- `"what files are in the current directory?"` — should trigger run_shell with `ls`
- `"what is the capital of France?"` — should answer directly, no tool

**Step 3: Commit**

```bash
git add main.py
git commit -m "feat: implement model loading and CLI entry point"
```

---

### Task 6: Run full test suite and clean up

**Step 1: Run all tests**

```bash
pytest tests/ -v
```
Expected: all PASS

**Step 2: Verify manual run works end-to-end**

```bash
python main.py --model Qwen/Qwen2.5-0.5B-Instruct
```
Check:
- Banner prints with architecture explanation
- Spinner appears while model loads and generates
- Tool calls show in yellow with confirmation prompt
- Tool results show dimmed below the call
- Assistant response shows in blue

**Step 3: Final commit**

```bash
git add .
git commit -m "chore: final cleanup and verified test suite"
```

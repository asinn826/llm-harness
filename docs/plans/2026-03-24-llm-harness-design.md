# LLM Harness Design

**Date:** 2026-03-24

## Product Goal

> A minimal but complete LLM harness that lets developers accomplish real tasks through a polished CLI, while being simple enough to read top-to-bottom in an afternoon and understand exactly how it works.

**Success looks like:**
- A developer uses it to do something genuinely useful (run a shell command, search the web, read/write files) and thinks *"I could build on this"*
- The code is short enough that they can trace a single request from `input()` through tool use back to the response — and see it's not magic
- The CLI feels real: colored output, visible tool confirmations, a sense of responsiveness
- Adding a new tool is one function + one line in a registry — no framework knowledge required

**The "aha" moment:** Reading the generation loop and thinking *"wait, this is basically what Claude Code is doing"*

## Technical Goal

Build a simple LLM harness using HuggingFace transformers to understand how tool use works end-to-end. Educational focus — every step should be explicit and visible.

## Approach

Structured output parsing: tools are defined as Python functions, their schemas are injected into the system prompt as JSON, and the model outputs JSON tool calls that the harness parses and executes.

## Architecture

Three layers:
1. **Tool registry** — dict of `name → function`, schemas serialized into system prompt
2. **Generation loop** — HuggingFace model in a `while True` loop, handles tool calls until plain text response
3. **CLI** — simple `input()` loop

## Components

### `tools.py`
- `run_shell(command)` — runs a bash command, returns stdout/stderr
- `read_file(path)` — reads a file, returns contents
- `write_file(path, content)` — writes content to a file
- `calculator(expression)` — evaluates a math expression via `eval()`
- `web_search(query)` — fetches DuckDuckGo results via `requests`

### `harness.py`
- `build_system_prompt(tools)` — serializes tool schemas into system prompt
- `parse_tool_call(response)` — extracts JSON from model output, returns `None` if plain text
- `confirm_and_run(tool_call)` — prints the call, asks `[y/n]`, runs if approved
- `chat(user_message)` — main loop: appends message, generates, handles tool calls until final answer

### `cli.py`
- Colored output via `rich` (user input, assistant response, tool calls each styled differently)
- Visible tool confirmation prompt with tool name + args displayed clearly
- Spinner while model is generating
- Prints a brief "how this works" header on startup so developers immediately see the architecture

### `main.py`
- Loads model + tokenizer from HuggingFace
- Wires together cli + harness + tools and starts the loop

## Data Flow

```
user input
    ↓
append to conversation as {"role": "user", "content": "..."}
    ↓
format conversation → tokenize → model.generate()
    ↓
decode output → parse_tool_call()
    ↓ (tool call detected)              ↓ (plain text)
confirm with user [y/n]              append as {"role": "assistant"}
    ↓ approved                           print to user, wait for next input
run tool, get result
    ↓
append tool result as {"role": "tool", "content": "..."}
    ↓
loop back to generate()
```

## Error Handling

- **Malformed JSON** — treat as plain text response
- **Tool exception** — return error string as tool result so model can recover
- **User denies tool** — inject denial message so model can respond gracefully
- **Infinite loop** — max 10 iterations per user message

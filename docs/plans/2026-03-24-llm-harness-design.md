# LLM Harness Design

**Date:** 2026-03-24

## Goal

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

### `main.py`
- Loads model + tokenizer from HuggingFace
- Starts the CLI input loop

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

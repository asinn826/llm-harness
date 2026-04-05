# Welcome Screen Redesign

## Summary

Replace the current 5-step "how it works" welcome banner with a minimal, information-dense welcome screen that shows what the harness can do rather than explaining how it works internally.

## Design

### Layout

Single Rich `Panel` with `border_style="dim"`. Three sections separated by breathing room (blank lines) and a dim horizontal rule.

### Structure

```
╭──────────────────────────────────────────────────────╮
│                                                      │
│  LLM Harness — local agent loop                      │
│  any HF model · shell · files · web · imessage ·     │
│  calendar                                            │
│                                                      │
│  ────────────────────────────────────────────────     │
│                                                      │
│  Model  google/gemma-3-4b-it · MLX                   │
│                                                      │
│  try: "what's on my calendar today?"                 │
│                                                      │
╰──────────────────────────────────────────────────────╯
```

### Sections

**1. Identity block (top)**
- Title: `[bold white]LLM Harness[/bold white]` + `[dim]— local agent loop[/dim]`
- Tool list: `[dim]any HF model · shell · files · web · imessage · calendar[/dim]`

**2. Model info (middle)**
- Format: `[dim]Model[/dim]  [white]{model_name}[/white] [dim]·[/dim] [white]{backend}[/white]`
- `model_name`: the Hugging Face model ID (e.g., `google/gemma-3-4b-it`)
- `backend`: `MLX` or `HF` depending on which inference backend was loaded
- Both values are already known in `main.py` at startup and will be passed to `print_banner()`

**3. Hint (bottom)**
- Format: `[dim]try: "{hint}"[/dim]`
- Randomly selected from a pool on each launch via `random.choice`

### Hint Pool

```python
HINTS = [
    "what's on my calendar today?",
    "send a gif to someone who deserves it",
    "read my latest texts",
    "summarize this file: README.md",
    "search the web for ...",
]
```

### Separator

A dim horizontal rule between the identity block and model info. Implemented as either:
- A Rich `Rule(style="dim")`, or
- A string of `─` characters with `[dim]` markup

Rich's Panel handles right-border alignment and padding automatically, so the separator width is managed by the panel — no manual character counting needed.

### Styling Summary

| Element | Rich markup |
|---|---|
| Title | `[bold white]LLM Harness[/bold white]` |
| Subtitle | `[dim]— local agent loop[/dim]` |
| Tool list | `[dim]any HF model · shell · files · web · ...[/dim]` |
| Separator | `[dim]` rule |
| Model label | `[dim]Model[/dim]` |
| Model value | `[white]{model_name}[/white] [dim]·[/dim] [white]{backend}[/white]` |
| Hint | `[dim]try: "{hint}"[/dim]` |

## Changes Required

### `cli.py`
- Replace the `BANNER` string constant with a function that accepts `model_name` and `backend` parameters
- Add `HINTS` list and `random.choice` selection
- Update `print_banner()` signature to `print_banner(model_name: str, backend: str)`

### `main.py`
- Pass `model_name` and `backend` to `print_banner()` at the call site (line ~271)
- Both values are already available in scope at that point

### No other files affected.

## What's Removed

- The 5-step "how it works" explanation
- The "Type quit to exit" instruction (users figure this out; the hint line is more useful)

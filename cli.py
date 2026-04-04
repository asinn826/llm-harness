"""CLI presentation: colors, spinners, confirmations, and startup banner.

This module owns everything the user sees. Harness logic lives in harness.py —
keeping presentation separate means you can swap out the CLI for an API or web
interface without touching any core logic. The harness calls back into here via
the confirm_fn parameter.
"""
import atexit
import os
import readline
import select
import sys
import termios
import tty
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text

console = Console()

_HISTORY_FILE = Path.home() / ".llm_harness_history"
try:
    readline.read_history_file(_HISTORY_FILE)
except FileNotFoundError:
    pass
readline.set_history_length(500)
atexit.register(readline.write_history_file, _HISTORY_FILE)

# Word-by-word navigation with Option+Left/Right.
# Terminals send different sequences depending on config:
#   \e[1;3D / \e[1;3C  — macOS Terminal.app with "Use Option as Meta key"
#   \e[3D   / \e[3C    — some other terminals
readline.parse_and_bind(r'"\e[1;3D": backward-word')
readline.parse_and_bind(r'"\e[1;3C": forward-word')
readline.parse_and_bind(r'"\e[3D": backward-word')
readline.parse_and_bind(r'"\e[3C": forward-word')

# Ctrl+O expands the last truncated tool result at any point during input.
# macOS uses libedit (not GNU readline), which requires different bind syntax.
_using_libedit = "libedit" in (readline.__doc__ or "")
if _using_libedit:
    # libedit: bind -s binds a key to a literal string; \n submits the line
    readline.parse_and_bind(r"bind -s '^O' 'expand\n'")
else:
    readline.parse_and_bind(r'"\C-o": "expand\n"')

_last_tool_result: str = ""

BANNER = """[bold white]LLM Harness[/bold white] — a minimal agent loop

[dim]How it works:[/dim]
  [dim]1.[/dim] Your message is added to a conversation list
  [dim]2.[/dim] The model generates a response (just tokens — no magic)
  [dim]3.[/dim] If the response is a JSON tool call, the harness runs it and feeds the result back
  [dim]4.[/dim] This repeats until the model responds in plain text
  [dim]5.[/dim] That's it — this is what Claude Code does too, just with more tools

Type [bold]quit[/bold] to exit.
"""


def print_banner():
    """Print the startup banner explaining how the harness works."""
    console.print(Panel(BANNER, border_style="dim"))


def print_assistant(message: str):
    """Display the assistant's final plain-text response."""
    console.print(f"\n[dim]→[/dim] {message}\n")


def print_tool_call(tool_name: str, args: dict):
    """Display an incoming tool call request."""
    args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
    console.print(f"\n[bold white]⚙ Tool call:[/bold white] [white]{tool_name}[/white]({args_str})")


def print_tool_result(result: str):
    """Display the result returned by a tool (truncated if long).

    Stores the full result so Ctrl+O can expand it later.
    """
    global _last_tool_result
    _last_tool_result = result

    if len(result) < 500:
        display = result
    else:
        truncated_chars = len(result) - 500
        truncated_lines = result[500:].count('\n')
        display = result[:500] + f"\n[dim]... (truncated — {truncated_lines} more lines, {truncated_chars} chars — press Ctrl+O to expand)[/dim]"
    console.print(f"[dim]  → {display}[/dim]")


def expand_last_tool_result():
    """Show the full last tool result in an alternate-screen overlay.

    Opens a pager-like view: arrow keys / j/k / space to scroll,
    Esc / Ctrl+O / q to dismiss. Uses the terminal's alternate screen
    buffer so the main conversation is fully restored on exit.
    """
    if not _last_tool_result:
        console.print("[dim]  (no tool result to expand)[/dim]")
        return

    if not sys.stdin.isatty():
        console.print(f"[dim]  → {_last_tool_result}[/dim]")
        return

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    lines = _last_tool_result.split('\n')
    scroll = 0

    try:
        cols, rows = os.get_terminal_size()
        visible = rows - 2  # header + footer
        max_scroll = max(0, len(lines) - visible)

        # Enter alternate screen, hide cursor
        sys.stdout.write('\033[?1049h\033[?25l')
        tty.setraw(fd)

        while True:
            # Draw frame
            sys.stdout.write('\033[2J\033[H')
            header = f" Tool Output ({len(lines)} lines) \u2014 Esc/Ctrl+O/q to close, \u2191\u2193/j/k to scroll "
            sys.stdout.write(f'\033[7m{header[:cols]:<{cols}}\033[0m\r\n')

            for i in range(scroll, min(scroll + visible, len(lines))):
                sys.stdout.write(f'{lines[i][:cols]}\r\n')

            # Footer at bottom
            sys.stdout.write(f'\033[{rows};1H')
            end = min(scroll + visible, len(lines))
            pct = int(end / len(lines) * 100) if lines else 100
            foot = f" {scroll + 1}-{end}/{len(lines)} ({min(pct, 100)}%) "
            sys.stdout.write(f'\033[7m{foot[:cols]:<{cols}}\033[0m')
            sys.stdout.flush()

            ch = os.read(fd, 1)
            if ch == b'\x1b':  # Escape or arrow sequence
                r, _, _ = select.select([fd], [], [], 0.05)
                if r:
                    seq = os.read(fd, 2)
                    if seq == b'[A':       # Up
                        scroll = max(0, scroll - 1)
                    elif seq == b'[B':     # Down
                        scroll = min(max_scroll, scroll + 1)
                    elif seq in (b'[5', b'[6'):  # Page Up / Page Down
                        try:
                            os.read(fd, 1)  # consume ~
                        except Exception:
                            pass
                        if seq == b'[5':
                            scroll = max(0, scroll - visible)
                        else:
                            scroll = min(max_scroll, scroll + visible)
                    continue
                break  # plain Esc
            elif ch in (b'\x0f', b'q', b'Q'):  # Ctrl+O or q
                break
            elif ch == b'j':
                scroll = min(max_scroll, scroll + 1)
            elif ch == b'k':
                scroll = max(0, scroll - 1)
            elif ch == b' ':
                scroll = min(max_scroll, scroll + visible)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write('\033[?25h\033[?1049l')
        sys.stdout.flush()


def confirm_tool(tool_name: str, args: dict) -> bool:
    """Ask the user whether to run a tool. Returns True if approved.

    This is passed as confirm_fn to run_conversation_turn — it's the bridge
    between the harness (which knows about tools) and the CLI (which knows
    about presentation).
    """
    print_tool_call(tool_name, args)
    response = console.input("  [dim]Run this? \\[Y/n] [/dim]").strip().lower()
    return response in ("", "y")


def get_user_input() -> Optional[str]:
    """Prompt the user for input. Returns None on EOF/interrupt, empty string on blank input."""
    try:
        print()  # blank line before prompt — kept outside input() so readline ignores it
        text = input("\001\033[1;38;5;214m\002❯\001\033[0m\002 ").strip()
        # Prune throwaway entries from history so they don't pollute up-arrow navigation
        if not text or text.lower() == "quit":
            length = readline.get_current_history_length()
            if length > 0:
                readline.remove_history_item(length - 1)
        return text
    except (EOFError, KeyboardInterrupt):
        return None


def thinking_spinner(label: str = "Thinking..."):
    """Return a Live context manager that shows a spinner while the model generates.

    Usage:
        with thinking_spinner():
            result = model_fn(conversation)
    """
    return Live(Spinner("dots", text=f"[dim]{label}[/dim]"), console=console, transient=True)

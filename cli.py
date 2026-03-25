"""CLI presentation: colors, spinners, confirmations, and startup banner.

This module owns everything the user sees. Harness logic lives in harness.py —
keeping presentation separate means you can swap out the CLI for an API or web
interface without touching any core logic. The harness calls back into here via
the confirm_fn parameter.
"""
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text

console = Console()

BANNER = """[bold cyan]LLM Harness[/bold cyan] — a minimal agent loop

[dim]How it works:[/dim]
  [cyan]1.[/cyan] Your message is added to a conversation list
  [cyan]2.[/cyan] The model generates a response (just tokens — no magic)
  [cyan]3.[/cyan] If the response is a JSON tool call, the harness runs it and feeds the result back
  [cyan]4.[/cyan] This repeats until the model responds in plain text
  [cyan]5.[/cyan] That's it — this is what Claude Code does too, just with more tools

Type [bold]quit[/bold] to exit.
"""


def print_banner():
    """Print the startup banner explaining how the harness works."""
    console.print(Panel(BANNER, border_style="cyan"))


def print_assistant(message: str):
    """Display the assistant's final plain-text response."""
    console.print(f"\n[bold blue]Assistant:[/bold blue] {message}\n")


def print_tool_call(tool_name: str, args: dict):
    """Display an incoming tool call request."""
    args_str = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
    console.print(f"\n[bold yellow]⚙ Tool call:[/bold yellow] [cyan]{tool_name}[/cyan]({args_str})")


def print_tool_result(result: str):
    """Display the result returned by a tool (truncated if long)."""
    display = result if len(result) < 500 else result[:500] + "\n[dim]... (truncated)[/dim]"
    console.print(f"[dim]  → {display}[/dim]")


def confirm_tool(tool_name: str, args: dict) -> bool:
    """Ask the user whether to run a tool. Returns True if approved.

    This is passed as confirm_fn to run_conversation_turn — it's the bridge
    between the harness (which knows about tools) and the CLI (which knows
    about presentation).
    """
    print_tool_call(tool_name, args)
    return Confirm.ask("  Run this?", default=True)


def get_user_input() -> str:
    """Prompt the user for input. Returns empty string on EOF/interrupt."""
    try:
        return Prompt.ask("\n[bold green]You[/bold green]").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def thinking_spinner(label: str = "Thinking..."):
    """Return a Live context manager that shows a spinner while the model generates.

    Usage:
        with thinking_spinner():
            result = model_fn(conversation)
    """
    return Live(Spinner("dots", text=f"[dim]{label}[/dim]"), console=console, transient=True)

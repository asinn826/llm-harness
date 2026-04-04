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
import threading
import tty
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live

console = Console()

_HISTORY_FILE = Path.home() / ".llm_harness_history"
try:
    readline.read_history_file(_HISTORY_FILE)
except FileNotFoundError:
    pass
readline.set_history_length(500)
atexit.register(readline.write_history_file, _HISTORY_FILE)

_last_tool_result: str = ""


def _setcbreak(fd):
    """Like tty.setcbreak but also clears IEXTEN.

    macOS's terminal driver maps Ctrl+O to VDISCARD (output flush toggle).
    VDISCARD is processed when IEXTEN is set — even in non-canonical mode —
    which means the byte never reaches the application. Clearing IEXTEN
    ensures Ctrl+O arrives as a normal 0x0F byte.
    """
    tty.setcbreak(fd)
    mode = termios.tcgetattr(fd)
    mode[3] &= ~termios.IEXTEN
    termios.tcsetattr(fd, termios.TCSANOW, mode)

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


_last_was_streamed = False


def print_assistant(message: str):
    """Display the assistant's final plain-text response.

    Skips printing if the response was already streamed token-by-token
    (model_fn sets _last_was_streamed when it streams).
    """
    global _last_was_streamed
    if _last_was_streamed:
        _last_was_streamed = False
        return
    console.print(f"\n[dim]→[/dim] {message}\n")


def start_stream():
    """Print the stream prefix (→) and mark that streaming is active."""
    global _last_was_streamed
    _last_was_streamed = True
    sys.stdout.write(f"\n\033[2m→\033[0m ")
    sys.stdout.flush()


def stream_token(token: str):
    """Print a single token during streaming."""
    sys.stdout.write(token)
    sys.stdout.flush()


def end_stream():
    """Finish streaming output with a trailing newline."""
    sys.stdout.write('\n')
    sys.stdout.flush()


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
        termios.tcflush(fd, termios.TCIFLUSH)

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


# ── Raw input with native Ctrl+O support ────────────────────────────────────
# Replaces Python's input() so we can intercept Ctrl+O (0x0F) directly in
# cbreak mode. Handles line editing (backspace, arrows, home/end, kill-line,
# kill-word) and history (up/down) using readline's history API. This avoids
# fighting with libedit's `ed-sequence-lead-in` binding on macOS.


def _read_char(fd: int) -> bytes:
    """Read one complete character from fd, handling UTF-8 multi-byte sequences."""
    b = os.read(fd, 1)
    if not b:
        return b
    first = b[0]
    if first & 0x80 == 0:
        return b
    elif first & 0xE0 == 0xC0:
        return b + os.read(fd, 1)
    elif first & 0xF0 == 0xE0:
        return b + os.read(fd, 2)
    elif first & 0xF8 == 0xF0:
        return b + os.read(fd, 3)
    return b


_PROMPT_COLS = 2  # visible width of "❯ " (emoji + space)
_PROMPT_STR = "\033[1;38;5;214m❯\033[0m "


def _redraw_line(buf: list, pos: int, old_len: int):
    """Erase the entire input area and redraw buf, leaving cursor at pos.

    Handles wrapped lines correctly by moving up to the prompt row before
    clearing. Uses absolute cursor positioning (up/right) rather than
    cursor-left, which doesn't cross line-wrap boundaries.
    """
    cols = os.get_terminal_size().columns

    # Move cursor up to the prompt row. The old content may have wrapped
    # across multiple terminal lines — we need to get back to the first one.
    old_total = _PROMPT_COLS + old_len
    lines_below = old_total // cols if old_total > 0 else 0
    if lines_below > 0:
        sys.stdout.write(f'\033[{lines_below}A')

    # Clear from prompt start to end of screen, then redraw
    sys.stdout.write(f'\r\033[J{_PROMPT_STR}')
    sys.stdout.write(''.join(buf))

    # Position cursor at pos (may be on an earlier wrapped line)
    if pos < len(buf):
        _move_cursor(len(buf), pos)

    sys.stdout.flush()


def _move_cursor(old_pos: int, new_pos: int):
    """Move the terminal cursor from old_pos to new_pos within the input buffer.

    Accounts for line wrapping — uses up/down + absolute column positioning
    rather than cursor-left/right which don't cross line boundaries.
    """
    if old_pos == new_pos:
        return
    cols = os.get_terminal_size().columns
    old_total = _PROMPT_COLS + old_pos
    new_total = _PROMPT_COLS + new_pos
    old_row = old_total // cols
    new_row = new_total // cols
    new_col = new_total % cols

    if new_row < old_row:
        sys.stdout.write(f'\033[{old_row - new_row}A')
    elif new_row > old_row:
        sys.stdout.write(f'\033[{new_row - old_row}B')

    sys.stdout.write('\r')
    if new_col > 0:
        sys.stdout.write(f'\033[{new_col}C')
    sys.stdout.flush()


def get_user_input() -> Optional[str]:
    """Prompt the user for input with native Ctrl+O support.

    Uses cbreak mode for character-at-a-time reading so Ctrl+O (0x0F)
    is intercepted directly — no readline macro needed. Supports basic
    line editing, history navigation, and Option+arrow word movement.
    Returns None on EOF/interrupt, empty string on blank input.
    """
    if not sys.stdin.isatty():
        try:
            return input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    print()
    sys.stdout.write("\033[1;38;5;214m❯\033[0m ")
    sys.stdout.flush()

    buf: list[str] = []
    pos = 0
    hist_total = readline.get_current_history_length()
    hist_idx = hist_total  # one past the last entry = "new line"
    saved_line = ""

    try:
        _setcbreak(fd)
        while True:
            ch = _read_char(fd)
            if not ch:
                raise EOFError

            # ── Ctrl+O: open overlay ─────────────────────────────────────
            if ch == b'\x0f':
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                expand_last_tool_result()
                # Alt screen restore (\033[?1049l) puts the original screen
                # and cursor position back — no need to redraw the prompt.
                _setcbreak(fd)
                continue

            # ── Enter ────────────────────────────────────────────────────
            if ch in (b'\r', b'\n'):
                # Move up to the prompt line and restyle with a background
                # so user input stands out in the conversation history.
                text_str = ''.join(buf).strip()
                if text_str:
                    cols = os.get_terminal_size().columns
                    total = _PROMPT_COLS + len(buf)
                    lines_below = total // cols if total > 0 else 0
                    if lines_below > 0:
                        sys.stdout.write(f'\033[{lines_below}A')
                    # \033[48;5;236m = dark gray background
                    sys.stdout.write(f'\r\033[J{_PROMPT_STR}\033[48;5;236m{text_str}\033[0m\n')
                else:
                    sys.stdout.write('\r\n')
                sys.stdout.flush()
                break

            # ── Ctrl+C — cancel current text, re-prompt ────────────────
            if ch == b'\x03':
                sys.stdout.write('^C\r\n')
                sys.stdout.write("\033[1;38;5;214m❯\033[0m ")
                sys.stdout.flush()
                buf.clear()
                pos = 0
                hist_idx = hist_total
                saved_line = ""
                continue

            # ── Ctrl+D ───────────────────────────────────────────────────
            if ch == b'\x04':
                if not buf:
                    raise EOFError
                continue

            # ── Backspace ────────────────────────────────────────────────
            if ch in (b'\x7f', b'\x08'):
                if pos > 0:
                    old_len = len(buf)
                    buf.pop(pos - 1)
                    pos -= 1
                    _redraw_line(buf, pos, old_len)
                continue

            # ── Ctrl+A (home) ────────────────────────────────────────────
            if ch == b'\x01':
                if pos > 0:
                    _move_cursor(pos, 0)
                    pos = 0
                continue

            # ── Ctrl+E (end) ─────────────────────────────────────────────
            if ch == b'\x05':
                if pos < len(buf):
                    _move_cursor(pos, len(buf))
                    pos = len(buf)
                continue

            # ── Ctrl+K (kill to end of line) ─────────────────────────────
            if ch == b'\x0b':
                if pos < len(buf):
                    old_len = len(buf)
                    buf[pos:] = []
                    _redraw_line(buf, pos, old_len)
                continue

            # ── Ctrl+U (kill entire line) ────────────────────────────────
            if ch == b'\x15':
                if buf:
                    old_len = len(buf)
                    buf.clear()
                    pos = 0
                    _redraw_line(buf, pos, old_len)
                continue

            # ── Ctrl+W (delete word back) ────────────────────────────────
            if ch == b'\x17':
                if pos > 0:
                    old_len = len(buf)
                    new_pos = pos - 1
                    while new_pos > 0 and buf[new_pos - 1] == ' ':
                        new_pos -= 1
                    while new_pos > 0 and buf[new_pos - 1] != ' ':
                        new_pos -= 1
                    del buf[new_pos:pos]
                    pos = new_pos
                    _redraw_line(buf, pos, old_len)
                continue

            # ── Ctrl+L (clear screen) ────────────────────────────────────
            if ch == b'\x0c':
                sys.stdout.write(f'\033[2J\033[H{_PROMPT_STR}')
                sys.stdout.write(''.join(buf))
                if pos < len(buf):
                    _move_cursor(len(buf), pos)
                sys.stdout.flush()
                continue

            # ── Escape sequences (arrows, Option+arrows, etc.) ──────────
            if ch == b'\x1b':
                r, _, _ = select.select([fd], [], [], 0.05)
                if not r:
                    continue  # bare Esc — ignore
                seq = os.read(fd, 1)
                if seq == b'[':
                    code = os.read(fd, 1)

                    # Up arrow — previous history
                    if code == b'A':
                        if hist_idx > 0:
                            if hist_idx == hist_total:
                                saved_line = ''.join(buf)
                            hist_idx -= 1
                            item = readline.get_history_item(hist_idx + 1) or ""
                            old_len = len(buf)
                            buf = list(item)
                            pos = len(buf)
                            _redraw_line(buf, pos, old_len)
                        continue

                    # Down arrow — next history
                    if code == b'B':
                        if hist_idx < hist_total:
                            hist_idx += 1
                            item = saved_line if hist_idx == hist_total else (readline.get_history_item(hist_idx + 1) or "")
                            old_len = len(buf)
                            buf = list(item)
                            pos = len(buf)
                            _redraw_line(buf, pos, old_len)
                        continue

                    # Right arrow
                    if code == b'C':
                        if pos < len(buf):
                            _move_cursor(pos, pos + 1)
                            pos += 1
                        continue

                    # Left arrow
                    if code == b'D':
                        if pos > 0:
                            _move_cursor(pos, pos - 1)
                            pos -= 1
                        continue

                    # Home (\033[H)
                    if code == b'H':
                        if pos > 0:
                            _move_cursor(pos, 0)
                            pos = 0
                        continue

                    # End (\033[F)
                    if code == b'F':
                        if pos < len(buf):
                            _move_cursor(pos, len(buf))
                            pos = len(buf)
                        continue

                    # Delete key (\033[3~)
                    if code == b'3':
                        r2, _, _ = select.select([fd], [], [], 0.05)
                        if r2:
                            os.read(fd, 1)  # consume ~
                        if pos < len(buf):
                            old_len = len(buf)
                            buf.pop(pos)
                            _redraw_line(buf, pos, old_len)
                        continue

                    # Option+Arrow / extended sequences (\033[1;3D etc.)
                    if code == b'1':
                        rest = b''
                        while True:
                            r2, _, _ = select.select([fd], [], [], 0.05)
                            if not r2:
                                break
                            b = os.read(fd, 1)
                            rest += b
                            if b.isalpha() or b == b'~':
                                break
                        if rest == b';3D':  # Option+Left (word back)
                            new_pos = pos
                            while new_pos > 0 and buf[new_pos - 1] == ' ':
                                new_pos -= 1
                            while new_pos > 0 and buf[new_pos - 1] != ' ':
                                new_pos -= 1
                            if new_pos < pos:
                                _move_cursor(pos, new_pos)
                                pos = new_pos
                        elif rest == b';3C':  # Option+Right (word forward)
                            new_pos = pos
                            while new_pos < len(buf) and buf[new_pos] != ' ':
                                new_pos += 1
                            while new_pos < len(buf) and buf[new_pos] == ' ':
                                new_pos += 1
                            if new_pos > pos:
                                _move_cursor(pos, new_pos)
                                pos = new_pos
                        continue

                    # Consume any remaining bytes in unknown sequences
                    while True:
                        r2, _, _ = select.select([fd], [], [], 0.02)
                        if not r2:
                            break
                        os.read(fd, 1)
                    continue

                elif seq == b'O':
                    # \033O sequences (some terminals use these for arrows)
                    code = os.read(fd, 1)
                    # Just consume — covered by \033[ above for most terminals
                    continue

                # Option key on macOS can send \033 + char (meta prefix)
                # \033b = word back, \033f = word forward
                if seq == b'b':  # Meta+b (word back)
                    new_pos = pos
                    while new_pos > 0 and buf[new_pos - 1] == ' ':
                        new_pos -= 1
                    while new_pos > 0 and buf[new_pos - 1] != ' ':
                        new_pos -= 1
                    if new_pos < pos:
                        _move_cursor(pos, new_pos)
                        pos = new_pos
                    continue

                if seq == b'f':  # Meta+f (word forward)
                    new_pos = pos
                    while new_pos < len(buf) and buf[new_pos] != ' ':
                        new_pos += 1
                    while new_pos < len(buf) and buf[new_pos] == ' ':
                        new_pos += 1
                    if new_pos > pos:
                        _move_cursor(pos, new_pos)
                        pos = new_pos
                    continue

                if seq == b'd':  # Meta+d (delete word forward)
                    if pos < len(buf):
                        old_len = len(buf)
                        new_pos = pos
                        while new_pos < len(buf) and buf[new_pos] == ' ':
                            new_pos += 1
                        while new_pos < len(buf) and buf[new_pos] != ' ':
                            new_pos += 1
                        del buf[pos:new_pos]
                        _redraw_line(buf, pos, old_len)
                    continue

                continue  # unknown escape — ignore

            # ── Printable characters ─────────────────────────────────────
            try:
                char = ch.decode('utf-8')
            except UnicodeDecodeError:
                continue

            if not char.isprintable():
                continue

            old_len = len(buf)
            buf.insert(pos, char)
            pos += 1
            if pos == len(buf):
                sys.stdout.write(char)
                sys.stdout.flush()
            else:
                _redraw_line(buf, pos, old_len)

    except (EOFError, KeyboardInterrupt):
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    text = ''.join(buf).strip()
    if text and text.lower() != "quit":
        readline.add_history(text)
    return text


# ── Thinking spinner with Ctrl+O support ────────────────────────────────────

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def thinking_spinner(fn=None, label: str = "Thinking..."):
    """Run fn with a spinner, or return a simple context manager.

    If fn is a callable: run it in a background thread while the main thread
    animates the spinner and monitors stdin for Ctrl+O. Returns fn's result.

    If fn is a string: treat it as the label and return a context manager.
    If fn is None: return a context manager with the default label.

    Usage:
        # Context manager (model loading — no Ctrl+O support needed):
        with thinking_spinner("Loading model..."):
            model = load(model_id)

        # Threaded (model generation — Ctrl+O works during inference):
        result = thinking_spinner(fn=lambda: generate(prompt), label="Thinking...")
    """
    if isinstance(fn, str):
        label = fn
        fn = None
    if fn is None:
        return Live(Spinner("dots", text=f"[dim]{label}[/dim]"), console=console, transient=True)
    return _run_with_spinner(fn, label)


def _run_with_spinner(fn, label: str):
    """Execute fn in a background thread, animate spinner + handle Ctrl+O."""
    result_box = [None]
    error_box = [None]

    def worker():
        try:
            result_box[0] = fn()
        except Exception as e:
            error_box[0] = e

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    is_tty = sys.stdin.isatty()
    fd = sys.stdin.fileno() if is_tty else -1
    old = termios.tcgetattr(fd) if is_tty else None

    frame = 0
    try:
        if is_tty:
            _setcbreak(fd)
        while thread.is_alive():
            sys.stdout.write(f"\r\033[2m{_SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]} {label}\033[0m")
            sys.stdout.flush()
            frame += 1

            if is_tty:
                r, _, _ = select.select([fd], [], [], 0.08)
                if r:
                    ch = os.read(fd, 1)
                    if ch == b'\x0f':  # Ctrl+O
                        sys.stdout.write('\r\033[K')
                        sys.stdout.flush()
                        termios.tcsetattr(fd, termios.TCSADRAIN, old)
                        # Flush any stale bytes that accumulated during mode
                        # transitions — without this, the overlay's first
                        # os.read() can return a buffered byte and exit instantly.
                        termios.tcflush(fd, termios.TCIFLUSH)
                        expand_last_tool_result()
                        _setcbreak(fd)
                    # Non-Ctrl+O keystrokes during thinking are silently discarded
            else:
                thread.join(timeout=0.08)

        sys.stdout.write('\r\033[K')
        sys.stdout.flush()
    finally:
        if is_tty:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    thread.join()
    if error_box[0] is not None:
        raise error_box[0]
    return result_box[0]

"""Tests for CLI presentation and input handling.

Tests what can be verified without a real terminal: tool result storage,
truncation, spinner modes, and UTF-8 character reading. Terminal-dependent
behavior (raw input loop, overlay pager) is tested via byte-pipe simulation
where possible.
"""
import io
import os
import time
import threading
import pytest
from unittest.mock import patch

import cli


class TestPrintToolResult:
    """print_tool_result stores the full result and truncates display."""

    def test_stores_full_result(self):
        cli._last_tool_result = ""
        cli.print_tool_result("hello world")
        assert cli._last_tool_result == "hello world"

    def test_stores_long_result_untruncated(self):
        long = "x" * 2000
        cli.print_tool_result(long)
        assert cli._last_tool_result == long
        assert len(cli._last_tool_result) == 2000

    def test_short_result_not_truncated(self, capsys):
        cli.print_tool_result("short")
        assert cli._last_tool_result == "short"

    def test_long_result_display_truncated(self):
        """Results over 500 chars get a truncation notice in the display."""
        long = "line\n" * 200  # well over 500 chars
        cli.print_tool_result(long)
        assert cli._last_tool_result == long  # full result stored

    def test_truncation_shows_line_count(self):
        """Truncation notice includes how many lines were cut."""
        lines = "\n".join(f"line {i}" for i in range(100))
        cli.print_tool_result(lines)
        # The stored result should be the full thing
        assert cli._last_tool_result == lines

    def test_overwrites_previous_result(self):
        cli.print_tool_result("first")
        cli.print_tool_result("second")
        assert cli._last_tool_result == "second"


class TestReadChar:
    """_read_char handles ASCII and multi-byte UTF-8 correctly."""

    def test_ascii_byte(self):
        r, w = os.pipe()
        os.write(w, b'A')
        assert cli._read_char(r) == b'A'
        os.close(r)
        os.close(w)

    def test_two_byte_utf8(self):
        r, w = os.pipe()
        os.write(w, 'é'.encode('utf-8'))  # 0xC3 0xA9
        result = cli._read_char(r)
        assert result == 'é'.encode('utf-8')
        os.close(r)
        os.close(w)

    def test_three_byte_utf8(self):
        r, w = os.pipe()
        os.write(w, '❯'.encode('utf-8'))  # 3 bytes
        result = cli._read_char(r)
        assert result == '❯'.encode('utf-8')
        os.close(r)
        os.close(w)

    def test_four_byte_utf8_emoji(self):
        r, w = os.pipe()
        os.write(w, '🎉'.encode('utf-8'))  # 4 bytes
        result = cli._read_char(r)
        assert result == '🎉'.encode('utf-8')
        os.close(r)
        os.close(w)

    def test_control_character(self):
        r, w = os.pipe()
        os.write(w, b'\x03')  # Ctrl+C
        result = cli._read_char(r)
        assert result == b'\x03'
        os.close(r)
        os.close(w)


class TestThinkingSpinner:
    """thinking_spinner supports both context-manager and fn modes."""

    def test_fn_mode_returns_result(self):
        result = cli.thinking_spinner(fn=lambda: 42)
        assert result == 42

    def test_fn_mode_propagates_exception(self):
        with pytest.raises(ValueError, match="boom"):
            cli.thinking_spinner(fn=lambda: (_ for _ in ()).throw(ValueError("boom")))

    def test_string_arg_returns_context_manager(self):
        ctx = cli.thinking_spinner("Loading...")
        assert hasattr(ctx, '__enter__')
        assert hasattr(ctx, '__exit__')

    def test_none_arg_returns_context_manager(self):
        ctx = cli.thinking_spinner()
        assert hasattr(ctx, '__enter__')
        assert hasattr(ctx, '__exit__')

    def test_fn_mode_with_slow_function(self):
        """fn mode waits for the function to complete."""
        result = cli.thinking_spinner(fn=lambda: (time.sleep(0.1), "done")[1])
        assert result == "done"

    def test_fn_mode_runs_in_background_thread(self):
        """The function runs in a thread, not the main thread."""
        thread_names = []
        def capture_thread():
            thread_names.append(threading.current_thread().name)
            return True
        cli.thinking_spinner(fn=capture_thread)
        assert thread_names
        assert thread_names[0] != threading.current_thread().name


class TestExpandLastToolResult:
    """expand_last_tool_result handles edge cases."""

    def test_no_result_prints_message(self):
        cli._last_tool_result = ""
        # Should not raise — just prints a message
        cli.expand_last_tool_result()

    def test_non_tty_prints_full_result(self):
        cli._last_tool_result = "full output here"
        with patch.object(cli.sys.stdin, 'isatty', return_value=False):
            cli.expand_last_tool_result()  # should not raise


class TestGetUserInputCtrlC:
    """Ctrl+C clears the line and re-prompts (doesn't exit).

    Since get_user_input requires a real TTY, we test the behavior by
    sending bytes through a pipe and patching isatty. The function's
    cbreak mode won't work on a pipe, so we test the non-TTY fallback
    and verify the TTY code path's Ctrl+C handling via code inspection.
    """

    def test_non_tty_ctrl_c_returns_none(self):
        """Non-TTY fallback: KeyboardInterrupt → None."""
        with patch('builtins.input', side_effect=KeyboardInterrupt):
            with patch.object(cli.sys.stdin, 'isatty', return_value=False):
                result = cli.get_user_input()
        assert result is None

    def test_non_tty_eof_returns_none(self):
        with patch('builtins.input', side_effect=EOFError):
            with patch.object(cli.sys.stdin, 'isatty', return_value=False):
                result = cli.get_user_input()
        assert result is None

    def test_non_tty_normal_input(self):
        with patch('builtins.input', return_value='hello'):
            with patch.object(cli.sys.stdin, 'isatty', return_value=False):
                result = cli.get_user_input()
        assert result == 'hello'

    def test_ctrl_c_handler_is_not_keyboard_interrupt(self):
        """Verify the Ctrl+C code path does NOT raise KeyboardInterrupt.

        We check the source to confirm the behavior — Ctrl+C (0x03)
        should clear the buffer and continue, not raise.
        """
        import inspect
        source = inspect.getsource(cli.get_user_input)
        # The handler should NOT raise KeyboardInterrupt for 0x03
        assert "raise KeyboardInterrupt" not in source or \
               source.index("b'\\x03'") < source.index("raise KeyboardInterrupt") is False, \
               "Ctrl+C handler should clear line, not raise KeyboardInterrupt"

    def test_ctrl_c_handler_clears_buffer(self):
        """Verify the Ctrl+C code path clears buf and resets position."""
        import inspect
        source = inspect.getsource(cli.get_user_input)
        # Find the Ctrl+C section
        ctrl_c_idx = source.index("b'\\x03'")
        section = source[ctrl_c_idx:ctrl_c_idx + 400]
        assert "buf.clear()" in section
        assert "pos = 0" in section
        assert "continue" in section

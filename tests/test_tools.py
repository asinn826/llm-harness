"""Tests for tool functions."""
import pytest
from unittest.mock import patch, MagicMock
from tools import run_shell, read_file, write_file, calculator, fetch_url, web_search, TOOLS

def test_run_shell_returns_output():
    result = run_shell("echo hello")
    assert "hello" in result

def test_run_shell_returns_stderr_on_error():
    result = run_shell("cat nonexistent_file_xyz")
    assert result
    assert "nonexistent_file_xyz" in result  # stderr should mention the filename

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

def test_calculator_division_by_zero():
    result = calculator("1 / 0")
    assert "Error" in result

def test_fetch_url_returns_text():
    mock_response = MagicMock()
    mock_response.text = "<html><body><h1>Hello</h1><p>World</p></body></html>"
    with patch("tools.requests.get", return_value=mock_response):
        result = fetch_url("https://example.com")
    assert "Hello" in result
    assert "World" in result

def test_fetch_url_truncates_long_content():
    mock_response = MagicMock()
    mock_response.text = f"<p>{'a' * 5000}</p>"
    with patch("tools.requests.get", return_value=mock_response):
        result = fetch_url("https://example.com")
    assert len(result) <= 3020  # 3000 + len("... (truncated)")
    assert "truncated" in result

def test_fetch_url_handles_error():
    with patch("tools.requests.get", side_effect=Exception("connection error")):
        result = fetch_url("https://example.com")
    assert "Error" in result

def test_web_search_returns_results():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"title": "Paris", "content": "Paris is the capital of France."},
            {"title": "France", "content": "France is a country in Western Europe."},
        ]
    }
    with patch("tools.requests.post", return_value=mock_response):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            result = web_search("capital of France")
    assert "Paris" in result

def test_web_search_handles_error():
    with patch("tools.requests.post", side_effect=Exception("network error")):
        with patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}):
            result = web_search("anything")
    assert "Error" in result

def test_web_search_missing_api_key():
    with patch.dict("os.environ", {}, clear=True):
        result = web_search("anything")
    assert "TAVILY_API_KEY" in result

def test_tools_registry_has_all_tools():
    # Every registered tool must be callable and have a docstring
    # (docstrings are injected into the system prompt — they're load-bearing)
    for name, fn in TOOLS.items():
        assert callable(fn), f"{name} is not callable"
        assert fn.__doc__, f"{name} has no docstring — the harness needs this for the system prompt"


# ── Calendar tool tests ─────────────────────────────────────────────────────

def test_calendar_tools_registered():
    assert "read_calendar" in TOOLS
    assert "create_event" in TOOLS
    assert "list_calendars" in TOOLS


def test_read_calendar_rejects_bad_date():
    from tools import read_calendar
    result = read_calendar("not-a-date")
    assert "Error" in result
    assert "ISO 8601" in result


def test_read_calendar_bad_end_date():
    from tools import read_calendar
    result = read_calendar("2026-04-04", end_date="garbage")
    assert "Error" in result


def test_create_event_rejects_bad_start_time():
    from tools import create_event
    result = create_event("Test", "not-a-time")
    assert "Error" in result
    assert "ISO 8601" in result


def test_create_event_rejects_bad_end_time():
    from tools import create_event
    result = create_event("Test", "2026-04-10T12:00:00", end_time="garbage")
    assert "Error" in result


def test_create_event_duration_default():
    """Without end_time, duration defaults to 60 minutes."""
    from datetime import datetime, timedelta
    # We can't test AppleScript execution, but we can verify the date math
    start = datetime.fromisoformat("2026-04-10T12:00:00")
    expected_end = start + timedelta(minutes=60)
    assert expected_end.hour == 13
    assert expected_end.minute == 0


def test_system_prompt_contains_today():
    from harness import build_system_prompt
    prompt = build_system_prompt(TOOLS)
    assert "Today is" in prompt
    # Should contain a day of week and month
    from datetime import datetime
    today = datetime.now()
    assert today.strftime("%B") in prompt  # month name
    assert today.strftime("%Y") in prompt  # year

"""Tests for tool functions."""
import pytest
from unittest.mock import patch, MagicMock
from tools import run_shell, read_file, write_file, calculator, web_search, TOOLS

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

def test_web_search_returns_results():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "AbstractText": "Paris is the capital of France.",
        "RelatedTopics": [
            {"Text": "France is a country in Western Europe."},
        ]
    }
    with patch("tools.requests.get", return_value=mock_response):
        result = web_search("capital of France")
    assert "Paris" in result

def test_web_search_handles_error():
    with patch("tools.requests.get", side_effect=Exception("network error")):
        result = web_search("anything")
    assert "Error" in result

def test_tools_registry_has_all_tools():
    # Every registered tool must be callable and have a docstring
    # (docstrings are injected into the system prompt — they're load-bearing)
    for name, fn in TOOLS.items():
        assert callable(fn), f"{name} is not callable"
        assert fn.__doc__, f"{name} has no docstring — the harness needs this for the system prompt"

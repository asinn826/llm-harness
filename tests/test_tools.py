"""Tests for tool functions."""
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

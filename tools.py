"""Tools available to the LLM harness.

Each tool is a plain Python function. The harness reads the docstring to build
the system prompt — so docstrings are load-bearing. Keep them accurate.

To add a new tool:
  1. Define a function with a clear docstring describing args and behavior
  2. Add it to the TOOLS dict at the bottom of this file
  That's it.
"""
import subprocess
import requests


def run_shell(command: str) -> str:
    """Run a shell command and return stdout+stderr. Args: command (str)."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    return (result.stdout + result.stderr).strip() or "(no output)"


def read_file(path: str) -> str:
    """Read a file and return its contents. Args: path (str)."""
    try:
        return open(path).read()
    except Exception as e:
        return f"Error: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to a file. Args: path (str), content (str)."""
    try:
        with open(path, "w") as f:
            f.write(content)
        return "OK"
    except Exception as e:
        return f"Error: {e}"


def calculator(expression: str) -> str:
    """Evaluate a math expression. Args: expression (str)."""
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        return "Error: only basic math expressions allowed"
    try:
        return str(eval(expression))
    except Exception as e:
        return f"Error: {e}"


def web_search(query: str) -> str:
    """Search the web using DuckDuckGo and return results. Args: query (str)."""
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_redirect": 1},
            timeout=10,
        )
        data = resp.json()
        results = []
        if data.get("AbstractText"):
            results.append(data["AbstractText"])
        for r in data.get("RelatedTopics", [])[:3]:
            if isinstance(r, dict) and r.get("Text"):
                results.append(r["Text"])
        return "\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Error: {e}"


# Registry: add new tools here. The harness reads this dict to build the system prompt.
TOOLS = {
    "run_shell": run_shell,
    "read_file": read_file,
    "write_file": write_file,
    "calculator": calculator,
    "web_search": web_search,
}

"""Tools available to the LLM harness.

Each tool is a plain Python function. The harness reads the docstring to build
the system prompt — so docstrings are load-bearing. Keep them accurate.

To add a new tool:
  1. Define a function with a clear docstring describing args and behavior
  2. Add it to the TOOLS dict at the bottom of this file
  That's it.
"""
import ast
import os
import subprocess
import html2text
import requests


def run_shell(command: str) -> str:
    """Run a shell command and return stdout+stderr. Args: command (str). Returns: stdout+stderr as a single string, or "(no output)" if empty."""
    # shell=True passes the command directly to the shell — intentional for flexibility,
    # but means a malicious or confused model could run arbitrary commands. In production,
    # you'd want a command allowlist or a sandboxed environment.
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    return (result.stdout + result.stderr).strip() or "(no output)"


def read_file(path: str) -> str:
    """Read a file and return its contents. Args: path (str). Returns: file contents as a string, or "Error: <message>" on failure."""
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        return f"Error: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to a file. Args: path (str), content (str). Returns: "OK" on success, or "Error: <message>" on failure."""
    try:
        with open(path, "w") as f:
            f.write(content)
        return "OK"
    except Exception as e:
        return f"Error: {e}"


def calculator(expression: str) -> str:
    """Evaluate a math expression safely using AST validation. Args: expression (str). Returns: result as a string, or "Error: <message>" on failure."""
    # Validate the AST before eval — only allow number literals and basic operators.
    # This is safer than a character allowlist, and shows how to think about eval safety.
    SAFE_NODES = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
        ast.FloorDiv, ast.UAdd, ast.USub,
    )
    try:
        tree = ast.parse(expression, mode="eval")
        if not all(isinstance(node, SAFE_NODES) for node in ast.walk(tree)):
            return "Error: only basic math expressions allowed"
        return str(eval(compile(tree, "<string>", "eval")))
    except Exception as e:
        return f"Error: {e}"


def send_imessage(contact: str, message: str, area_code: str = "", label: str = "") -> str:
    """Send a text message to a contact by name using the macOS Messages app. Args: contact (str) - full name as it appears in Contacts (e.g. "Millie Wu"), message (str) - the message text to send, area_code (str, optional) - filter to a phone number with this area code (e.g. "929"), label (str, optional) - filter by phone label such as "mobile", "home", "work", "iPhone" (case-insensitive). Both filters can be combined. Returns: "OK" on success or "Error: <message>" on failure."""
    # AppleScript doesn't support backslash escaping in strings, so we pass
    # the message via an environment variable and read it with do shell script.
    if area_code or label:
        area_code_check = f'''
            set cleanPhone to ""
            repeat with c in characters of phoneVal
                if c is in "0123456789" then set cleanPhone to cleanPhone & c
            end repeat
            if (length of cleanPhone > 10) and cleanPhone starts with "1" then
                set cleanPhone to text 2 thru -1 of cleanPhone
            end if
            if not (cleanPhone starts with "{area_code}") then set matches to false''' if area_code else ""

        label_check = f'''
            ignoring case
                if phoneLabel does not contain "{label}" then set matches to false
            end ignoring''' if label else ""

        filter_desc = " and ".join(filter(None, [
            f"area code {area_code}" if area_code else "",
            f'label "{label}"' if label else "",
        ]))

        phone_selection = f'''
    set thePhone to ""
    repeat with p in phones of thePerson
        set phoneVal to (value of p) as text
        set phoneLabel to (label of p) as text
        set matches to true
        {area_code_check}
        {label_check}
        if matches then
            set thePhone to phoneVal
            exit repeat
        end if
    end repeat
    if thePhone is "" then error "No phone number matching {filter_desc} found for \\"{contact}\\""'''
    else:
        phone_selection = '''
    if (count of phones of thePerson) is 0 then error "Contact has no phone number"
    set thePhone to value of item 1 of phones of thePerson'''

    script = f'''
tell application "Contacts"
    set matchingPeople to (every person whose name contains "{contact}")
    if (count of matchingPeople) is 0 then
        error "No contact named \\"{contact}\\" found"
    end if
    set thePerson to item 1 of matchingPeople{phone_selection}
end tell
set theMsg to do shell script "echo $MSG"
tell application "Messages"
    try
        set theService to 1st service whose service type = iMessage
        send theMsg to buddy thePhone of theService
    on error
        set theService to 1st service whose service type = SMS
        send theMsg to buddy thePhone of theService
    end try
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=15,
        env={**__import__("os").environ, "MSG": message},
    )
    if result.returncode != 0:
        return f"Error: {result.stderr.strip()}"
    return "OK"


def fetch_url(url: str) -> str:
    """Fetch the content of a webpage and return it as plain text. Args: url (str). Returns: page content as plain text (truncated to 3000 chars), or "Error: <message>" on failure."""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        text = h.handle(resp.text).strip()
        return text[:3000] + "\n... (truncated)" if len(text) > 3000 else text
    except Exception as e:
        return f"Error: {e}"


def web_search(query: str) -> str:
    """Search the web using Tavily and return results. Args: query (str). Returns: newline-joined results (title + content snippet per result), "No results found.", or "Error: <message>"."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return "Error: TAVILY_API_KEY environment variable not set"
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 3},
            timeout=10,
        )
        data = resp.json()
        results = []
        for r in data.get("results", []):
            results.append(f"{r['title']}\n{r['content']}")
        return "\n\n".join(results) if results else "No results found."
    except Exception as e:
        return f"Error: {e}"


# Registry: add new tools here. The harness reads this dict to build the system prompt.
TOOLS = {
    "run_shell": run_shell,
    "read_file": read_file,
    "write_file": write_file,
    "calculator": calculator,
    "fetch_url": fetch_url,
    "web_search": web_search,
    "send_imessage": send_imessage,
}

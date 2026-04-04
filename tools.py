"""Tools available to the LLM harness.

Each tool is a plain Python function. The harness reads the docstring to build
the system prompt — so docstrings are load-bearing. Keep them accurate.

To add a new tool:
  1. Define a function with a clear docstring describing args and behavior
  2. Annotate it with @permission(Permission.READ_ONLY) or
     @permission(Permission.REQUIRES_CONFIRMATION)
  3. Add it to the TOOLS dict at the bottom of this file

Permission levels:
  READ_ONLY             — no side effects; runs automatically without asking
  REQUIRES_CONFIRMATION — has side effects (sends, writes, executes); asks first

The harness checks `fn.needs_confirmation` (set by the decorator) so it stays
decoupled from this enum — you can extend Permission without touching harness.py.
"""
import ast
import glob
import os
import sqlite3
import subprocess
from datetime import datetime
from enum import Enum
from typing import Callable, TypeVar
import html2text
import requests

F = TypeVar("F", bound=Callable)


class Permission(Enum):
    """Permission level for a tool.

    Extend this enum to add new levels (e.g. DANGEROUS, NETWORK_ONLY) as the
    permission model grows. The harness only checks `fn.needs_confirmation`, so
    new levels slot in without any harness changes — just update the decorator
    and any dispatch logic in main.py.
    """
    READ_ONLY = "read_only"
    """No side effects. Runs automatically without user confirmation."""

    REQUIRES_CONFIRMATION = "requires_confirmation"
    """Has side effects (sends messages, writes files, executes commands).
    The harness will prompt the user before running."""

    @property
    def needs_confirmation(self) -> bool:
        return self != Permission.READ_ONLY


def permission(level: Permission) -> Callable[[F], F]:
    """Decorator that attaches a Permission level to a tool function.

    Sets two attributes on the function:
      fn.permission         — the full Permission enum value (for introspection)
      fn.needs_confirmation — bool shortcut used by harness.py

    Example:
        @permission(Permission.READ_ONLY)
        def my_tool(...): ...
    """
    def decorator(fn: F) -> F:
        fn.permission = level
        fn.needs_confirmation = level.needs_confirmation
        return fn
    return decorator


@permission(Permission.REQUIRES_CONFIRMATION)
def run_shell(command: str) -> str:
    """Run a shell command and return stdout+stderr. Args: command (str). Returns: stdout+stderr as a single string, or "(no output)" if empty."""
    # shell=True passes the command directly to the shell — intentional for flexibility,
    # but means a malicious or confused model could run arbitrary commands. In production,
    # you'd want a command allowlist or a sandboxed environment.
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    return (result.stdout + result.stderr).strip() or "(no output)"


@permission(Permission.READ_ONLY)
def read_file(path: str) -> str:
    """Read a file and return its contents. Args: path (str). Returns: file contents as a string, or "Error: <message>" on failure."""
    try:
        with open(path) as f:
            return f.read()
    except Exception as e:
        return f"Error: {e}"


@permission(Permission.REQUIRES_CONFIRMATION)
def write_file(path: str, content: str) -> str:
    """Write content to a file. Args: path (str), content (str). Returns: "OK" on success, or "Error: <message>" on failure."""
    try:
        with open(path, "w") as f:
            f.write(content)
        return "OK"
    except Exception as e:
        return f"Error: {e}"


@permission(Permission.READ_ONLY)
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


def _last10(phone: str) -> str:
    """Return the last 10 digits of a phone number string."""
    digits = ''.join(c for c in phone if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


@permission(Permission.READ_ONLY)
def read_imessages(contact: str, limit: int = 10, received_only: bool = False) -> str:
    """Read recent iMessages. Args: contact (str) - contact name as it appears in Contacts; pass empty string "" to get most recent messages across all conversations, limit (int, optional) - number of recent messages to return (default 10), received_only (bool, optional) - if true, only return messages received from others (not sent by you). Returns: formatted message history or an error with setup instructions."""
    APPLE_EPOCH = 978307200  # seconds between Unix epoch (1970) and Apple epoch (2001)
    db_path = os.path.expanduser("~/Library/Messages/chat.db")

    if not os.access(db_path, os.R_OK):
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])
        return (
            "Full Disk Access is required to read iMessages — System Settings has been opened for you.\n\n"
            "Why we're asking: iMessages are stored in ~/Library/Messages/chat.db, "
            "a file macOS protects for your privacy. This tool only reads from that file — "
            "it never writes to, modifies, or shares your messages.\n\n"
            "To grant access:\n"
            "  1. Enable access for Terminal in the Full Disk Access list\n"
            "  2. Try your request again\n\n"
            "You can revoke this permission at any time from the same settings screen."
        )

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as e:
        return f"Error opening messages database: {e}"

    def decode_message_text(text, attributed_body):
        if text:
            return text
        if not attributed_body:
            return None
        # attributedBody is a typedstream (NeXT legacy binary format).
        # The message text is stored as +<length_byte><utf8_data> between
        # the NSString and NSDictionary class markers.
        try:
            start = attributed_body.find(b'NSString')
            end = attributed_body.find(b'NSDictionary')
            if start == -1 or end == -1 or end <= start:
                return None
            chunk = attributed_body[start + 8:end]
            plus_pos = chunk.find(b'+')
            if plus_pos == -1 or plus_pos + 1 >= len(chunk):
                return None
            length = chunk[plus_pos + 1]
            text_start = plus_pos + 2
            return chunk[text_start:text_start + length].decode('utf-8', errors='replace')
        except Exception:
            return None

    try:
        cursor = conn.cursor()

        if not contact:
            # No contact specified — return most recent messages across all conversations,
            # with the chat_identifier as the sender label for received messages.
            received_filter = "AND m.is_from_me = 0" if received_only else ""
            cursor.execute(f"""
                SELECT DISTINCT m.text, m.attributedBody, m.is_from_me, m.date,
                       c.display_name, c.chat_identifier, h.id AS sender_handle
                FROM message m
                JOIN chat_message_join cmj ON m.rowid = cmj.message_id
                JOIN chat c ON cmj.chat_id = c.rowid
                LEFT JOIN handle h ON m.handle_id = h.rowid
                WHERE 1=1 {received_filter}
                ORDER BY m.date DESC LIMIT ?
            """, [limit])
            rows = cursor.fetchall()
            if not rows:
                return "No messages found."

            # Reverse-resolve sender phone numbers to contact names by querying
            # the AddressBook SQLite databases directly — much faster than AppleScript.
            name_map = {}
            ab_dbs = glob.glob(os.path.expanduser(
                "~/Library/Application Support/AddressBook/Sources/*/AddressBook-v*.abcddb"
            ))
            for ab_path in ab_dbs:
                try:
                    ab = sqlite3.connect(f"file:{ab_path}?mode=ro", uri=True)
                    ab_cur = ab.cursor()
                    ab_cur.execute("""
                        SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZORGANIZATION, p.ZFULLNUMBER
                        FROM ZABCDPHONENUMBER p
                        JOIN ZABCDRECORD r ON p.ZOWNER = r.Z_PK
                        WHERE p.ZFULLNUMBER IS NOT NULL
                    """)
                    for first, last, org, phone in ab_cur.fetchall():
                        d = _last10(phone)
                        if d and d not in name_map:
                            name = " ".join(filter(None, [first, last])) or org or ""
                            if name:
                                name_map[d] = name
                    ab.close()
                except Exception:
                    pass

            # Group messages by chat_identifier so the model sees clear
            # conversation boundaries rather than a flat chronological stream.
            # This is critical for correct per-thread summarization.
            from collections import defaultdict
            threads: dict[str, list[str]] = defaultdict(list)
            thread_order: list[str] = []  # preserves first-seen order

            for text, attributed_body, is_from_me, date, display_name, chat_id, sender_handle in reversed(rows):
                body = decode_message_text(text, attributed_body)
                if not body:
                    continue
                ts = (date / 1e9 if date > 1e12 else date) + APPLE_EPOCH
                dt = datetime.fromtimestamp(ts).strftime("%b %d %H:%M")
                if is_from_me:
                    sender = "You"
                else:
                    # Use the per-message handle (correct for group chats where
                    # multiple people send messages) rather than the chat identifier.
                    handle_digits = _last10(sender_handle or "")
                    sender = name_map.get(handle_digits) or sender_handle or display_name or "Unknown"

                if chat_id not in thread_order:
                    thread_order.append(chat_id)
                threads[chat_id].append(f"  [{dt}] {sender}: {body}")

            if not threads:
                return "No readable messages found."

            # Resolve participant names for each chat via chat_handle_join.
            # A chat with >1 participant handle is a group chat — more reliable
            # than checking the chat_identifier prefix, which varies by service.
            cursor.execute("""
                SELECT c.chat_identifier, h.id
                FROM chat c
                JOIN chat_handle_join chj ON c.rowid = chj.chat_id
                JOIN handle h ON chj.handle_id = h.rowid
            """)
            chat_participants: dict[str, list[str]] = defaultdict(list)
            for cid, handle_id in cursor.fetchall():
                digits = _last10(handle_id)
                name = name_map.get(digits) or handle_id
                chat_participants[cid].append(name)

            sections = []
            for chat_id in thread_order:
                participants = chat_participants.get(chat_id, [])
                is_group = len(participants) > 1
                digits = _last10(chat_id or "")
                display_name = next(
                    (dn for _, _, _, _, dn, cid, _ in rows if cid == chat_id and dn), None
                )
                label = name_map.get(digits) or display_name or ("Group Chat" if is_group else chat_id)

                header = f"--- {'Group: ' if is_group else ''}{label} ---"
                if is_group and chat_id in chat_participants:
                    participants = ", ".join(sorted(set(chat_participants[chat_id])))
                    header += f"\nParticipants: {participants}"

                sections.append(header + "\n" + "\n".join(threads[chat_id]))

            return "\n\n".join(sections)

        # Get contact's phone numbers AND emails via Contacts.app
        script = f'''
tell application "Contacts"
    set matchingPeople to (every person whose name contains "{contact}")
    if (count of matchingPeople) is 0 then return ""
    set thePerson to item 1 of matchingPeople
    set identList to ""
    repeat with p in phones of thePerson
        set identList to identList & (value of p as text) & ","
    end repeat
    repeat with e in emails of thePerson
        set identList to identList & (value of e as text) & ","
    end repeat
    return identList
end tell
'''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        raw_identifiers = [p.strip() for p in result.stdout.strip().split(",") if p.strip()]

        phone_digits = [_last10(p) for p in raw_identifiers if any(c.isdigit() for c in p)]
        emails = [e.lower() for e in raw_identifiers if '@' in e]

        if not phone_digits and not emails:
            phone_digits = [_last10(contact)]

        cursor.execute("SELECT rowid, id FROM handle")
        all_handles = cursor.fetchall()
        matching_handle_ids = [
            rowid for rowid, hid in all_handles
            if any(_last10(hid) == d for d in phone_digits)
            or hid.lower() in emails
        ]

        if not matching_handle_ids:
            return f"No messages found for {contact}."

        # Match via chat.chat_identifier (set to phone/email for 1:1 chats),
        # then pull all messages in those chats — captures both sent and received.
        cursor.execute("SELECT rowid, chat_identifier FROM chat")
        matching_chat_ids = [
            rowid for rowid, chat_id in cursor.fetchall()
            if chat_id and (
                any(_last10(chat_id) == d for d in phone_digits)
                or chat_id.lower() in emails
            )
        ]

        if not matching_chat_ids:
            return f"No messages found for {contact}. (handles checked: {len(matching_handle_ids)}, chats checked: 0)"

        received_filter = "AND m.is_from_me = 0" if received_only else ""
        placeholders = ','.join('?' * len(matching_chat_ids))
        cursor.execute(f"""
            SELECT DISTINCT m.text, m.attributedBody, m.is_from_me, m.date
            FROM message m
            JOIN chat_message_join cmj ON m.rowid = cmj.message_id
            WHERE cmj.chat_id IN ({placeholders}) {received_filter}
            ORDER BY m.date DESC LIMIT ?
        """, matching_chat_ids + [limit])

        rows = cursor.fetchall()
        if not rows:
            return f"No messages found for {contact}. (handles: {len(matching_handle_ids)}, chats: {len(matching_chat_ids)})"

        first_name = contact.split()[0] if contact.split() else contact
        lines = []
        for text, attributed_body, is_from_me, date in reversed(rows):
            body = decode_message_text(text, attributed_body)
            if not body:
                continue
            ts = (date / 1e9 if date > 1e12 else date) + APPLE_EPOCH
            dt = datetime.fromtimestamp(ts).strftime("%b %d %H:%M")
            sender = "You" if is_from_me else first_name
            lines.append(f"[{dt}] {sender}: {body}")

        if not lines:
            return f"No readable messages found for {contact} (messages may be attachments or reactions only)."
        return '\n'.join(lines)
    finally:
        conn.close()


@permission(Permission.READ_ONLY)
def find_gif(query: str) -> str:
    """Search Tenor for a GIF matching the query and return a URL. Args: query (str). Returns: a Tenor GIF URL that can be sent as a message (iMessage will auto-preview it), or "Error: <message>" on failure."""
    try:
        resp = requests.get(
            "https://api.tenor.com/v1/search",
            params={"q": query, "limit": 1, "media_filter": "minimal", "key": "LIVDSRZULELA"},
            timeout=10,
        )
        results = resp.json().get("results", [])
        if not results:
            return "Error: No GIFs found"
        return results[0]["url"]
    except Exception as e:
        return f"Error: {e}"


@permission(Permission.REQUIRES_CONFIRMATION)
def send_imessage(contact: str, message: str = "", area_code: str = "", label: str = "") -> str:
    """Send a text message to a contact by name using the macOS Messages app. To send a GIF, first call find_gif to get a URL, then pass it as the message — iMessage will auto-preview it. Args: contact (str) - full name as it appears in Contacts (e.g. "Millie Wu"), message (str) - the message text to send, area_code (str, optional) - filter to a phone number with this area code (e.g. "929"), label (str, optional) - filter by phone label such as "mobile", "home", "work", "iPhone" (case-insensitive). Returns: confirmation string or "Error: <message>" on failure."""
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

    # Step 1: resolve phone number from Contacts
    # `launch` reconnects AppleScript to the running instance without bringing
    # it to the foreground — prevents the -600 "Application isn't running" error
    # that can occur even when Contacts.app is open.
    lookup_script = f'''
tell application "Contacts" to launch
tell application "Contacts"
    set matchingPeople to (every person whose name contains "{contact}")
    if (count of matchingPeople) is 0 then
        error "No contact named \\"{contact}\\" found"
    end if
    set thePerson to item 1 of matchingPeople{phone_selection}
end tell
return thePhone
'''
    lookup = subprocess.run(["osascript", "-e", lookup_script], capture_output=True, text=True, timeout=10)
    if lookup.returncode != 0:
        return f"Error: {lookup.stderr.strip()}"
    raw_phone = lookup.stdout.strip()

    # Normalize to E.164
    digits = ''.join(c for c in raw_phone if c.isdigit())
    if len(digits) == 10:
        digits = '1' + digits
    e164 = '+' + digits
    last10_digits = _last10(e164)

    # Step 2: check chat.db to determine the right service for this number.
    # Messages won't raise an error when sending iMessage to a non-iMessage number —
    # it silently fails. So we look up the service from past conversations.
    # Step 2: check chat.db to determine the right service for this number.
    # A contact may have multiple handles (e.g. an iMessage email handle AND
    # an RCS/SMS phone handle). Prefer iMessage if any handle uses it.
    service_type = "iMessage"  # default
    db_path = os.path.expanduser("~/Library/Messages/chat.db")
    if os.access(db_path, os.R_OK):
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute("SELECT id, service FROM handle")
            services_found = set()
            for hid, svc in cur.fetchall():
                if _last10(hid) == last10_digits:
                    services_found.add(svc)
            conn.close()
            if services_found:
                # Prefer iMessage > SMS/RCS
                service_type = "iMessage" if "iMessage" in services_found else services_found.pop()
        except Exception:
            pass

    # Step 3: send via the determined service, with fallback to the other
    if service_type == "iMessage":
        primary, fallback = "iMessage", "SMS"
    else:
        primary, fallback = "SMS", "iMessage"

    send_script = f'''
set theMsg to do shell script "echo $MSG"
tell application "Messages"
    try
        set theService to 1st service whose service type = {primary}
        send theMsg to buddy "{e164}" of theService
    on error
        set theService to 1st service whose service type = {fallback}
        send theMsg to buddy "{e164}" of theService
    end try
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", send_script],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "MSG": message},
    )
    if result.returncode != 0:
        return f"Error: {result.stderr.strip()}"
    return f"Message sent to {contact} via {service_type}. Check Messages.app to confirm delivery."


@permission(Permission.READ_ONLY)
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


@permission(Permission.READ_ONLY)
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
    "find_gif": find_gif,
    "read_imessages": read_imessages,
    "send_imessage": send_imessage,
}

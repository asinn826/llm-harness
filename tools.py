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
from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import Callable, TypeVar
import html2text
import requests

F = TypeVar("F", bound=Callable)

APPLE_EPOCH = 978307200  # seconds between Unix epoch (1970) and Apple epoch (2001)

REACTION_LABELS = {
    2000: "loved", 2001: "liked", 2002: "disliked",
    2003: "laughed at", 2004: "emphasized", 2005: "questioned",
}


# ── Permission system ───────────────────────────────────────────────────────

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


# ── Simple tools ────────────────────────────────────────────────────────────

@permission(Permission.REQUIRES_CONFIRMATION)
def run_shell(command: str) -> str:
    """Run a shell command and return stdout+stderr. Args: command (str). Returns: stdout+stderr as a single string, or "(no output)" if empty."""
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


# ── iMessage helpers ────────────────────────────────────────────────────────

def _last10(phone: str) -> str:
    """Return the last 10 digits of a phone number string."""
    digits = ''.join(c for c in phone if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _open_messages_db():
    """Open ~/Library/Messages/chat.db read-only.

    Returns (conn, None) on success or (None, error_string) on failure.
    On permission error, opens System Settings to the Full Disk Access pane.
    """
    db_path = os.path.expanduser("~/Library/Messages/chat.db")
    if not os.access(db_path, os.R_OK):
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])
        return None, (
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
        return conn, None
    except sqlite3.OperationalError as e:
        return None, f"Error opening messages database: {e}"


def _build_name_map() -> dict[str, str]:
    """Build a phone-digits → contact-name map from the AddressBook databases.

    Reads the macOS AddressBook SQLite databases directly — much faster than
    AppleScript. Returns a dict mapping last-10-digit phone numbers to names.
    """
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
    return name_map


def _decode_message_text(text, attributed_body):
    """Extract message text from the text column or attributedBody blob.

    attributedBody is a NeXT typedstream binary format. The plain-text content
    is stored as +<length_byte><utf8_data> between the NSString and NSDictionary
    class markers.
    """
    if text:
        return text
    if not attributed_body:
        return None
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


def _format_timestamp(date) -> str:
    """Convert an iMessage date (Apple epoch, possibly nanoseconds) to 'Mon DD HH:MM'."""
    ts = (date / 1e9 if date > 1e12 else date) + APPLE_EPOCH
    return datetime.fromtimestamp(ts).strftime("%b %d %H:%M")


def _format_reaction(body: str, reaction_type, associated_guid, cursor, name_map, source_cache: dict) -> str:
    """If this message is a tapback reaction, prefix it with [reacted: ...].

    Looks up the source message via associated_message_guid so the model
    sees who sent the original and what it was, even when the original
    falls outside the query window.
    """
    if not reaction_type or reaction_type not in REACTION_LABELS:
        return body

    label = REACTION_LABELS[reaction_type]
    if not associated_guid:
        return f"[reacted: {label}] {body}"

    # associated_message_guid has format "p:N/<GUID>" or "bp:<GUID>"
    guid = associated_guid
    if '/' in guid:
        guid = guid.split('/', 1)[1]
    elif guid.startswith('bp:'):
        guid = guid[3:]

    if guid not in source_cache:
        cursor.execute("""
            SELECT m.text, m.attributedBody, m.is_from_me,
                   h.id, m.cache_has_attachments
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.rowid
            WHERE m.guid = ?
        """, [guid])
        row = cursor.fetchone()
        if not row:
            source_cache[guid] = None
        else:
            src_text, src_attr, src_from_me, src_handle, src_has_atts = row
            src_body = _decode_message_text(src_text, src_attr)
            if not src_body:
                src_body = "[image]" if src_has_atts else None
            if src_body:
                handle_digits = _last10(src_handle or "")
                src_sender = "You" if src_from_me else (name_map.get(handle_digits) or src_handle or "them")
                source_cache[guid] = f"{src_sender}: {src_body}"
            else:
                source_cache[guid] = None

    src = source_cache[guid]
    if src:
        return f"[reacted: {label} to '{src}'] {body}"
    return f"[reacted: {label}] {body}"


def _resolve_sender(is_from_me, sender_handle, name_map, display_name=None) -> str:
    """Determine the display name for a message sender."""
    if is_from_me:
        return "You"
    handle_digits = _last10(sender_handle or "")
    return name_map.get(handle_digits) or sender_handle or display_name or "Unknown"


# ── iMessage read: all conversations ────────────────────────────────────────

def _read_all_conversations(cursor, limit: int, received_only: bool) -> str:
    """Read recent messages across all conversations, grouped by thread."""
    received_filter = "AND m.is_from_me = 0" if received_only else ""
    cursor.execute(f"""
        SELECT m.text, m.attributedBody, m.is_from_me, m.date,
               c.display_name, c.chat_identifier, h.id AS sender_handle,
               m.cache_has_attachments, m.associated_message_type,
               m.associated_message_guid
        FROM message m
        JOIN chat_message_join cmj ON m.rowid = cmj.message_id
        JOIN chat c ON cmj.chat_id = c.rowid
        LEFT JOIN handle h ON m.handle_id = h.rowid
        WHERE 1=1 {received_filter}
        GROUP BY m.rowid
        ORDER BY m.date DESC LIMIT ?
    """, [limit])
    rows = cursor.fetchall()
    if not rows:
        return "No messages found."

    name_map = _build_name_map()
    source_cache: dict = {}

    # Group messages by chat thread (chronological within each thread)
    threads: dict[str, list[str]] = defaultdict(list)
    thread_order: list[str] = []

    for text, attr_body, is_from_me, date, display_name, chat_id, sender_handle, has_atts, reaction_type, assoc_guid in reversed(rows):
        body = _decode_message_text(text, attr_body)
        if not body:
            body = "[image]" if has_atts else None
        if not body:
            continue

        body = _format_reaction(body, reaction_type, assoc_guid, cursor, name_map, source_cache)
        dt = _format_timestamp(date)
        sender = _resolve_sender(is_from_me, sender_handle, name_map, display_name)

        if chat_id not in thread_order:
            thread_order.append(chat_id)
        threads[chat_id].append(f"  [{dt}] {sender}: {body}")

    if not threads:
        return "No readable messages found."

    # Resolve participant names to identify group chats
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

    # Build section headers
    sections = []
    for chat_id in thread_order:
        participants = chat_participants.get(chat_id, [])
        is_group = len(participants) > 1
        digits = _last10(chat_id or "")
        dn = next(
            (dn for _, _, _, _, dn, cid, _, _, _, _ in rows if cid == chat_id and dn), None
        )
        label = name_map.get(digits) or dn or ("Group Chat" if is_group else chat_id)

        header = f"--- {'Group: ' if is_group else ''}{label} ---"
        if is_group and chat_id in chat_participants:
            names = ", ".join(sorted(set(chat_participants[chat_id])))
            header += f"\nParticipants: {names}"

        sections.append(header + "\n" + "\n".join(threads[chat_id]))

    return "\n\n".join(sections)


# ── iMessage read: specific contact ─────────────────────────────────────────

def _read_contact_messages(cursor, contact: str, limit: int, received_only: bool) -> str:
    """Read recent messages from a specific contact."""
    # Resolve contact's phone numbers and emails via Contacts.app
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

    # Find matching handles and chats
    cursor.execute("SELECT rowid, id FROM handle")
    matching_handle_ids = [
        rowid for rowid, hid in cursor.fetchall()
        if any(_last10(hid) == d for d in phone_digits)
        or hid.lower() in emails
    ]
    if not matching_handle_ids:
        return f"No messages found for {contact}."

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

    # Fetch messages with reaction and attachment metadata
    received_filter = "AND m.is_from_me = 0" if received_only else ""
    placeholders = ','.join('?' * len(matching_chat_ids))
    cursor.execute(f"""
        SELECT m.text, m.attributedBody, m.is_from_me, m.date,
               m.cache_has_attachments, m.associated_message_type,
               m.associated_message_guid
        FROM message m
        JOIN chat_message_join cmj ON m.rowid = cmj.message_id
        WHERE cmj.chat_id IN ({placeholders}) {received_filter}
        GROUP BY m.rowid
        ORDER BY m.date DESC LIMIT ?
    """, matching_chat_ids + [limit])

    rows = cursor.fetchall()
    if not rows:
        return f"No messages found for {contact}. (handles: {len(matching_handle_ids)}, chats: {len(matching_chat_ids)})"

    name_map = _build_name_map()
    source_cache: dict = {}
    first_name = contact.split()[0] if contact.split() else contact
    lines = []
    for text, attr_body, is_from_me, date, has_atts, reaction_type, assoc_guid in reversed(rows):
        body = _decode_message_text(text, attr_body)
        if not body:
            body = "[image]" if has_atts else None
        if not body:
            continue

        body = _format_reaction(body, reaction_type, assoc_guid, cursor, name_map, source_cache)
        dt = _format_timestamp(date)
        sender = "You" if is_from_me else first_name
        lines.append(f"[{dt}] {sender}: {body}")

    if not lines:
        return f"No readable messages found for {contact} (messages may be attachments or reactions only)."
    return '\n'.join(lines)


# ── iMessage read: entry point ──────────────────────────────────────────────

@permission(Permission.READ_ONLY)
def read_imessages(contact: str, limit: int = 10, received_only: bool = False) -> str:
    """Read recent iMessages. Args: contact (str) - contact name as it appears in Contacts; pass empty string "" to get most recent messages across all conversations, limit (int, optional) - number of recent messages to return (default 10), received_only (bool, optional) - if true, only return messages received from others (not sent by you). Returns: formatted message history or an error with setup instructions."""
    conn, error = _open_messages_db()
    if error:
        return error
    try:
        cursor = conn.cursor()
        if not contact:
            return _read_all_conversations(cursor, limit, received_only)
        return _read_contact_messages(cursor, contact, limit, received_only)
    finally:
        conn.close()


# ── iMessage send ───────────────────────────────────────────────────────────

@permission(Permission.REQUIRES_CONFIRMATION)
def send_imessage(contact: str, message: str = "", area_code: str = "", label: str = "") -> str:
    """Send a text message to a contact by name using the macOS Messages app. To send a GIF, first call find_gif to get a URL, then pass it as the message — iMessage will auto-preview it. Args: contact (str) - full name as it appears in Contacts (e.g. "Millie Wu"), message (str) - the message text to send, area_code (str, optional) - filter to a phone number with this area code (e.g. "929"), label (str, optional) - filter by phone label such as "mobile", "home", "work", "iPhone" (case-insensitive). Returns: confirmation string or "Error: <message>" on failure."""
    # Step 1: resolve phone number from Contacts via AppleScript.
    # `launch` reconnects to the running instance without bringing it to the
    # foreground — prevents the -600 "Application isn't running" error.
    phone_selection = _build_phone_selection(contact, area_code, label)
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

    # Step 2: determine the right messaging service for this number.
    # A contact may have multiple handles (e.g. an iMessage email handle AND
    # an RCS/SMS phone handle). Prefer iMessage if any handle uses it.
    service_type = _detect_service(e164)

    # Step 3: send via the determined service, with fallback to the other
    return _send_via_messages_app(e164, message, contact, service_type)


def _build_phone_selection(contact: str, area_code: str, label: str) -> str:
    """Build the AppleScript fragment that selects which phone number to use."""
    if not area_code and not label:
        return '''
    if (count of phones of thePerson) is 0 then error "Contact has no phone number"
    set thePhone to value of item 1 of phones of thePerson'''

    area_code_check = ""
    if area_code:
        area_code_check = f'''
            set cleanPhone to ""
            repeat with c in characters of phoneVal
                if c is in "0123456789" then set cleanPhone to cleanPhone & c
            end repeat
            if (length of cleanPhone > 10) and cleanPhone starts with "1" then
                set cleanPhone to text 2 thru -1 of cleanPhone
            end if
            if not (cleanPhone starts with "{area_code}") then set matches to false'''

    label_check = ""
    if label:
        label_check = f'''
            ignoring case
                if phoneLabel does not contain "{label}" then set matches to false
            end ignoring'''

    filter_desc = " and ".join(filter(None, [
        f"area code {area_code}" if area_code else "",
        f'label "{label}"' if label else "",
    ]))

    return f'''
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


def _detect_service(e164: str) -> str:
    """Check chat.db to determine whether to send via iMessage or SMS."""
    service_type = "iMessage"
    db_path = os.path.expanduser("~/Library/Messages/chat.db")
    last10_digits = _last10(e164)
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
                service_type = "iMessage" if "iMessage" in services_found else services_found.pop()
        except Exception:
            pass
    return service_type


def _send_via_messages_app(e164: str, message: str, contact: str, service_type: str) -> str:
    """Send a message via Messages.app AppleScript, with service fallback."""
    if service_type == "iMessage":
        primary, fallback = "iMessage", "SMS"
    else:
        primary, fallback = "SMS", "iMessage"

    # AppleScript doesn't support backslash escaping in strings, so we pass
    # the message via an environment variable and read it with do shell script.
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


# ── Tool registry ───────────────────────────────────────────────────────────

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

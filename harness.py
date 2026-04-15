"""LLM harness: generation loop and tool call handling.

This is the core of the harness — the loop that makes an LLM feel like an agent.

The key insight: the model doesn't "run" tools. It outputs text that *looks like*
a tool call (a JSON object). The harness intercepts that text, runs the actual
tool, and feeds the result back as context. The model never leaves the token world.

This is exactly how Claude Code, LangChain agents, and GPT function calling work
under the hood — just with more scaffolding around the edges.
"""
import json
import inspect
import re
from typing import Optional


def get_tool_schemas(tools: dict) -> dict:
    """Extract name and docstring from each tool function.

    Returns a dict of {tool_name: {"name": ..., "description": ...}}.
    These schemas are serialized into the system prompt so the model knows
    what tools are available and how to call them.
    """
    schemas = {}
    for name, fn in tools.items():
        schemas[name] = {
            "name": name,
            "description": inspect.getdoc(fn) or "",
        }
    return schemas


def build_system_prompt(tools: dict) -> str:
    """Build a system prompt that describes available tools to the model.

    The model learns what tools exist and how to call them entirely from this
    prompt — there's no magic. If you want to add a tool, you add it to the
    registry and it shows up here automatically.
    """
    from datetime import datetime as _dt
    now = _dt.now()
    today_str = now.strftime("Today is %A, %B %d, %Y. The current time is %I:%M %p.")
    today_iso = _dt.now().strftime("%Y-%m-%d")

    from memory import compile_paragraph
    memory_block = compile_paragraph()

    schemas = get_tool_schemas(tools)
    tool_descriptions = json.dumps(list(schemas.values()), indent=2)
    memory_section = f"\n{memory_block}\n" if memory_block else ""
    return f"""You are a helpful assistant with access to tools.

{today_str} Convert relative dates to ISO 8601 using this (e.g. "tomorrow" → "{today_iso}" + 1 day).
{memory_section}

TOOL CALL FORMAT — respond with ONLY this JSON, nothing else:
{{"tool": "<tool_name>", "args": {{"<arg_name>": "<value>"}}}}

Available tools:
{tool_descriptions}

RULES:
1. ACT, DON'T ASK. If you have enough context to call a tool, call it. Never say "would you like me to..." or "should I..." — just do it.
2. Live data (messages, calendar, web) is NEVER in memory. Always call the tool, even if a result is in the conversation history.
3. One tool per turn. After getting a result, use it to answer the question or call the next tool.
4. Summarize tool results for the user — don't repeat raw output. Summarize messages by thread, not as a flat list.
5. Be concise. After completing tool calls, give the user a short final answer. Don't narrate your reasoning ("The message was sent successfully. I should confirm...") — just say the result ("Done! Sent the weather to Sam.").
6. Copy URLs and file paths exactly as written. Never correct or modify them.
7. For greetings and chitchat ("hello", "thanks", "ok"), respond in plain text — no tool needed.
8. For vague/creative requests ("send a gif to someone who deserves it"), be autonomous: read messages for context, make a fun choice, and act. Don't interview the user.

MEMORY — you can remember and recall facts across sessions:
- Use `remember` to save important facts (contacts, preferences, appointments). Set always_on=true for facts that should be available every turn.
- Use `recall` when you need to disambiguate a name, check a preference, or look up something the user said before.
- Facts marked always_on=true in the USER CONTEXT above are available every turn without calling recall.
- When the user corrects you ("no, the other Sam"), save the correction with remember so you don't repeat the mistake.

PICK THE RIGHT TOOL — don't default to calendar for everything:
- Questions about the world, facts, places, people → web_search
- Questions about YOUR schedule, events, availability → read_calendar
- Questions about YOUR messages, conversations → read_imessages
- "where is Shelton?" → web_search (it's a factual question, not a calendar query)
- "what's the weather?" / "is it raining?" → get_weather
- "tell Jake about Shelton" → compose from what you know + send_imessage
- "tell the group with Dana and Sam..." → send_group_imessage (for group chats, use participant names)

EXAMPLES:
- "what files are here?" → {{"tool": "run_shell", "args": {{"command": "ls"}}}}
- "what is 123 * 456?" → {{"tool": "calculator", "args": {{"expression": "123 * 456"}}}}
- "search for X" → {{"tool": "web_search", "args": {{"query": "X"}}}}
- "where is Shelton?" → {{"tool": "web_search", "args": {{"query": "Shelton location"}}}}
- "what's the weather in Seattle?" → {{"tool": "get_weather", "args": {{"location": "Seattle"}}}}
- "is it raining?" → {{"tool": "get_weather", "args": {{"location": "<user's likely city from context>"}}}}
- "read my recent messages" → {{"tool": "read_imessages", "args": {{"contact": "", "limit": 20}}}}
- "what did John say?" → {{"tool": "read_imessages", "args": {{"contact": "John"}}}}
- "messages from Sarah this month" → {{"tool": "read_imessages", "args": {{"contact": "Sarah", "days_back": 30}}}}
- "send John a text saying hi" → {{"tool": "send_imessage", "args": {{"contact": "John", "message": "hi"}}}}
- "tell Sarah she left her keys" → {{"tool": "send_imessage", "args": {{"contact": "Sarah", "message": "you left your keys here"}}}}
- "tell the group chat with Dana and Sam to meet at 10am" → {{"tool": "send_group_imessage", "args": {{"participants": "Dana, Sam", "message": "meet here at 10am"}}}}
- "respond to the group with Ryan and Dana" → {{"tool": "send_group_imessage", "args": {{"participants": "Ryan, Dana", "message": "<your response>"}}}}
- "read the group chat with Dana and Sam" → {{"tool": "read_group_imessages", "args": {{"participants": "Dana, Sam"}}}}
- "what's been happening in the Dana/Ryan/Sam chat?" → {{"tool": "read_group_imessages", "args": {{"participants": "Dana, Ryan, Sam"}}}}
- "send a gif of a dumpster fire to John" → STEP 1: {{"tool": "find_gif", "args": {{"query": "dumpster fire"}}}} → STEP 2 (after getting URL): {{"tool": "send_imessage", "args": {{"contact": "John", "message": "<the URL from find_gif>"}}}}
- "send Peter a funny gif" → STEP 1: {{"tool": "find_gif", "args": {{"query": "funny"}}}} → STEP 2: {{"tool": "send_imessage", "args": {{"contact": "Peter", "message": "<the URL>"}}}}
- "summarize my calendar and text it to Sarah" → STEP 1: {{"tool": "read_calendar", "args": {{}}}} → STEP 2: {{"tool": "send_imessage", "args": {{"contact": "Sarah", "message": "<your summary>"}}}}
- "what's on my calendar?" → {{"tool": "read_calendar", "args": {{"start_date": "{today_iso}"}}}}
- "what's on my Work calendar this month?" → {{"tool": "read_calendar", "args": {{"start_date": "{today_iso}", "days_ahead": 30, "calendar_name": "Work"}}}}
- "schedule lunch Thu at noon" → {{"tool": "create_event", "args": {{"title": "Lunch", "start_time": "<Thu>T12:00:00"}}}}
- "fetch alfredsin.com" → {{"tool": "fetch_url", "args": {{"url": "http://alfredsin.com"}}}}
- "remember that Sam means Sam Chen" → {{"tool": "remember", "args": {{"fact": "Sam means Sam Chen", "category": "contact", "always_on": true}}}}
- "when is Jake's birthday?" → {{"tool": "recall", "args": {{"query": "Jake birthday"}}}}

SENDING MESSAGES — when composing text for send_imessage:
- Write like a human texting a friend. Casual, warm, no markdown (iMessage doesn't render it).
- Summarize — don't dump raw data. Use line breaks between sections.
- Rewrite from the recipient's perspective. The user talks ABOUT the recipient in third person — you must convert to second person in the message:
  "tell Sarah she'll love the tongs" → message: "you'll love the tongs" (NOT "she'll love the tongs")
  "let John know he left his keys" → message: "you left your keys here" (NOT "he left his keys")
  "remind Jake he has a meeting" → message: "hey, you have a meeting" (NOT "he has a meeting")
- BAD: "Tue Apr 7: Staycation\\nFri Apr 17: Fishing\\nWed Apr 22: Portland"
- GOOD: "Hey! Quick recap — staycation on the 7th, fishing on the 17th, then Portland starting the 22nd. Let me know if you need details!"

CALENDAR — convert relative dates to ISO 8601. Use calendar_name to filter when the user mentions a specific calendar. Use days_ahead for vague ranges ("next few months" → days_ahead: 90)."""


def _quote_toplevel_keys(raw: str) -> str:
    """Quote unquoted JSON keys at the top level only.

    Naively applying \\w+: → "\\w+": breaks content inside string values
    (e.g. "07:00" becomes "07":00). This function walks the string and only
    quotes keys that appear outside of quoted strings at brace depth 1.
    """
    result = []
    in_string = False
    escape = False
    depth = 0
    i = 0
    while i < len(raw):
        ch = raw[i]
        if escape:
            result.append(ch)
            escape = False
            i += 1
            continue
        if ch == '\\' and in_string:
            result.append(ch)
            escape = True
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue
        if in_string:
            result.append(ch)
            i += 1
            continue
        if ch == '{':
            depth += 1
            result.append(ch)
            i += 1
            continue
        if ch == '}':
            depth -= 1
            result.append(ch)
            i += 1
            continue
        # At depth 1, outside strings: look for unquoted keys (word:)
        if depth == 1:
            m = re.match(r'(\w+)\s*:', raw[i:])
            if m and (not result or result[-1] in ('{', ',', ' ', '\n')):
                result.append(f'"{m.group(1)}":')
                i += m.end()
                continue
        result.append(ch)
        i += 1
    return ''.join(result)


def _fix_unclosed_quotes(text: str) -> str:
    """Fix unclosed string values in JSON-like text.

    Models sometimes omit the closing quote: {"query":"hello world}
    This walks the string tracking brace depth. When we're inside a string
    and hit a } that would close a JSON object (depth would reach 0),
    we insert a closing quote first. Escaped braces inside strings
    (like echo {\\"key\\": \\"val\\"}) are left alone.
    """
    result = []
    in_string = False
    escape = False
    depth = 0
    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == '\\':
            result.append(ch)
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if not in_string:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
        elif ch == '}' and depth <= 1:
            # Inside a string, and this } would close the JSON object —
            # the quote was likely meant to close before it.
            result.append('"')
            in_string = False
            depth -= 1
        result.append(ch)
    return ''.join(result)


def parse_tool_call(response: str) -> Optional[dict]:
    """Try to parse a tool call JSON from the model response.

    Returns a dict with "tool" and "args" keys if the response is a tool call,
    or None if it's a plain text response.

    Handles markdown code blocks (```json ... ```) and preamble text since some
    models wrap JSON in fences or add text before the JSON even when instructed
    not to.
    """
    text = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", response, flags=re.DOTALL).strip()

    # Repair common model output errors before attempting to parse:
    # - stray backslash before value quotes: `: \"value"` → `: "value"`
    #   Only match when preceded by `: ` or `,` at the boundary of a JSON value,
    #   NOT inside an already-quoted string (where \" is a valid escape).
    text = re.sub(r'(?<=[{,])\s*"([^"]+)":\s*\\(")', r' "\1": \2', text)
    # - stray \n" between closing quote and braces: "value"\n"}} → "value"}}
    text = re.sub(r'"\\n"(\s*\}\})', r'"\1', text)
    # - </think> tags from thinking mode leaking into output
    text = re.sub(r'</think>\s*', '', text)
    # - missing values like "limit": ,  →  "limit": null
    text = re.sub(r':\s*,', ': null,', text)
    # - unclosed string before } — add the missing closing quote
    text = _fix_unclosed_quotes(text)
    # - trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Try the whole response first (fast path)
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("tool"), str):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # Fall back: scan for a brace-balanced {...} block containing "tool".
    # The simple [^{}]* regex fails on nested objects like {"args": {...}},
    # so we use bracket matching instead.
    for i, ch in enumerate(text):
        if ch != '{':
            continue
        depth = 0
        for j in range(i, len(text)):
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
            if depth == 0:
                candidate = text[i:j + 1]
                if '"tool"' in candidate:
                    try:
                        data = json.loads(candidate)
                        if isinstance(data, dict) and isinstance(data.get("tool"), str):
                            return data
                    except (json.JSONDecodeError, ValueError):
                        pass
                break

    # Last resort: handle Gemma-style `call:"tool_name", "args": {...}` output
    # by extracting the tool name and using brace matching on the args object.
    call_match = re.search(r'call:\s*"([^"]+)"\s*,\s*"args"\s*:\s*(\{)', text)
    if call_match:
        tool_name = call_match.group(1)
        args_start = call_match.start(2)
        depth = 0
        for j in range(args_start, len(text)):
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
            if depth == 0:
                try:
                    args = json.loads(text[args_start:j + 1])
                    return {"tool": tool_name, "args": args}
                except (json.JSONDecodeError, ValueError):
                    pass
                break

    # Final fallback: handle `call:"tool_name", "key": "val", ...}` where the
    # model omits the "args" wrapper and dumps key-value pairs directly.
    call_flat = re.search(r'call:\s*"([^"]+)"\s*,\s*', text)
    if call_flat:
        tool_name = call_flat.group(1)
        rest = text[call_flat.end():]
        # Wrap the flat pairs in braces to form valid JSON
        json_str = '{' + rest.rstrip().rstrip('}') + '}'
        # Repair: trailing commas, missing values
        json_str = re.sub(r':\s*,', ': null,', json_str)
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
        try:
            args = json.loads(json_str)
            if isinstance(args, dict):
                return {"tool": tool_name, "args": args}
        except (json.JSONDecodeError, ValueError):
            pass

    # Handle Gemma call: prefix variants. The model produces many combinations:
    #   call:"tool", "args": {...}        call:tool:name:read_calendar,...
    #   call:tool:name:"read_calendar",.. call:tool:read_calendar{...}
    #   call:tool_name:"read_calendar", args={...}
    # Strategy: find everything between "call:" and the first "{", then extract
    # the last word-like token as the tool name (it's always the rightmost one).
    call_prefix = re.search(r'call:(.*?)(\{)', text, re.DOTALL)
    if call_prefix:
        prefix = call_prefix.group(1)
        # Strip trailing args/arg keyword and separators, then grab the last word
        clean = re.sub(r'[,;]?\s*"?args?"?\s*[=:]?\s*$', '', prefix).strip()
        name_match = re.search(r'"(\w+)"\s*$', clean) or re.search(r'(\w+)\s*$', clean)
        if name_match:
            tool_name = name_match.group(1)
            args_start = call_prefix.start(2)
            depth = 0
            for j in range(args_start, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                if depth == 0:
                    raw = text[args_start:j + 1]
                    # Try parsing as-is first (keys might already be quoted)
                    raw_cleaned = re.sub(r',\s*([}\]])', r'\1', raw)
                    try:
                        args = json.loads(raw_cleaned)
                        return {"tool": tool_name, "args": args}
                    except (json.JSONDecodeError, ValueError):
                        pass
                    # Retry with unquoted key repair — but only quote keys
                    # at brace depth 1 (top-level), not inside string values.
                    # Simple heuristic: only quote \w+: when preceded by { or
                    # a comma that's NOT inside a quoted string.
                    repaired = _quote_toplevel_keys(raw)
                    repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
                    try:
                        args = json.loads(repaired)
                        return {"tool": tool_name, "args": args}
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break

    return None


def confirm_and_run(tool_call: dict, tools: dict, confirm_fn=None, result_fn=None, display_fn=None) -> str:
    """Ask user to confirm, then run the tool. Returns the result as a string.

    confirm_fn: callable(tool_name: str, args: dict) -> bool | str
      Returns True (approved), False (denied), or a string (feedback for the model).
      If None, falls back to a plain input() prompt (useful outside a rich CLI).
      The CLI passes cli.confirm_tool here; tests pass a lambda.

    result_fn: callable(result: str) -> None — called after the tool runs, for display.
      If None, the result is returned but not displayed.

    display_fn: callable(tool_name: str, args: dict) -> None — displays the tool
      call without asking for confirmation. Used for READ_ONLY tools so the user
      sees what's happening even though no approval is needed.

    Keeping confirm_fn injectable is what makes this function testable without
    any terminal interaction.
    """
    tool_name = tool_call.get("tool")
    args = tool_call.get("args", {})

    if tool_name not in tools:
        return f"Error: unknown tool '{tool_name}'"

    # Drop null args so function defaults kick in rather than passing None
    args = {k: v for k, v in args.items() if v is not None}

    # Always display the tool call so the user sees what's happening,
    # even for read-only tools that don't need confirmation.
    needs_confirmation = getattr(tools[tool_name], "needs_confirmation", True)

    if needs_confirmation:
        if confirm_fn is None:
            print(f"[Tool call] {tool_name}({args})")
            approved = input("Run this? [y/n]: ").strip().lower() == "y"
        else:
            approved = confirm_fn(tool_name, args)
    else:
        # Read-only: show the call but don't ask for approval
        if display_fn is not None:
            display_fn(tool_name, args)
        elif confirm_fn is None:
            print(f"[Tool call] {tool_name}({args})")
        approved = True

    # String feedback: don't run the tool, pass the feedback to the model
    if isinstance(approved, str):
        return f"User feedback (do NOT run the tool — adjust and try again): {approved}"

    if not approved:
        return "Tool call denied by user."

    try:
        result = str(tools[tool_name](**args))
    except Exception as e:
        result = f"Error running tool: {e}"

    if result_fn is not None:
        result_fn(result)

    return result


def _summarize_tool_result(content: str, tool_name: str) -> str:
    """Generate a compact summary of a tool result without using the model."""
    lines = content.strip().split('\n')

    if tool_name == 'read_calendar':
        events = [l.strip() for l in lines if l.strip().startswith('[')]
        titles = []
        for e in events:
            parts = e.split('] ', 1)
            if len(parts) > 1:
                title = parts[1].split('  (')[0].strip()
                if title and title not in ('[all day]', ''):
                    # Strip [all day] prefix if present
                    title = title.replace('[all day] ', '')
                    if title:
                        titles.append(title)
        unique_titles = list(dict.fromkeys(titles))  # dedupe preserving order
        return f"[trimmed {tool_name}: {len(events)} events — {', '.join(unique_titles[:5])}]"

    if tool_name in ('read_imessages', 'read_group_imessages'):
        msg_count = sum(1 for l in lines if l.strip().startswith('['))
        senders = set()
        for l in lines:
            if '] ' in l and ': ' in l:
                sender = l.split('] ', 1)[1].split(': ', 1)[0].strip()
                if sender:
                    senders.add(sender)
        return f"[trimmed {tool_name}: {msg_count} messages — {', '.join(list(senders)[:4])}]"

    if tool_name == 'get_weather':
        summary = ' '.join(l.strip() for l in lines[:2] if l.strip())
        return f"[trimmed {tool_name}: {summary}]"

    if tool_name == 'web_search':
        titles = [l.strip() for l in lines if l.strip() and not l.strip().startswith('http')][:3]
        return f"[trimmed {tool_name}: {', '.join(titles[:2])}]"

    # Default
    first = next((l.strip() for l in lines if l.strip()), '')[:60]
    return f"[trimmed tool result: {len(content)} chars — {first}]"


def _trim_stale_tool_results(conversation: list, keep_recent: int = 2):
    """Replace old tool results with compact summaries.

    Keeps the last `keep_recent` user turns' tool results intact.
    Older tool results > 200 chars are replaced with a smart summary
    that preserves the tool name and key content (event titles, sender
    names, etc.) without using the model.
    """
    # Count user messages from the end to find the cutoff
    user_count = 0
    cutoff_idx = len(conversation)
    for i in range(len(conversation) - 1, -1, -1):
        if conversation[i]["role"] == "user":
            user_count += 1
            if user_count >= keep_recent:
                cutoff_idx = i
                break

    # Replace tool results before the cutoff
    for i in range(cutoff_idx):
        msg = conversation[i]
        if msg["role"] != "tool" or len(msg["content"]) <= 200:
            continue
        # Already trimmed on a previous iteration
        if msg["content"].startswith("[trimmed "):
            continue
        # Extract tool name from the preceding assistant message
        tool_name = "unknown"
        if i > 0 and conversation[i - 1]["role"] == "assistant":
            try:
                call = json.loads(conversation[i - 1]["content"])
                tool_name = call.get("tool", "unknown")
            except (json.JSONDecodeError, ValueError):
                m = re.search(r'"?tool"?\s*[:=]\s*"?(\w+)', conversation[i - 1]["content"])
                if m:
                    tool_name = m.group(1)
        msg["content"] = _summarize_tool_result(msg["content"], tool_name)


def run_conversation_turn(
    user_message: str,
    conversation: list,
    model_fn,
    tools: dict,
    confirm_fn=None,
    result_fn=None,
    display_fn=None,
    max_iterations: int = 10,
) -> str:
    """Run one full conversation turn and return the final assistant response.

    This is the main loop. Here's what happens each iteration:
      1. Call model_fn with the current conversation
      2. If the response is a tool call → confirm, run, inject result, repeat
      3. If the response is plain text → we're done, return it

    model_fn: callable(conversation: list[dict]) -> str
      Any callable that takes a conversation and returns a string.
      Could be a HuggingFace model, an API call, or a test stub.

    The conversation list is mutated in place — user_message is appended at the
    start of this call, so don't add it yourself beforehand. The full history
    (including intermediate tool calls and results) is in conversation after the call.
    """
    conversation.append({"role": "user", "content": user_message})

    for _ in range(max_iterations):
        _trim_stale_tool_results(conversation)
        try:
            response = model_fn(conversation)
        except KeyboardInterrupt:
            conversation.append({"role": "assistant", "content": "(generation cancelled by user)"})
            return "(cancelled)"
        tool_call = parse_tool_call(response)

        if tool_call is None:
            # Plain text response — we're done.
            # Warn if the response looks like it contains a tool call that
            # the parser couldn't extract (helps debug format issues).
            if '"tool"' in response or 'call:' in response:
                import logging
                logging.warning(
                    "Response contains tool-call-like text but parse_tool_call returned None. "
                    "Last 200 chars: %s", response[-200:]
                )
            conversation.append({"role": "assistant", "content": response})
            return response

        # Tool call — confirm, run, inject result, loop again
        conversation.append({"role": "assistant", "content": response})
        result = confirm_and_run(tool_call, tools, confirm_fn=confirm_fn, result_fn=result_fn, display_fn=display_fn)
        conversation.append({"role": "tool", "content": result})

    fallback = "Reached maximum tool call iterations."
    conversation.append({"role": "assistant", "content": fallback})
    return fallback

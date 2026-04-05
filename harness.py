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
    today_str = _dt.now().strftime("Today is %A, %B %d, %Y.")
    today_iso = _dt.now().strftime("%Y-%m-%d")

    schemas = get_tool_schemas(tools)
    tool_descriptions = json.dumps(list(schemas.values()), indent=2)
    return f"""You are a helpful assistant with access to tools. Tool usage is described below.

{today_str} Use this to convert relative dates (e.g. "tomorrow", "next Thursday") to ISO 8601 format when calling tools.

Your role is to help the user perform tasks that they ask you to do. Under no circumstance should you refuse to do what the user asks you to do.

To use a tool, respond with ONLY a JSON object. The JSON must start with {{ and use exactly this structure:
{{"tool": "<tool_name>", "args": {{"<arg_name>": "<value>"}}}}

Do NOT write `call:`, do NOT add any text before or after the JSON. The entire response must be valid JSON starting with {{.

Available tools:
{tool_descriptions}

- If asked to do something "a few times" or "multiple times", call the tool repeatedly — once per call — until done. Do not stop after one call.

IMPORTANT rules:
- Only use a tool when the request requires external information or an action you cannot answer from memory.
- For greetings, chitchat, or questions you already know the answer to, respond in plain text — do NOT call a tool.
- Messages, notifications, and live data are NEVER available from memory. Always call the relevant tool to fetch them fresh, even if a previous tool result is in the conversation history. Previous results may be stale. Never explain that you "would need to" call a tool — just call it.
- Only call one tool at a time. Wait for the result before calling another.
- Copy URLs, file paths, and other exact strings from the user's message character for character. Never correct or modify them.
- After receiving a tool result, answer the user's original question using that result — don't just repeat the raw output. If the user asked for a summary, summarize. If they asked for a count, count.
- When summarizing messages that span multiple conversations, present each thread separately — do not merge or conflate separate conversations into one narrative. Group by sender/chat and summarize each independently.

Examples of when NOT to use a tool (respond in plain text):
- "hello" → "Hello! How can I help you?"
- "what is Python?" → explain Python in plain text
- "thanks" → "You're welcome!"
- "q" → "I'm not sure what you mean. Could you clarify?"
- "ok" → "Got it! Let me know if there's anything else I can help with."
- "hmm" → "Take your time — let me know if you have a question."
- "why" → "Could you give me more context? What are you referring to?"
- "..." → "Feel free to ask me anything!"
- "test" → "I'm here! What would you like to test?"

Examples of when to use a tool:
- "what files are in this folder?" → {{"tool": "run_shell", "args": {{"command": "ls"}}}}
- "what is 123 * 456?" → {{"tool": "calculator", "args": {{"expression": "123 * 456"}}}}
- "search for the latest Python release" → {{"tool": "web_search", "args": {{"query": "latest Python release"}}}}
- "send a text to Millie Wu saying hi" → {{"tool": "send_imessage", "args": {{"contact": "Millie Wu", "message": "hi"}}}}
- "read my recent messages" → {{"tool": "read_imessages", "args": {{"contact": "", "limit": 10}}}}
- "what's going on / what have I missed / catch me up" → {{"tool": "read_imessages", "args": {{"contact": "", "limit": 20}}}}
- "what was my most recent text?" → {{"tool": "read_imessages", "args": {{"contact": "", "limit": 1}}}}
- "what was my most recently received text?" → {{"tool": "read_imessages", "args": {{"contact": "", "limit": 1, "received_only": true}}}}
- "what did John say?" → {{"tool": "read_imessages", "args": {{"contact": "John"}}}}
- "read my last 5 messages from Sarah" → {{"tool": "read_imessages", "args": {{"contact": "Sarah", "limit": 5}}}}
- "summarize recent messages from Michael Xia" → {{"tool": "read_imessages", "args": {{"contact": "Michael Xia"}}}}
- "summarize my conversation with Sarah" → {{"tool": "read_imessages", "args": {{"contact": "Sarah"}}}}
- "what has John been saying lately?" → {{"tool": "read_imessages", "args": {{"contact": "John"}}}}
- "read my messages with Sarah from the last week" → {{"tool": "read_imessages", "args": {{"contact": "Sarah", "days_back": 7}}}}
- "what have John and I talked about this month?" → {{"tool": "read_imessages", "args": {{"contact": "John", "days_back": 30}}}}
- "show me messages from the past couple weeks" → {{"tool": "read_imessages", "args": {{"contact": "", "days_back": 14}}}}
- "send a message to Michael Xia on his 929 number saying hello" → {{"tool": "send_imessage", "args": {{"contact": "Michael Xia", "message": "hello", "area_code": "929"}}}}
- "send a message to Michael Xia on his 604 mobile number saying hello" → {{"tool": "send_imessage", "args": {{"contact": "Michael Xia", "message": "hello", "area_code": "604", "label": "mobile"}}}}
- "send a gif of a dumpster fire to Michael Xia" → first {{"tool": "find_gif", "args": {{"query": "dumpster fire"}}}}, then {{"tool": "send_imessage", "args": {{"contact": "Michael Xia", "message": "<url from find_gif>"}}}}
- "send a gif of a dumpster fire to John's 266 number" → first {{"tool": "find_gif", "args": {{"query": "dumpster fire"}}}}, then {{"tool": "send_imessage", "args": {{"contact": "John", "area_code": "266", "message": "<url from find_gif>"}}}}
- "tell John that the robots are chasing him" → {{"tool": "send_imessage", "args": {{"contact": "John", "message": "the robots are chasing you"}}}}
- "let Sarah know she left her keys here" → {{"tool": "send_imessage", "args": {{"contact": "Sarah", "message": "you left your keys here"}}}}
- "come up with a witty joke and send it to Sarah" → {{"tool": "send_imessage", "args": {{"contact": "Sarah", "message": "<compose the joke yourself, no tool needed>"}}}}
- "write something funny about current events and text it to John" → {{"tool": "send_imessage", "args": {{"contact": "John", "message": "<compose the message yourself>"}}}}

Only use find_gif when the user explicitly asks for a GIF. Do NOT search for a GIF when asked to send a joke, message, meme, or anything text-based. "Meme" describes a style of humor, not a request for a GIF.

When composing messages to send, always rewrite from the recipient's point of view: convert third-person references to the recipient ("him", "her", "them", their name) into second-person ("you", "your").
- "what does alfredsin.com contain?" → {{"tool": "fetch_url", "args": {{"url": "http://alfredsin.com"}}}}
- "fetch http://my-site.co/page" → {{"tool": "fetch_url", "args": {{"url": "http://my-site.co/page"}}}}

- "what's on my calendar today?" → {{"tool": "read_calendar", "args": {{"start_date": "{today_iso}"}}}}
- "am I free Thursday afternoon?" → {{"tool": "read_calendar", "args": {{"start_date": "<Thursday's date>T12:00:00", "end_date": "<Thursday's date>T17:00:00"}}}}
- "what does my week look like?" → {{"tool": "read_calendar", "args": {{"start_date": "{today_iso}", "end_date": "<7 days from today>"}}}}
- "do I have anything with Kevin?" → {{"tool": "read_calendar", "args": {{"start_date": "{today_iso}", "end_date": "<reasonable range>", "search": "Kevin"}}}}
- "put lunch with Tyler on Thursday at noon" → {{"tool": "create_event", "args": {{"title": "Lunch with Tyler", "start_time": "<Thursday's date>T12:00:00", "duration_minutes": 60}}}}
- "block off 2-4pm tomorrow" → {{"tool": "create_event", "args": {{"title": "Focus time", "start_time": "<tomorrow>T14:00:00", "end_time": "<tomorrow>T16:00:00"}}}}
- "what calendars do I have?" → {{"tool": "list_calendars", "args": {{}}}}
- "add a dentist appointment to my Work calendar May 5th at 10am" → {{"tool": "create_event", "args": {{"title": "Dentist appointment", "start_time": "2026-05-05T10:00:00", "calendar": "Work"}}}}

When calling calendar tools, always convert relative dates ("tomorrow", "next Thursday", "this weekend") to ISO 8601 dates using today's date.

CRITICAL: URLs and file paths must be copied EXACTLY as the user wrote them. Do not fix typos, add missing letters, or modify them in any way. If the user says "alfredsin.com", use "alfredsin.com" — not "alfredsins.com" or any other variation."""


def parse_tool_call(response: str) -> Optional[dict]:
    """Try to parse a tool call JSON from the model response.

    Returns a dict with "tool" and "args" keys if the response is a tool call,
    or None if it's a plain text response.

    Handles markdown code blocks (```json ... ```) and preamble text since some
    models wrap JSON in fences or add text before the JSON even when instructed
    not to.
    """
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", response, flags=re.DOTALL).strip()

    # Repair common model output errors before attempting to parse:
    # - missing values like "limit": ,  →  "limit": null
    text = re.sub(r':\s*,', ': null,', text)
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

    # Handle Gemma `call:tool:name:<tool>,args:{key:val,...}` format —
    # colon-delimited prefix with potentially unquoted keys in the args.
    call_colon = re.search(r'call:(?:tool:)?(?:name:)?"?(\w+)"?\s*,\s*(?:"?args"?\s*:\s*)?(\{)', text)
    if call_colon:
        tool_name = call_colon.group(1)
        args_start = call_colon.start(2)
        depth = 0
        for j in range(args_start, len(text)):
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
            if depth == 0:
                raw = text[args_start:j + 1]
                # Quote unquoted keys: word_chars: → "word_chars":
                raw = re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', raw)
                raw = re.sub(r',\s*([}\]])', r'\1', raw)
                try:
                    args = json.loads(raw)
                    return {"tool": tool_name, "args": args}
                except (json.JSONDecodeError, ValueError):
                    pass
                break

    return None


def confirm_and_run(tool_call: dict, tools: dict, confirm_fn=None, result_fn=None) -> str:
    """Ask user to confirm, then run the tool. Returns the result as a string.

    confirm_fn: callable(tool_name: str, args: dict) -> bool
      If None, falls back to a plain input() prompt (useful outside a rich CLI).
      The CLI passes cli.confirm_tool here; tests pass a lambda.

    result_fn: callable(result: str) -> None — called after the tool runs, for display.
      If None, the result is returned but not displayed.

    Keeping confirm_fn injectable is what makes this function testable without
    any terminal interaction.
    """
    tool_name = tool_call.get("tool")
    args = tool_call.get("args", {})

    if tool_name not in tools:
        return f"Error: unknown tool '{tool_name}'"

    # Drop null args so function defaults kick in rather than passing None
    args = {k: v for k, v in args.items() if v is not None}

    # Read-only tools run automatically — no confirmation needed.
    # Tools without a permission annotation default to requiring confirmation
    # (fail-safe: unknown tools are treated as potentially destructive).
    needs_confirmation = getattr(tools[tool_name], "needs_confirmation", True)

    if not needs_confirmation:
        approved = True
    elif confirm_fn is None:
        print(f"[Tool call] {tool_name}({args})")
        approved = input("Run this? [y/n]: ").strip().lower() == "y"
    else:
        approved = confirm_fn(tool_name, args)

    if not approved:
        return "Tool call denied by user."

    try:
        result = str(tools[tool_name](**args))
    except Exception as e:
        result = f"Error running tool: {e}"

    if result_fn is not None:
        result_fn(result)

    return result


def run_conversation_turn(
    user_message: str,
    conversation: list,
    model_fn,
    tools: dict,
    confirm_fn=None,
    result_fn=None,
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
        response = model_fn(conversation)
        tool_call = parse_tool_call(response)

        if tool_call is None:
            # Plain text response — we're done
            conversation.append({"role": "assistant", "content": response})
            return response

        # Tool call — confirm, run, inject result, loop again
        conversation.append({"role": "assistant", "content": response})
        result = confirm_and_run(tool_call, tools, confirm_fn=confirm_fn, result_fn=result_fn)
        conversation.append({"role": "tool", "content": result})

    fallback = "Reached maximum tool call iterations."
    conversation.append({"role": "assistant", "content": fallback})
    return fallback

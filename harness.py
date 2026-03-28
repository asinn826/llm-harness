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
    schemas = get_tool_schemas(tools)
    tool_descriptions = json.dumps(list(schemas.values()), indent=2)
    return f"""You are a helpful assistant with access to tools.

To use a tool, respond with ONLY a JSON object in this exact format:
{{"tool": "<tool_name>", "args": {{"<arg_name>": "<value>"}}}}

Available tools:
{tool_descriptions}

- If asked to do something "a few times" or "multiple times", call the tool repeatedly — once per call — until done. Do not stop after one call.

IMPORTANT rules:
- Only use a tool when the request requires external information or an action you cannot answer from memory.
- For greetings, chitchat, or questions you already know the answer to, respond in plain text — do NOT call a tool.
- Only call one tool at a time. Wait for the result before calling another.
- Copy URLs, file paths, and other exact strings from the user's message character for character. Never correct or modify them.

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
- "send a message to Michael Xia on his 929 number saying hello" → {{"tool": "send_imessage", "args": {{"contact": "Michael Xia", "message": "hello", "area_code": "929"}}}}
- "send a message to Michael Xia on his 604 mobile number saying hello" → {{"tool": "send_imessage", "args": {{"contact": "Michael Xia", "message": "hello", "area_code": "604", "label": "mobile"}}}}
- "send a gif of a dumpster fire to Michael Xia" → first {{"tool": "find_gif", "args": {{"query": "dumpster fire"}}}}, then {{"tool": "send_imessage", "args": {{"contact": "Michael Xia", "message": "<url from find_gif>"}}}}
- "send a gif of a dumpster fire to John's 266 number" → first {{"tool": "find_gif", "args": {{"query": "dumpster fire"}}}}, then {{"tool": "send_imessage", "args": {{"contact": "John", "area_code": "266", "message": "<url from find_gif>"}}}}
- "tell John that the robots are chasing him" → {{"tool": "send_imessage", "args": {{"contact": "John", "message": "the robots are chasing you"}}}}
- "let Sarah know she left her keys here" → {{"tool": "send_imessage", "args": {{"contact": "Sarah", "message": "you left your keys here"}}}}

When composing messages to send, always rewrite from the recipient's point of view: convert third-person references to the recipient ("him", "her", "them", their name) into second-person ("you", "your").
- "what does alfredsin.com contain?" → {{"tool": "fetch_url", "args": {{"url": "http://alfredsin.com"}}}}
- "fetch http://my-site.co/page" → {{"tool": "fetch_url", "args": {{"url": "http://my-site.co/page"}}}}

CRITICAL: URLs and file paths must be copied EXACTLY as the user wrote them. Do not fix typos, add missing letters, or modify them in any way. If the user says "alfredsin.com", use "alfredsin.com" — not "alfredsins.com" or any other variation."""


def parse_tool_call(response: str) -> Optional[dict]:
    """Try to parse a tool call JSON from the model response.

    Returns a dict with "tool" and "args" keys if the response is a tool call,
    or None if it's a plain text response.

    Handles markdown code blocks (```json ... ```) since some models wrap JSON
    in fences even when instructed not to.
    """
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", response, flags=re.DOTALL).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("tool"), str):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
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

    if confirm_fn is None:
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

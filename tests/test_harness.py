"""Tests for harness logic (no model loading required).

The harness is tested without a real model — we pass in a fake model_fn
(a simple callable) so we can control exactly what the model "says."
This is a useful pattern: it shows that the harness is decoupled from
any specific model implementation.
"""
import pytest
from harness import build_system_prompt, parse_tool_call, get_tool_schemas, run_conversation_turn
from tools import TOOLS


def test_get_tool_schemas_includes_all_tools():
    schemas = get_tool_schemas(TOOLS)
    assert "run_shell" in schemas
    assert "calculator" in schemas


def test_get_tool_schemas_includes_descriptions():
    schemas = get_tool_schemas(TOOLS)
    for name, schema in schemas.items():
        assert schema["description"], f"{name} schema has no description"


def test_build_system_prompt_contains_tool_names():
    prompt = build_system_prompt(TOOLS)
    assert "run_shell" in prompt
    assert "calculator" in prompt
    assert "JSON" in prompt


def test_parse_tool_call_detects_valid_json():
    response = '{"tool": "calculator", "args": {"expression": "2+2"}}'
    result = parse_tool_call(response)
    assert result is not None
    assert result["tool"] == "calculator"
    assert result["args"] == {"expression": "2+2"}


def test_parse_tool_call_strips_markdown_code_block():
    response = '```json\n{"tool": "calculator", "args": {"expression": "2+2"}}\n```'
    result = parse_tool_call(response)
    assert result is not None
    assert result["tool"] == "calculator"


def test_parse_tool_call_returns_none_for_plain_text():
    result = parse_tool_call("The answer is 42.")
    assert result is None


def test_parse_tool_call_returns_none_for_bad_json():
    result = parse_tool_call("{ not valid json }")
    assert result is None


def test_parse_tool_call_returns_none_for_json_without_tool_key():
    result = parse_tool_call('{"foo": "bar"}')
    assert result is None


def test_read_only_tools_do_not_require_confirmation():
    """READ_ONLY tools should run without calling confirm_fn."""
    from tools import Permission
    confirm_called = []
    confirm_fn = lambda tool_name, args: confirm_called.append(tool_name) or True

    conversation = []
    responses = iter([
        '{"tool": "calculator", "args": {"expression": "1+1"}}',
        "The answer is 2.",
    ])
    model_fn = lambda conv: next(responses)
    run_conversation_turn("What is 1+1?", conversation, model_fn, TOOLS, confirm_fn=confirm_fn)

    assert confirm_called == [], "confirm_fn should not be called for READ_ONLY tools"
    assert TOOLS["calculator"].permission == Permission.READ_ONLY


def test_requires_confirmation_tools_call_confirm_fn():
    """REQUIRES_CONFIRMATION tools must always call confirm_fn."""
    from tools import Permission
    confirm_called = []
    confirm_fn = lambda tool_name, args: confirm_called.append(tool_name) or False

    conversation = []
    responses = iter([
        '{"tool": "run_shell", "args": {"command": "echo hi"}}',
        "Denied.",
    ])
    model_fn = lambda conv: next(responses)
    run_conversation_turn("Run echo hi", conversation, model_fn, TOOLS, confirm_fn=confirm_fn)

    assert "run_shell" in confirm_called
    assert TOOLS["run_shell"].permission == Permission.REQUIRES_CONFIRMATION


def test_all_tools_have_permission_annotation():
    """Every tool in TOOLS must have a permission annotation — no unannotated tools."""
    for name, fn in TOOLS.items():
        assert hasattr(fn, "permission"), f"Tool '{name}' is missing a @permission annotation"
        assert hasattr(fn, "needs_confirmation"), f"Tool '{name}' is missing needs_confirmation attribute"


def test_parse_tool_call_handles_gemma_call_prefix():
    """Gemma 4 sometimes outputs `call:"tool", "args": {...}` instead of valid JSON."""
    response = 'call:"calculator", "args": {"expression": "2+2"}'
    result = parse_tool_call(response)
    assert result is not None
    assert result["tool"] == "calculator"
    assert result["args"] == {"expression": "2+2"}


def test_run_conversation_turn_plain_response():
    """Model responds with plain text — no tool calls."""
    conversation = []
    model_fn = lambda conv: "The capital of France is Paris."
    result = run_conversation_turn("What is the capital of France?", conversation, model_fn, TOOLS)
    assert result == "The capital of France is Paris."
    assert len(conversation) == 2  # user + assistant


def test_run_conversation_turn_with_tool_call():
    """Model first calls a tool, then responds with plain text."""
    conversation = []
    responses = iter([
        '{"tool": "calculator", "args": {"expression": "2+2"}}',
        "The answer is 4.",
    ])
    model_fn = lambda conv: next(responses)
    confirm_fn = lambda tool_name, args: True  # always approve

    result = run_conversation_turn("What is 2+2?", conversation, model_fn, TOOLS, confirm_fn=confirm_fn)
    assert result == "The answer is 4."
    # conversation: user, tool_call, tool_result, assistant
    assert len(conversation) == 4


def test_run_conversation_turn_denied_tool():
    """User denies a tool call — harness injects denial and model continues.
    Uses run_shell (REQUIRES_CONFIRMATION) so the confirm_fn is actually called.
    """
    conversation = []
    responses = iter([
        '{"tool": "run_shell", "args": {"command": "echo hi"}}',
        "I was unable to run that.",
    ])
    model_fn = lambda conv: next(responses)
    confirm_fn = lambda tool_name, args: False  # always deny

    result = run_conversation_turn("Run echo hi", conversation, model_fn, TOOLS, confirm_fn=confirm_fn)
    assert result == "I was unable to run that."
    # tool result should contain denial message
    tool_result = next(m for m in conversation if m["role"] == "tool")
    assert "denied" in tool_result["content"].lower()


def test_run_conversation_turn_max_iterations():
    """Harness stops after max_iterations even if model keeps calling tools."""
    conversation = []
    model_fn = lambda conv: '{"tool": "calculator", "args": {"expression": "1+1"}}'
    confirm_fn = lambda tool_name, args: True

    result = run_conversation_turn("loop forever", conversation, model_fn, TOOLS, confirm_fn=confirm_fn, max_iterations=3)
    assert "maximum" in result.lower()
    # conversation should end with an assistant message, not a dangling tool result
    assert conversation[-1]["role"] == "assistant"


# ── parse_tool_call edge cases ──────────────────────────────────────────────

def test_parse_tool_call_trailing_comma():
    """JSON with trailing comma before } — common model output error."""
    response = '{"tool": "calculator", "args": {"expression": "2+2",}}'
    result = parse_tool_call(response)
    assert result is not None
    assert result["tool"] == "calculator"


def test_parse_tool_call_null_value():
    """JSON with missing value like "limit": , — repaired to null."""
    response = '{"tool": "read_imessages", "args": {"contact": "", "limit": , "received_only": true}}'
    result = parse_tool_call(response)
    assert result is not None
    assert result["tool"] == "read_imessages"
    assert result["args"]["limit"] is None


def test_parse_tool_call_nested_args():
    """Tool call with nested object in args."""
    response = '{"tool": "run_shell", "args": {"command": "echo {\\"key\\": \\"val\\"}"}}'
    result = parse_tool_call(response)
    assert result is not None
    assert result["tool"] == "run_shell"


def test_parse_tool_call_preamble_text():
    """Model adds text before the JSON tool call."""
    response = 'I will use the calculator tool.\n{"tool": "calculator", "args": {"expression": "3*4"}}'
    result = parse_tool_call(response)
    assert result is not None
    assert result["tool"] == "calculator"
    assert result["args"]["expression"] == "3*4"


def test_parse_tool_call_json_without_args():
    """Tool call with missing args key — should still parse."""
    response = '{"tool": "calculator"}'
    result = parse_tool_call(response)
    assert result is not None
    assert result["tool"] == "calculator"


def test_parse_tool_call_non_string_tool():
    """JSON with non-string tool value — not a valid tool call."""
    result = parse_tool_call('{"tool": 123, "args": {}}')
    assert result is None


def test_parse_tool_call_empty_string():
    result = parse_tool_call("")
    assert result is None


def test_parse_tool_call_plain_json_object():
    """A JSON object without 'tool' key is not a tool call."""
    result = parse_tool_call('{"name": "calculator", "arguments": {"expression": "1+1"}}')
    assert result is None


def test_parse_tool_call_gemma_with_nested_args():
    """Gemma call: format with nested args object."""
    response = 'call:"run_shell", "args": {"command": "ls -la"}'
    result = parse_tool_call(response)
    assert result is not None
    assert result["tool"] == "run_shell"
    assert result["args"]["command"] == "ls -la"


# ── confirm_and_run edge cases ──────────────────────────────────────────────

def test_confirm_and_run_unknown_tool():
    """Unknown tool name returns an error string."""
    from harness import confirm_and_run
    result = confirm_and_run({"tool": "nonexistent", "args": {}}, TOOLS)
    assert "unknown tool" in result.lower()


def test_confirm_and_run_strips_null_args():
    """Null args are stripped so function defaults kick in."""
    from harness import confirm_and_run
    result = confirm_and_run(
        {"tool": "calculator", "args": {"expression": "1+1", "unused": None}},
        TOOLS,
    )
    # calculator only takes 'expression' — null 'unused' should be stripped
    assert result == "2"


def test_confirm_and_run_tool_exception():
    """Tool that raises an exception returns error string."""
    from harness import confirm_and_run
    def bad_tool():
        raise RuntimeError("tool broke")
    bad_tool.needs_confirmation = False
    tools = {"bad": bad_tool}
    result = confirm_and_run({"tool": "bad", "args": {}}, tools)
    assert "Error" in result


def test_confirm_and_run_calls_result_fn():
    """result_fn callback is called with the tool result."""
    from harness import confirm_and_run
    results = []
    confirm_and_run(
        {"tool": "calculator", "args": {"expression": "5+5"}},
        TOOLS,
        result_fn=lambda r: results.append(r),
    )
    assert results == ["10"]


# ── run_conversation_turn edge cases ────────────────────────────────────────

def test_run_conversation_turn_tool_then_tool_then_text():
    """Model calls two tools in sequence, then responds."""
    conversation = []
    responses = iter([
        '{"tool": "calculator", "args": {"expression": "2+2"}}',
        '{"tool": "calculator", "args": {"expression": "4+4"}}',
        "2+2 is 4 and 4+4 is 8.",
    ])
    model_fn = lambda conv: next(responses)
    result = run_conversation_turn("math", conversation, model_fn, TOOLS)
    assert result == "2+2 is 4 and 4+4 is 8."
    # user + tool_call + tool_result + tool_call + tool_result + assistant = 6
    assert len(conversation) == 6


def test_run_conversation_turn_result_fn_called():
    """result_fn is called for each tool result."""
    results = []
    conversation = []
    responses = iter([
        '{"tool": "calculator", "args": {"expression": "9*9"}}',
        "81.",
    ])
    run_conversation_turn(
        "9*9", conversation, lambda conv: next(responses), TOOLS,
        result_fn=lambda r: results.append(r),
    )
    assert results == ["81"]


def test_run_conversation_turn_mutates_conversation():
    """The conversation list is mutated in place."""
    conversation = []
    model_fn = lambda conv: "Hello!"
    run_conversation_turn("hi", conversation, model_fn, TOOLS)
    assert conversation[0] == {"role": "user", "content": "hi"}
    assert conversation[1] == {"role": "assistant", "content": "Hello!"}

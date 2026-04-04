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

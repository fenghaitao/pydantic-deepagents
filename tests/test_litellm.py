"""Tests for pydantic_deep.litellm helpers.

Offline tests exercise wiring without HTTP. A live round-trip runs when you opt in:

- ``LITELLM_API_BASE`` is set (typical self-hosted LiteLLM proxy), **or**
- ``PYDANTIC_DEEP_LITELLM_LIVE=1`` (e.g. GitHub Copilot via LiteLLM **OAuth2** with no custom base).

Configure auth per `LiteLLM’s provider docs <https://docs.litellm.ai/>`_ (OAuth env vars, etc.).

Optional:

- ``PYDANTIC_DEEP_TEST_LITELLM_MODEL``: full pydantic-ai model id, default
  ``litellm:github_copilot/gpt-4o``.
- ``LITELLM_API_KEY``: forwarded to the OpenAI-compatible client when set.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import (
    BuiltinToolCallPart,
    InstructionPart,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition

from pydantic_deep import create_deep_agent, create_default_deps
from pydantic_deep.litellm import (
    DEFAULT_GITHUB_COPILOT_LITELLM_MODEL,
    LiteLLMModel,
    LiteLLMStreamedResponse,
    _get_tools,
    _map_messages,
    _sanitize_tools_for_moonshot,
    _strip_ref_siblings,
    github_copilot_litellm_model,
    infer_litellm_model,
)


def _litellm_live_enabled() -> bool:
    return bool(os.environ.get("LITELLM_API_BASE")) or os.environ.get(
        "PYDANTIC_DEEP_LITELLM_LIVE",
        "",
    ) == "1"


def test_infer_litellm_model_from_prefixed_name() -> None:
    m = infer_litellm_model(
        "litellm:github_copilot/gpt-4o",
    )
    assert isinstance(m, LiteLLMModel)
    assert m.model_name == "github_copilot/gpt-4o"


def test_infer_litellm_model_from_plain_name() -> None:
    m = infer_litellm_model("github_copilot/gpt-4o")
    assert isinstance(m, LiteLLMModel)
    assert m.model_name == "github_copilot/gpt-4o"


def test_infer_litellm_model_adds_copilot_headers() -> None:
    m = infer_litellm_model("github_copilot/gpt-4o")
    assert isinstance(m, LiteLLMModel)
    assert m._extra_headers["Editor-Version"] == "vscode/1.85.1"  # pyright: ignore[reportPrivateUsage]
    assert m._extra_headers["Copilot-Integration-Id"] == "vscode-chat"  # pyright: ignore[reportPrivateUsage]


def test_infer_litellm_model_passes_through_model_instance() -> None:
    inner = TestModel()
    assert infer_litellm_model(inner) is inner


def test_github_copilot_litellm_model() -> None:
    assert github_copilot_litellm_model("gpt-4o") == "github_copilot/gpt-4o"


def test_default_github_copilot_constant() -> None:
    assert DEFAULT_GITHUB_COPILOT_LITELLM_MODEL.startswith("github_copilot/")


def _make_fake_response(
    content: str = "hello",
    tool_calls: list[Any] | None = None,
    finish_reason: str = "stop",
    model: str = "github_copilot/gpt-4o",
    has_usage: bool = True,
) -> Any:
    choice = SimpleNamespace(
        message=SimpleNamespace(
            content=content,
            tool_calls=tool_calls or [],
        ),
        finish_reason=finish_reason,
    )
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5) if has_usage else None
    return SimpleNamespace(choices=[choice], usage=usage, model=model, id="resp-1")


def _make_fake_tool_call(name: str = "my_tool", args: str = '{"x": 1}', id: str = "tc-1") -> Any:
    return SimpleNamespace(
        function=SimpleNamespace(name=name, arguments=args),
        id=id,
    )


def _make_params(
    tool_names: list[str] | None = None, allow_text: bool = True
) -> ModelRequestParameters:
    if not tool_names:
        return ModelRequestParameters(allow_text_output=allow_text)
    tools = [ToolDefinition(name=n, description="desc", parameters_json_schema={}) for n in tool_names]
    return ModelRequestParameters(function_tools=tools, allow_text_output=allow_text)


# ── LiteLLMModel properties ──────────────────────────────────────────────────


def test_system_property() -> None:
    m = LiteLLMModel("github_copilot/gpt-4o")
    assert m.system == "litellm"


# ── _build_kwargs ────────────────────────────────────────────────────────────


def test_build_kwargs_no_tools_no_settings() -> None:
    m = LiteLLMModel("gpt-4o")
    msgs: list[Any] = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    kwargs = m._build_kwargs(msgs, _make_params(), None, stream=False)  # pyright: ignore[reportPrivateUsage]
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["stream"] is False
    assert "tools" not in kwargs
    assert "extra_headers" not in kwargs


def test_build_kwargs_with_tools() -> None:
    m = LiteLLMModel("gpt-4o")
    msgs: list[Any] = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    kwargs = m._build_kwargs(msgs, _make_params(["search"]), None, stream=False)  # pyright: ignore[reportPrivateUsage]
    assert "tools" in kwargs
    assert kwargs["tool_choice"] == "auto"


def test_build_kwargs_tool_choice_required_when_no_text() -> None:
    m = LiteLLMModel("gpt-4o")
    msgs: list[Any] = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    kwargs = m._build_kwargs(msgs, _make_params(["t"], allow_text=False), None, stream=False)  # pyright: ignore[reportPrivateUsage]
    assert kwargs["tool_choice"] == "required"


def test_build_kwargs_moonshot_sanitizes_tools() -> None:
    m = LiteLLMModel("moonshot/kimi-k2.6")
    msgs: list[Any] = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    kwargs = m._build_kwargs(msgs, _make_params(["t"]), None, stream=False)  # pyright: ignore[reportPrivateUsage]
    assert "tools" in kwargs


def test_build_kwargs_settings_applied() -> None:
    from pydantic_ai.settings import ModelSettings

    m = LiteLLMModel("gpt-4o")
    msgs: list[Any] = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    settings: ModelSettings = {"temperature": 0.7, "max_tokens": 100, "top_p": 0.9, "stop_sequences": ["END"]}
    kwargs = m._build_kwargs(msgs, _make_params(), settings, stream=False)  # pyright: ignore[reportPrivateUsage]
    assert kwargs["temperature"] == 0.7
    assert kwargs["max_tokens"] == 100
    assert kwargs["top_p"] == 0.9
    assert kwargs["stop"] == ["END"]


def test_build_kwargs_fixed_temp_model_skips_temperature() -> None:
    from pydantic_ai.settings import ModelSettings

    m = LiteLLMModel("moonshot/kimi-k2.6")
    msgs: list[Any] = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    settings: ModelSettings = {"temperature": 0.5}
    kwargs = m._build_kwargs(msgs, _make_params(), settings, stream=False)  # pyright: ignore[reportPrivateUsage]
    assert "temperature" not in kwargs


def test_build_kwargs_extra_headers_included() -> None:
    m = LiteLLMModel("github_copilot/gpt-4o")
    assert "extra_headers" in m._build_kwargs([], _make_params(), None, stream=False)  # pyright: ignore[reportPrivateUsage]


# ── _process_response ────────────────────────────────────────────────────────


def test_process_response_text_only() -> None:
    m = LiteLLMModel("gpt-4o")
    resp = _make_fake_response("Hello!")
    result = m._process_response(resp)  # pyright: ignore[reportPrivateUsage]
    assert any(isinstance(p, TextPart) and p.content == "Hello!" for p in result.parts)
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5


def test_process_response_tool_call() -> None:
    m = LiteLLMModel("gpt-4o")
    tc = _make_fake_tool_call()
    resp = _make_fake_response(content="", tool_calls=[tc])
    result = m._process_response(resp)  # pyright: ignore[reportPrivateUsage]
    assert any(isinstance(p, ToolCallPart) for p in result.parts)


def test_process_response_no_usage() -> None:
    m = LiteLLMModel("gpt-4o")
    resp = _make_fake_response(has_usage=False)
    result = m._process_response(resp)  # pyright: ignore[reportPrivateUsage]
    assert result.usage.input_tokens == 0


def test_process_response_finish_reason_length() -> None:
    m = LiteLLMModel("gpt-4o")
    resp = _make_fake_response(finish_reason="length")
    result = m._process_response(resp)  # pyright: ignore[reportPrivateUsage]
    assert result.finish_reason == "length"


# ── request and request_stream ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_request_delegates_to_acompletion() -> None:
    m = LiteLLMModel("gpt-4o")
    fake_resp = _make_fake_response("OK")
    msgs: list[Any] = [ModelRequest(parts=[UserPromptPart(content="ping")])]
    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=fake_resp):
        result = await m.request(msgs, None, _make_params())
    assert any(isinstance(p, TextPart) for p in result.parts)


@pytest.mark.anyio
async def test_request_stream_yields_response() -> None:
    m = LiteLLMModel("gpt-4o")
    fake_resp = MagicMock()
    fake_resp.__aiter__ = MagicMock(return_value=iter([]))
    msgs: list[Any] = [ModelRequest(parts=[UserPromptPart(content="ping")])]
    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=fake_resp):
        async with m.request_stream(msgs, None, _make_params()) as streamed:
            assert isinstance(streamed, LiteLLMStreamedResponse)


# ── LiteLLMStreamedResponse ──────────────────────────────────────────────────


def test_streamed_response_properties() -> None:
    params = _make_params()
    fake_response = MagicMock()
    sr = LiteLLMStreamedResponse(
        model_request_parameters=params,
        response=fake_response,
        model_name="gpt-4o",
    )
    assert sr.model_name == "gpt-4o"
    assert sr.provider_name == "litellm"
    assert sr.provider_url is None
    from datetime import datetime
    assert isinstance(sr.timestamp, datetime)


class _AsyncChunks:
    """Simple async iterable that yields a fixed list of chunks."""

    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> "_AsyncChunks":
        self._it = iter(self._chunks)
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.anyio
async def test_get_event_iterator_text_delta() -> None:
    params = _make_params()

    delta = SimpleNamespace(content="Hello", tool_calls=None)
    chunk = SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)

    sr = LiteLLMStreamedResponse(
        model_request_parameters=params,
        response=_AsyncChunks([chunk]),
        model_name="gpt-4o",
    )
    events = [e async for e in sr._get_event_iterator()]  # pyright: ignore[reportPrivateUsage]
    assert len(events) > 0


@pytest.mark.anyio
async def test_get_event_iterator_tool_call_delta_event_is_none() -> None:
    """handle_tool_call_delta returns None on the first (continuation) delta with no name."""
    params = _make_params(["my_tool"])

    # Continuation delta with no name, no id → handle_tool_call_delta returns None
    tc_delta = SimpleNamespace(
        index=0,
        id=None,
        function=SimpleNamespace(name=None, arguments='{"x":1}'),
    )
    delta = SimpleNamespace(content=None, tool_calls=[tc_delta])
    chunk = SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)

    sr = LiteLLMStreamedResponse(
        model_request_parameters=params,
        response=_AsyncChunks([chunk]),
        model_name="gpt-4o",
    )
    events = [e async for e in sr._get_event_iterator()]  # pyright: ignore[reportPrivateUsage]
    assert len(events) >= 0  # event is None → not yielded (branch 250->242 covered)


@pytest.mark.anyio
async def test_get_event_iterator_tool_call_delta() -> None:
    params = _make_params(["my_tool"])

    tc_delta = SimpleNamespace(
        index=0,
        id="tc-1",
        function=SimpleNamespace(name="my_tool", arguments='{"x":1}'),
    )
    delta = SimpleNamespace(content=None, tool_calls=[tc_delta])
    chunk = SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)

    sr = LiteLLMStreamedResponse(
        model_request_parameters=params,
        response=_AsyncChunks([chunk]),
        model_name="gpt-4o",
    )
    events = [e async for e in sr._get_event_iterator()]  # pyright: ignore[reportPrivateUsage]
    assert len(events) >= 0


@pytest.mark.anyio
async def test_get_event_iterator_usage_chunk() -> None:
    params = _make_params()

    delta = SimpleNamespace(content=None, tool_calls=None)
    usage = SimpleNamespace(prompt_tokens=5, completion_tokens=3)
    chunk = SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)

    sr = LiteLLMStreamedResponse(
        model_request_parameters=params,
        response=_AsyncChunks([chunk]),
        model_name="gpt-4o",
    )
    async for _ in sr._get_event_iterator():  # pyright: ignore[reportPrivateUsage]
        pass
    assert sr._usage.input_tokens == 5  # pyright: ignore[reportPrivateUsage]


@pytest.mark.anyio
async def test_get_event_iterator_empty_choices() -> None:
    params = _make_params()

    chunk = SimpleNamespace(choices=[], usage=None)

    sr = LiteLLMStreamedResponse(
        model_request_parameters=params,
        response=_AsyncChunks([chunk]),
        model_name="gpt-4o",
    )
    events = [e async for e in sr._get_event_iterator()]  # pyright: ignore[reportPrivateUsage]
    assert events == []


# ── _map_messages ────────────────────────────────────────────────────────────


def test_map_messages_system_prompt() -> None:
    msgs = [ModelRequest(parts=[SystemPromptPart(content="Be helpful")])]
    result = _map_messages(msgs)
    assert result == [{"role": "system", "content": "Be helpful"}]


def test_map_messages_user_prompt_str() -> None:
    msgs = [ModelRequest(parts=[UserPromptPart(content="Hello")])]
    result = _map_messages(msgs)
    assert result == [{"role": "user", "content": "Hello"}]


def test_map_messages_tool_return() -> None:
    msgs = [ModelRequest(parts=[ToolReturnPart(tool_name="t", content="result", tool_call_id="id1")])]
    result = _map_messages(msgs)
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "id1"


def test_map_messages_retry_prompt_no_tool() -> None:
    msgs = [ModelRequest(parts=[RetryPromptPart(content="retry", tool_name=None)])]
    result = _map_messages(msgs)
    assert result[0]["role"] == "user"


def test_map_messages_retry_prompt_with_tool() -> None:
    msgs = [ModelRequest(parts=[RetryPromptPart(content="err", tool_name="t", tool_call_id="id2")])]
    result = _map_messages(msgs)
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "id2"


def test_map_messages_model_response_text() -> None:
    msgs = [ModelResponse(parts=[TextPart(content="response")], model_name="gpt-4o")]
    result = _map_messages(msgs)
    assert result[0]["role"] == "assistant"
    assert result[0]["content"] == "response"


def test_map_messages_model_response_tool_call() -> None:
    msgs = [ModelResponse(parts=[ToolCallPart(tool_name="t", args='{"x":1}', tool_call_id="tc1")], model_name="gpt-4o")]
    result = _map_messages(msgs)
    assert result[0]["role"] == "assistant"
    assert len(result[0]["tool_calls"]) == 1
    assert result[0]["tool_calls"][0]["id"] == "tc1"


def test_map_messages_thinking_part_skipped() -> None:
    msgs = [ModelResponse(parts=[ThinkingPart(content="thinking..."), TextPart(content="answer")], model_name="gpt-4o")]
    result = _map_messages(msgs)
    assert result[0]["content"] == "answer"
    assert "tool_calls" not in result[0]


# ── _strip_ref_siblings ──────────────────────────────────────────────────────


def test_strip_ref_siblings_removes_siblings() -> None:
    schema = {"$ref": "#/def/Foo", "description": "should be removed"}
    assert _strip_ref_siblings(schema) == {"$ref": "#/def/Foo"}


def test_strip_ref_siblings_recurses_into_dict() -> None:
    schema = {"properties": {"x": {"$ref": "#/def/Bar", "title": "X"}}}
    result = _strip_ref_siblings(schema)
    assert result == {"properties": {"x": {"$ref": "#/def/Bar"}}}


def test_strip_ref_siblings_recurses_into_list() -> None:
    schema = [{"$ref": "#/def/A", "extra": "junk"}, "plain"]
    result = _strip_ref_siblings(schema)
    assert result == [{"$ref": "#/def/A"}, "plain"]


def test_strip_ref_siblings_leaves_plain_value() -> None:
    assert _strip_ref_siblings("string") == "string"


# ── _sanitize_tools_for_moonshot ─────────────────────────────────────────────


def test_sanitize_tools_for_moonshot() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "foo",
                "parameters": {"$ref": "#/def/A", "description": "remove me"},
            },
        }
    ]
    result = _sanitize_tools_for_moonshot(tools)
    assert result[0]["function"]["parameters"] == {"$ref": "#/def/A"}


def test_map_messages_unknown_request_part_skipped() -> None:
    """UnknownPart type in ModelRequest — no output (falls through elif chain)."""
    msgs = [ModelRequest(parts=[InstructionPart(content="instruction")])]
    result = _map_messages(msgs)
    assert result == []


def test_map_messages_unknown_message_type_skipped() -> None:
    """Neither ModelRequest nor ModelResponse — skipped silently."""
    msgs: list[Any] = ["not-a-message"]
    result = _map_messages(msgs)
    assert result == []


def test_map_messages_unknown_response_part_skipped() -> None:
    """ModelResponse with BuiltinToolCallPart — falls through elif chain, no tool_calls entry."""
    msgs = [ModelResponse(parts=[BuiltinToolCallPart(tool_name="t", args={}, tool_call_id="1")], model_name="m")]
    result = _map_messages(msgs)
    assert result[0]["role"] == "assistant"
    assert "tool_calls" not in result[0]


# ── _get_tools ───────────────────────────────────────────────────────────────


def test_get_tools_empty() -> None:
    params = _make_params()
    assert _get_tools(params) == []


def test_get_tools_with_tools() -> None:
    params = _make_params(["search", "execute"])
    tools = _get_tools(params)
    assert len(tools) == 2
    names = {t["function"]["name"] for t in tools}
    assert names == {"search", "execute"}


@pytest.mark.skipif(
    not _litellm_live_enabled(),
    reason="Set LITELLM_API_BASE or PYDANTIC_DEEP_LITELLM_LIVE=1 for live LiteLLM test",
)
async def test_litellm_live_agent_roundtrip() -> None:
    """One real completion via LiteLLM (proxy URL and/or OAuth2 per your LiteLLM config)."""
    model_spec = os.environ.get(
        "PYDANTIC_DEEP_TEST_LITELLM_MODEL",
        f"litellm:{DEFAULT_GITHUB_COPILOT_LITELLM_MODEL}",
    )
    agent = create_deep_agent(
        model=infer_litellm_model(model_spec),
        include_todo=False,
        include_filesystem=False,
        include_subagents=False,
        include_skills=False,
        include_plan=False,
        cost_tracking=False,
        context_manager=False,
        include_history_archive=False,
    )
    deps = create_default_deps()
    result = await agent.run(
        "Reply with the single word OK and nothing else.",
        deps=deps,
    )
    assert "ok" in result.output.lower()

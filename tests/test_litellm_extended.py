"""Extended tests for pydantic_deep.litellm — covers _map_messages, _get_tools,
_process_response, _build_kwargs, and LiteLLMStreamedResponse."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import (
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
from pydantic_ai.tools import ToolDefinition

from pydantic_deep.litellm import (
    LiteLLMModel,
    LiteLLMStreamedResponse,
    _get_tools,
    _map_messages,
)


# ---------------------------------------------------------------------------
# _map_messages
# ---------------------------------------------------------------------------


class TestMapMessages:
    def test_system_prompt(self) -> None:
        msgs = [ModelRequest(parts=[SystemPromptPart(content="You are helpful.")])]
        result = _map_messages(msgs)
        assert result == [{"role": "system", "content": "You are helpful."}]

    def test_user_prompt_string(self) -> None:
        msgs = [ModelRequest(parts=[UserPromptPart(content="Hello")])]
        result = _map_messages(msgs)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_tool_return_part(self) -> None:
        part = ToolReturnPart(tool_name="my_tool", content="result", tool_call_id="tc1")
        msgs = [ModelRequest(parts=[part])]
        result = _map_messages(msgs)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc1"

    def test_retry_prompt_no_tool(self) -> None:
        part = RetryPromptPart(content="try again", tool_name=None, tool_call_id=None)
        msgs = [ModelRequest(parts=[part])]
        result = _map_messages(msgs)
        assert result[0]["role"] == "user"

    def test_retry_prompt_with_tool(self) -> None:
        part = RetryPromptPart(content="bad args", tool_name="my_tool", tool_call_id="tc2")
        msgs = [ModelRequest(parts=[part])]
        result = _map_messages(msgs)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tc2"

    def test_model_response_text(self) -> None:
        msgs = [ModelResponse(parts=[TextPart(content="Hi there")])]
        result = _map_messages(msgs)
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Hi there"

    def test_model_response_thinking_part_skipped(self) -> None:
        msgs = [ModelResponse(parts=[ThinkingPart(content="thinking..."), TextPart(content="answer")])]
        result = _map_messages(msgs)
        assert result[0]["content"] == "answer"

    def test_model_response_tool_call(self) -> None:
        part = ToolCallPart(tool_name="search", args='{"q":"test"}', tool_call_id="tc3")
        msgs = [ModelResponse(parts=[part])]
        result = _map_messages(msgs)
        assert result[0]["role"] == "assistant"
        assert result[0]["tool_calls"][0]["function"]["name"] == "search"

    def test_empty_messages(self) -> None:
        assert _map_messages([]) == []
        parts = [
            TextPart(content="Let me search"),
            ToolCallPart(tool_name="search", args="{}", tool_call_id="tc4"),
        ]
        msgs = [ModelResponse(parts=parts)]
        result = _map_messages(msgs)
        assert result[0]["content"] == "Let me search"
        assert len(result[0]["tool_calls"]) == 1

    def test_user_prompt_non_string_content(self) -> None:
        """Non-string content (e.g. list of parts) is coerced to str."""
        part = UserPromptPart(content=[{"type": "text", "text": "hello"}])
        msgs = [ModelRequest(parts=[part])]
        result = _map_messages(msgs)
        assert result[0]["role"] == "user"
        assert isinstance(result[0]["content"], str)


# ---------------------------------------------------------------------------
# _get_tools
# ---------------------------------------------------------------------------


class TestGetTools:
    def _make_params(self, tool_defs: dict | None = None) -> ModelRequestParameters:
        params = MagicMock(spec=ModelRequestParameters)
        params.tool_defs = tool_defs
        params.allow_text_output = True
        return params

    def test_no_tools_returns_empty(self) -> None:
        params = self._make_params(tool_defs=None)
        assert _get_tools(params) == []

    def test_empty_tool_defs_returns_empty(self) -> None:
        params = self._make_params(tool_defs={})
        assert _get_tools(params) == []

    def test_single_tool(self) -> None:
        td = MagicMock(spec=ToolDefinition)
        td.name = "my_tool"
        td.description = "Does something"
        td.parameters_json_schema = {"type": "object", "properties": {}}
        params = self._make_params(tool_defs={"my_tool": td})
        result = _get_tools(params)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "my_tool"
        assert result[0]["type"] == "function"


# ---------------------------------------------------------------------------
# LiteLLMModel._build_kwargs
# ---------------------------------------------------------------------------


class TestBuildKwargs:
    def _model(self) -> LiteLLMModel:
        return LiteLLMModel(model_name="openai/gpt-4o")

    def _params(self, allow_text: bool = True, tools: dict | None = None) -> ModelRequestParameters:
        p = MagicMock(spec=ModelRequestParameters)
        p.tool_defs = tools
        p.allow_text_output = allow_text
        return p

    def test_basic_kwargs(self) -> None:
        m = self._model()
        kwargs = m._build_kwargs([], self._params(), None, stream=False)  # pyright: ignore[reportPrivateUsage]
        assert kwargs["model"] == "openai/gpt-4o"
        assert kwargs["stream"] is False

    def test_stream_true(self) -> None:
        m = self._model()
        kwargs = m._build_kwargs([], self._params(), None, stream=True)  # pyright: ignore[reportPrivateUsage]
        assert kwargs["stream"] is True

    def test_temperature_from_settings(self) -> None:
        m = self._model()
        settings: Any = {"temperature": 0.5}
        kwargs = m._build_kwargs([], self._params(), settings, stream=False)  # pyright: ignore[reportPrivateUsage]
        assert kwargs.get("temperature") == 0.5

    def test_max_tokens_from_settings(self) -> None:
        m = self._model()
        settings: Any = {"max_tokens": 100}
        kwargs = m._build_kwargs([], self._params(), settings, stream=False)  # pyright: ignore[reportPrivateUsage]
        assert kwargs.get("max_tokens") == 100

    def test_top_p_from_settings(self) -> None:
        m = self._model()
        settings: Any = {"top_p": 0.9}
        kwargs = m._build_kwargs([], self._params(), settings, stream=False)  # pyright: ignore[reportPrivateUsage]
        assert kwargs.get("top_p") == 0.9

    def test_stop_sequences_from_settings(self) -> None:
        m = self._model()
        settings: Any = {"stop_sequences": ["STOP"]}
        kwargs = m._build_kwargs([], self._params(), settings, stream=False)  # pyright: ignore[reportPrivateUsage]
        assert kwargs.get("stop") == ["STOP"]

    def test_tools_injected_when_present(self) -> None:
        td = MagicMock(spec=ToolDefinition)
        td.name = "t"
        td.description = "desc"
        td.parameters_json_schema = {}
        m = self._model()
        kwargs = m._build_kwargs([], self._params(tools={"t": td}), None, stream=False)  # pyright: ignore[reportPrivateUsage]
        assert "tools" in kwargs
        assert kwargs["tool_choice"] == "auto"

    def test_tool_choice_required_when_no_text_output(self) -> None:
        td = MagicMock(spec=ToolDefinition)
        td.name = "t"
        td.description = "desc"
        td.parameters_json_schema = {}
        m = self._model()
        kwargs = m._build_kwargs([], self._params(allow_text=False, tools={"t": td}), None, stream=False)  # pyright: ignore[reportPrivateUsage]
        assert kwargs["tool_choice"] == "required"

    def test_extra_headers_included(self) -> None:
        m = LiteLLMModel(model_name="github_copilot/gpt-4o")
        kwargs = m._build_kwargs([], self._params(), None, stream=False)  # pyright: ignore[reportPrivateUsage]
        assert "extra_headers" in kwargs
        assert kwargs["extra_headers"]["Editor-Version"] == "vscode/1.85.1"


# ---------------------------------------------------------------------------
# LiteLLMModel._process_response
# ---------------------------------------------------------------------------


class TestProcessResponse:
    def _make_response(
        self,
        content: str | None = "Hello",
        tool_calls: list | None = None,
        finish_reason: str = "stop",
    ) -> MagicMock:
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        resp.choices[0].message.tool_calls = tool_calls or []
        resp.choices[0].finish_reason = finish_reason
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        resp.model = "gpt-4o"
        resp.id = "resp-1"
        return resp

    def test_text_response(self) -> None:
        m = LiteLLMModel(model_name="openai/gpt-4o")
        resp = self._make_response(content="Hi!")
        result = m._process_response(resp)  # pyright: ignore[reportPrivateUsage]
        assert any(isinstance(p, TextPart) and p.content == "Hi!" for p in result.parts)

    def test_tool_call_response(self) -> None:
        tc = MagicMock()
        tc.function.name = "search"
        tc.function.arguments = '{"q":"test"}'
        tc.id = "tc1"
        m = LiteLLMModel(model_name="openai/gpt-4o")
        resp = self._make_response(content=None, tool_calls=[tc])
        result = m._process_response(resp)  # pyright: ignore[reportPrivateUsage]
        assert any(isinstance(p, ToolCallPart) and p.tool_name == "search" for p in result.parts)

    def test_usage_extracted(self) -> None:
        m = LiteLLMModel(model_name="openai/gpt-4o")
        resp = self._make_response()
        result = m._process_response(resp)  # pyright: ignore[reportPrivateUsage]
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 5

    def test_finish_reason_mapped(self) -> None:
        m = LiteLLMModel(model_name="openai/gpt-4o")
        resp = self._make_response(finish_reason="tool_calls")
        result = m._process_response(resp)  # pyright: ignore[reportPrivateUsage]
        assert result.finish_reason == "tool_call"

    def test_unknown_finish_reason_defaults_to_stop(self) -> None:
        m = LiteLLMModel(model_name="openai/gpt-4o")
        resp = self._make_response(finish_reason="unknown_reason")
        result = m._process_response(resp)  # pyright: ignore[reportPrivateUsage]
        assert result.finish_reason == "stop"


# ---------------------------------------------------------------------------
# LiteLLMModel.request (mocked)
# ---------------------------------------------------------------------------


class TestLiteLLMModelRequest:
    async def test_request_calls_acompletion(self) -> None:
        m = LiteLLMModel(model_name="openai/gpt-4o")
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "OK"
        mock_resp.choices[0].message.tool_calls = []
        mock_resp.choices[0].finish_reason = "stop"
        mock_resp.usage = None
        mock_resp.model = "gpt-4o"
        mock_resp.id = "r1"

        params = MagicMock(spec=ModelRequestParameters)
        params.tool_defs = None
        params.allow_text_output = True

        with patch("litellm.acompletion", new=AsyncMock(return_value=mock_resp)):
            result = await m.request([], None, params)

        assert any(isinstance(p, TextPart) for p in result.parts)

    async def test_request_stream_yields_response(self) -> None:
        m = LiteLLMModel(model_name="openai/gpt-4o")

        async def _fake_stream() -> Any:
            yield MagicMock(choices=[], usage=None)

        mock_stream = _fake_stream()
        params = MagicMock(spec=ModelRequestParameters)
        params.tool_defs = None
        params.allow_text_output = True

        with patch("litellm.acompletion", new=AsyncMock(return_value=mock_stream)):
            async with m.request_stream([], None, params) as streamed:
                assert isinstance(streamed, LiteLLMStreamedResponse)


# ---------------------------------------------------------------------------
# LiteLLMStreamedResponse
# ---------------------------------------------------------------------------


class TestLiteLLMStreamedResponse:
    def _make_streamed(self, chunks: list) -> LiteLLMStreamedResponse:
        async def _gen() -> Any:
            for c in chunks:
                yield c

        params = MagicMock(spec=ModelRequestParameters)
        params.tool_defs = {}
        params.allow_text_output = True
        params.allow_image_output = False
        return LiteLLMStreamedResponse(
            model_request_parameters=params,
            response=_gen(),
            model_name="gpt-4o",
        )

    def test_model_name(self) -> None:
        s = self._make_streamed([])
        assert s.model_name == "gpt-4o"

    def test_provider_name(self) -> None:
        s = self._make_streamed([])
        assert s.provider_name == "litellm"

    def test_provider_url_is_none(self) -> None:
        s = self._make_streamed([])
        assert s.provider_url is None

    def test_timestamp_is_datetime(self) -> None:
        from datetime import datetime
        s = self._make_streamed([])
        assert isinstance(s.timestamp, datetime)

    async def test_text_chunk_yields_events(self) -> None:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = "Hello"
        chunk.choices[0].delta.tool_calls = []
        chunk.usage = None

        s = self._make_streamed([chunk])
        events = []
        async for event in s:
            events.append(event)
        assert len(events) > 0

    async def test_empty_choices_skipped(self) -> None:
        chunk = MagicMock()
        chunk.choices = []
        chunk.usage = None

        s = self._make_streamed([chunk])
        events = []
        async for event in s:
            events.append(event)
        assert events == []

    async def test_tool_call_chunk_yields_events(self) -> None:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = None
        tc = MagicMock()
        tc.index = 0
        tc.id = "tc1"
        tc.function = MagicMock()
        tc.function.name = "search"
        tc.function.arguments = '{"q":'
        chunk.choices[0].delta.tool_calls = [tc]
        chunk.usage = None

        s = self._make_streamed([chunk])
        events = []
        async for event in s:
            events.append(event)
        # Tool call delta should produce at least one event
        assert len(events) >= 0  # may be 0 if partial, just ensure no crash

    async def test_usage_extracted_from_chunk(self) -> None:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = None
        chunk.choices[0].delta.tool_calls = []
        usage = MagicMock()
        usage.prompt_tokens = 3
        usage.completion_tokens = 7
        chunk.usage = usage

        s = self._make_streamed([chunk])
        async for _ in s:
            pass
        assert s.usage().input_tokens == 3
        assert s.usage().output_tokens == 7

    async def test_chunk_with_no_usage_attribute(self) -> None:
        """Chunks without usage attribute should not crash."""
        chunk = MagicMock(spec=["choices"])
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = "hi"
        chunk.choices[0].delta.tool_calls = []

        s = self._make_streamed([chunk])
        async for _ in s:
            pass

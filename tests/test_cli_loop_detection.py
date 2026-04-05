"""Tests for CLI loop detection capability."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RunUsage

from apps.cli.middleware.loop_detection import (
    LoopDetectionMiddleware,
    _hash_args,
)

_MODEL = TestModel()


def _ctx() -> RunContext[Any]:
    return RunContext(deps=None, model=_MODEL, usage=RunUsage())


def _call(tool: str) -> ToolCallPart:
    return ToolCallPart(tool_name=tool, args={}, tool_call_id="t")


def _td(tool: str) -> ToolDefinition:
    return ToolDefinition(name=tool, description="")


async def _execute(mw: LoopDetectionMiddleware, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Helper to call before_tool_execute with proper args."""
    return await mw.before_tool_execute(_ctx(), call=_call(tool), tool_def=_td(tool), args=args)


class TestHashArgs:
    """Tests for _hash_args()."""

    def test_same_args_produce_same_hash(self) -> None:
        args = {"command": "python test.py", "timeout": 30}
        assert _hash_args(args) == _hash_args(args)

    def test_different_args_produce_different_hash(self) -> None:
        args1 = {"command": "python test.py"}
        args2 = {"command": "python other.py"}
        assert _hash_args(args1) != _hash_args(args2)

    def test_order_independent(self) -> None:
        args1 = {"a": 1, "b": 2}
        args2 = {"b": 2, "a": 1}
        assert _hash_args(args1) == _hash_args(args2)

    def test_handles_non_serializable(self) -> None:
        args: dict[str, Any] = {"obj": object()}
        result = _hash_args(args)
        assert isinstance(result, str)


class TestLoopDetectionMiddleware:
    """Tests for LoopDetectionMiddleware."""

    @pytest.fixture()
    def middleware(self) -> LoopDetectionMiddleware:
        return LoopDetectionMiddleware(max_repeats=3, window_size=15)

    async def test_allows_first_call(self, middleware: LoopDetectionMiddleware) -> None:
        result = await _execute(middleware, "execute", {"command": "python test.py"})
        assert result == {"command": "python test.py"}

    async def test_allows_different_calls(self, middleware: LoopDetectionMiddleware) -> None:
        for i in range(5):
            result = await _execute(middleware, "execute", {"command": f"python test{i}.py"})
            assert isinstance(result, dict)

    async def test_allows_up_to_max_repeats(self, middleware: LoopDetectionMiddleware) -> None:
        args = {"command": "python test.py"}
        for i in range(3):
            result = await _execute(middleware, "execute", args)
            assert isinstance(result, dict), f"Call {i + 1} should be allowed"

    async def test_denies_after_max_repeats(self, middleware: LoopDetectionMiddleware) -> None:
        args = {"command": "python test.py"}
        for _ in range(3):
            await _execute(middleware, "execute", args)

        with pytest.raises(ModelRetry, match="Loop detected"):
            await _execute(middleware, "execute", args)

    async def test_different_tools_tracked_separately(
        self, middleware: LoopDetectionMiddleware
    ) -> None:
        args = {"path": "/test"}
        for _ in range(3):
            await _execute(middleware, "read_file", args)

        result = await _execute(middleware, "write_file", args)
        assert isinstance(result, dict)

    async def test_same_tool_different_args_tracked_separately(
        self, middleware: LoopDetectionMiddleware
    ) -> None:
        for _ in range(3):
            await _execute(middleware, "execute", {"command": "python a.py"})

        result = await _execute(middleware, "execute", {"command": "python b.py"})
        assert isinstance(result, dict)

    async def test_window_size_limits_history(self) -> None:
        middleware = LoopDetectionMiddleware(max_repeats=3, window_size=5)
        for i in range(10):
            await _execute(middleware, "read_file", {"path": f"/file{i}"})

        args = {"command": "python test.py"}
        for _ in range(3):
            result = await _execute(middleware, "execute", args)
            assert isinstance(result, dict)

    async def test_custom_max_repeats(self) -> None:
        middleware = LoopDetectionMiddleware(max_repeats=1)
        args = {"command": "test"}

        result = await _execute(middleware, "execute", args)
        assert isinstance(result, dict)

        with pytest.raises(ModelRetry):
            await _execute(middleware, "execute", args)

    async def test_deny_reason_includes_tool_name(
        self, middleware: LoopDetectionMiddleware
    ) -> None:
        args = {"command": "python test.py"}
        for _ in range(3):
            await _execute(middleware, "execute", args)

        with pytest.raises(ModelRetry, match="execute") as exc_info:
            await _execute(middleware, "execute", args)
        assert "different approach" in str(exc_info.value)

"""Tests for moonshot, _backend, and bridge coverage."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.usage import RunUsage

from pydantic_deep import DeepAgentDeps
from pydantic_deep._backend import read_backend_bytes
from pydantic_deep.capabilities.bridge import BridgeCapability, current_bridge_sender


# ── moonshot ─────────────────────────────────────────────────────────────────


def test_infer_moonshot_model_with_prefix() -> None:
    from pydantic_ai.models.openai import OpenAIChatModel

    from pydantic_deep.moonshot import infer_moonshot_model

    with patch.dict("os.environ", {"MOONSHOT_API_KEY": "test-key"}):
        m = infer_moonshot_model("moonshot:kimi-k2.6")
    assert isinstance(m, OpenAIChatModel)
    assert m.model_name == "kimi-k2.6"


def test_infer_moonshot_model_without_prefix() -> None:
    from pydantic_ai.models.openai import OpenAIChatModel

    from pydantic_deep.moonshot import infer_moonshot_model

    with patch.dict("os.environ", {"MOONSHOT_API_KEY": "test-key"}):
        m = infer_moonshot_model("kimi-k2.6")
    assert isinstance(m, OpenAIChatModel)
    assert m.model_name == "kimi-k2.6"


def test_moonshot_model_fixes_temperature_kimi_k2() -> None:
    from pydantic_deep.moonshot import moonshot_model_fixes_temperature

    assert moonshot_model_fixes_temperature("kimi-k2.6") is True
    assert moonshot_model_fixes_temperature("moonshot:kimi-k2.6") is True


def test_moonshot_model_fixes_temperature_other() -> None:
    from pydantic_deep.moonshot import moonshot_model_fixes_temperature

    assert moonshot_model_fixes_temperature("moonshot:moonshot-v1-8k") is False
    assert moonshot_model_fixes_temperature("moonshot-v1-8k") is False


# ── _backend ─────────────────────────────────────────────────────────────────


class _ModernBackend:
    """Backend with new read_bytes API."""

    def read_bytes(self, path: str) -> bytes:
        return b"modern"


class _LegacyBackend:
    """Backend with old _read_bytes API."""

    def _read_bytes(self, path: str) -> bytes:
        return b"legacy"


class _NoReadBackend:
    """Backend that supports neither bytes-reading method."""


def test_read_backend_bytes_modern() -> None:
    b = _ModernBackend()
    assert read_backend_bytes(b, "/file.txt") == b"modern"


def test_read_backend_bytes_legacy_fallback() -> None:
    b = _LegacyBackend()
    assert read_backend_bytes(b, "/file.txt") == b"legacy"


def test_read_backend_bytes_raises_when_unsupported() -> None:
    b = _NoReadBackend()
    with pytest.raises(AttributeError, match="_NoReadBackend does not support reading bytes"):
        read_backend_bytes(b, "/file.txt")


# ── BridgeCapability ──────────────────────────────────────────────────────────

_TEST_MODEL = TestModel()


def _make_ctx() -> RunContext[DeepAgentDeps]:
    from pydantic_ai_backends import StateBackend

    deps = DeepAgentDeps(backend=StateBackend())
    return RunContext(deps=deps, model=_TEST_MODEL, usage=RunUsage())


def _make_call(name: str = "write") -> ToolCallPart:
    return ToolCallPart(tool_name=name, args="{}", tool_call_id="tc-1")


def _make_td(name: str = "write") -> ToolDefinition:
    return ToolDefinition(name=name, description="")


def test_bridge_capability_get_toolset() -> None:
    send_fn: Any = MagicMock()
    cap = BridgeCapability(send_fn=send_fn)
    toolset = cap.get_toolset()
    assert toolset is cap._toolset  # pyright: ignore[reportPrivateUsage]


@pytest.mark.anyio
async def test_after_tool_execute_notify_writes_false() -> None:
    """notify_writes=False → returns result unchanged without calling send_fn."""
    send_fn: Any = MagicMock()
    cap = BridgeCapability(send_fn=send_fn, notify_writes=False)
    ctx = _make_ctx()
    result = await cap.after_tool_execute(
        ctx,
        call=_make_call("write"),
        tool_def=_make_td("write"),
        args={"file_path": "/foo.txt"},
        result="ok",
    )
    assert result == "ok"
    send_fn.assert_not_called()


@pytest.mark.anyio
async def test_after_tool_execute_wrong_tool_name() -> None:
    """Tool name mismatch → returns result unchanged."""
    send_fn: Any = MagicMock()
    cap = BridgeCapability(send_fn=send_fn, write_tool_name="write")
    ctx = _make_ctx()
    result = await cap.after_tool_execute(
        ctx,
        call=_make_call("read"),
        tool_def=_make_td("read"),
        args={"file_path": "/foo.txt"},
        result="content",
    )
    assert result == "content"
    send_fn.assert_not_called()


@pytest.mark.anyio
async def test_after_tool_execute_no_bridge_sender() -> None:
    """No current_bridge_sender → returns result unchanged."""
    send_fn: Any = MagicMock()
    cap = BridgeCapability(send_fn=send_fn)
    ctx = _make_ctx()
    token = current_bridge_sender.set(None)
    try:
        result = await cap.after_tool_execute(
            ctx,
            call=_make_call("write"),
            tool_def=_make_td("write"),
            args={"file_path": "/foo.txt"},
            result="ok",
        )
    finally:
        current_bridge_sender.reset(token)
    assert result == "ok"
    send_fn.assert_not_called()


@pytest.mark.anyio
async def test_after_tool_execute_no_file_path() -> None:
    """No file_path in args → returns result unchanged."""
    send_fn: Any = MagicMock()
    cap = BridgeCapability(send_fn=send_fn)
    ctx = _make_ctx()
    token = current_bridge_sender.set("user-123")
    try:
        result = await cap.after_tool_execute(
            ctx,
            call=_make_call("write"),
            tool_def=_make_td("write"),
            args={},
            result="ok",
        )
    finally:
        current_bridge_sender.reset(token)
    assert result == "ok"
    send_fn.assert_not_called()


@pytest.mark.anyio
async def test_after_tool_execute_file_exists(tmp_path: Any) -> None:
    """File exists → send_fn called with size notification."""
    sent: list[tuple[str, str]] = []

    def send_fn(uid: str, text: str) -> None:
        sent.append((uid, text))

    cap = BridgeCapability(send_fn=send_fn)
    ctx = _make_ctx()
    fp = tmp_path / "output.txt"
    fp.write_bytes(b"hello world")

    token = current_bridge_sender.set("user-abc")
    try:
        result = await cap.after_tool_execute(
            ctx,
            call=_make_call("write"),
            tool_def=_make_td("write"),
            args={"file_path": str(fp)},
            result="ok",
        )
    finally:
        current_bridge_sender.reset(token)

    assert result == "ok"
    assert len(sent) == 1
    uid, msg = sent[0]
    assert uid == "user-abc"
    assert "output.txt" in msg


@pytest.mark.anyio
async def test_after_tool_execute_file_not_exists() -> None:
    """File doesn't exist → os.path.isfile returns False, send_fn not called."""
    sent: list[Any] = []

    def send_fn(uid: str, text: str) -> None:
        sent.append((uid, text))

    cap = BridgeCapability(send_fn=send_fn)
    ctx = _make_ctx()

    token = current_bridge_sender.set("user-abc")
    try:
        result = await cap.after_tool_execute(
            ctx,
            call=_make_call("write"),
            tool_def=_make_td("write"),
            args={"file_path": "/nonexistent/path/file.txt"},
            result="ok",
        )
    finally:
        current_bridge_sender.reset(token)

    assert result == "ok"
    assert sent == []


@pytest.mark.anyio
async def test_after_tool_execute_oserror_silenced(tmp_path: Any) -> None:
    """OSError from os.path.getsize is caught silently."""
    sent: list[Any] = []

    def send_fn(uid: str, text: str) -> None:
        sent.append((uid, text))

    cap = BridgeCapability(send_fn=send_fn)
    ctx = _make_ctx()
    fp = tmp_path / "output.txt"
    fp.write_bytes(b"data")

    token = current_bridge_sender.set("user-abc")
    try:
        with patch("os.path.getsize", side_effect=OSError("permission denied")):
            result = await cap.after_tool_execute(
                ctx,
                call=_make_call("write"),
                tool_def=_make_td("write"),
                args={"file_path": str(fp)},
                result="ok",
            )
    finally:
        current_bridge_sender.reset(token)

    assert result == "ok"
    assert sent == []

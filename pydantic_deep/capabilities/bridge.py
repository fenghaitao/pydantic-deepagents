"""Bridge capability for pydantic-deep agents.

Wires the agent's tool lifecycle to an active bridge transport so that:
  - Files written by the agent are notified back to the originating user.
  - The agent can proactively send messages via ``send_bridge_message``.

The capability is transport-agnostic: it receives a ``send_fn(uid, text)``
callable at construction time (WeChat, Telegram, or any other transport).

The current sender is tracked via a ContextVar that the BridgeRunner sets
at the start of each agent turn, so each asyncio task carries its own sender
identity even when multiple users are processed concurrently.

Example::

    from pydantic_deep.capabilities.bridge import BridgeCapability, current_bridge_sender
    from apps.bridge.wechat import wx_send

    send_fn = lambda uid, text: wx_send(uid, text, token, base_url)
    capability = BridgeCapability(send_fn=send_fn)

    agent, deps = create_cli_agent(
        ...
        capabilities=[capability],
    )
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset
from pydantic_ai.tools import ToolDefinition

#: Set by BridgeRunner._execute() at the start of each agent turn.
#: Isolates sender identity per-asyncio-task so concurrent users don't bleed.
current_bridge_sender: ContextVar[str | None] = ContextVar("bridge_sender", default=None)

SendFn = Callable[[str, str], None]  # (uid, text) → None


class _BridgeSendToolset(FunctionToolset[Any]):
    """Toolset exposing send_bridge_message to the agent."""

    def __init__(self, send_fn: SendFn) -> None:
        super().__init__()
        self._send_fn = send_fn

        @self.tool(
            description=(
                "Send a message back to the user over the active bridge (WeChat, Telegram, etc.). "
                "Use this to proactively notify the user of progress, results, or ask questions. "
                "The `recipient` must be the sender ID of the current conversation "
                "(available as the implicit context — leave blank to reply to the current user, "
                "or pass an explicit uid to message a different contact)."
            )
        )
        async def send_bridge_message(
            ctx: RunContext[Any],
            recipient: str,
            message: str,
        ) -> str:
            """Send a message to a bridge user.

            Args:
                recipient: The user/contact ID to message. Pass the current sender's uid
                    to reply in the active conversation.
                message: Text message to send (max 2000 chars per WeChat message).

            Returns:
                Confirmation string.
            """
            uid = recipient.strip() or current_bridge_sender.get() or ""
            if not uid:
                return "Error: no recipient specified and no active bridge sender."
            try:
                await asyncio.to_thread(self._send_fn, uid, message)
                return f"Message sent to {uid}."
            except Exception as exc:
                return f"Failed to send message: {exc}"


@dataclass
class BridgeCapability(AbstractCapability[Any]):
    """Capability that wires file writes and proactive messaging to a bridge transport.

    Args:
        send_fn: Transport-specific send function ``(uid: str, text: str) -> None``.
            For WeChat: ``lambda uid, text: wx_send(uid, text, token, base_url)``
        notify_writes: When True (default), sends a notification when the agent
            writes a file. The notification includes the file path and size.
        write_tool_name: Name of the write tool to intercept (default: ``"write"``).
    """

    send_fn: SendFn
    notify_writes: bool = True
    write_tool_name: str = "write"
    _toolset: _BridgeSendToolset = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._toolset = _BridgeSendToolset(self.send_fn)

    def get_toolset(self) -> AbstractToolset[Any]:
        return self._toolset

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        """Notify the current bridge user when the agent writes a file."""
        if not self.notify_writes:
            return result
        if call.tool_name != self.write_tool_name:
            return result

        uid = current_bridge_sender.get()
        if not uid:
            return result

        file_path = str(args.get("file_path") or args.get("path") or "").strip()
        if not file_path:
            return result

        # Best-effort size reporting from real filesystem
        try:
            if os.path.isfile(file_path):
                size_kb = os.path.getsize(file_path) / 1024
                fname = os.path.basename(file_path)
                # Offload the blocking transport send so the event loop is not stalled.
                await asyncio.to_thread(
                    self.send_fn,
                    uid,
                    f"📄 Wrote `{fname}` ({size_kb:.1f} KB)\nPath: `{file_path}`",
                )
        except OSError:
            pass

        return result

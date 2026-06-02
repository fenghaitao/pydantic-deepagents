"""WeChat bridge controller for the TUI.

Drives the ``apps.bridge`` WeChat integration from inside the Textual app:

  * ``/wechat on``  — authenticate (QR scan if needed) and start the long-poll
    loop, processing inbound WeChat messages with a dedicated non-interactive
    agent.
  * ``/wechat off`` — stop the poll loop and release the single-instance lock.

The WeChat conversation is *mirrored* into the chat view: inbound user
messages and the agent's outbound replies both appear in the TUI, so the
operator can watch the conversation live. ``apps.bridge`` itself is untouched —
this module only wraps its public surface (``qr_login``, ``start_poll``,
``wx_send``, ``WeChatConfig``) and the transport-agnostic ``BridgeRunner``.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.cli.app import DeepApp

#: Saved WeChat credentials live alongside the bridge's own config file so the
#: TUI and ``python -m apps.bridge`` share one login.
_BRIDGE_CONFIG_PATH = Path.home() / ".pydantic-deep" / "bridge.json"


def _load_config() -> dict[str, Any]:
    if _BRIDGE_CONFIG_PATH.exists():
        try:
            return json.loads(_BRIDGE_CONFIG_PATH.read_text())
        except (OSError, ValueError):
            return {}
    return {}


def _save_config(config: dict[str, Any]) -> None:
    _BRIDGE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _BRIDGE_CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))


class WeChatBridgeController:
    """Manages the WeChat bridge lifecycle for a running :class:`DeepApp`."""

    def __init__(self, app: DeepApp) -> None:
        self._app = app
        self._runner: Any | None = None
        self._poll_thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._wx_cfg: Any | None = None

    @property
    def running(self) -> bool:
        return self._poll_thread is not None and self._poll_thread.is_alive()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Authenticate (QR scan if needed) and start the poll loop."""
        from apps.bridge import wechat as wx
        from apps.bridge.runner import BridgeRunner
        from apps.cli.agent import create_cli_agent
        from pydantic_deep.capabilities.bridge import BridgeCapability

        app = self._app

        if self.running:
            app.notify("WeChat bridge is already running.", severity="warning")
            return

        config = _load_config()

        # Single-instance lock (shared with `python -m apps.bridge`).
        acquired, holder = wx._acquire_lock()
        if not acquired:
            app.notify(
                f"WeChat bridge already running elsewhere (pid={holder}).",
                severity="error",
            )
            return

        # Auth precedence: environment token > saved config; QR login otherwise.
        wx_cfg = wx.WeChatConfig.from_env() or wx.WeChatConfig.from_dict(config)
        if wx_cfg is None:
            app.notify("No WeChat token — opening QR login (scan with WeChat)…")
            # Suspend the TUI so the ascii QR code renders on the real terminal.
            success = False
            with app.suspend():
                success = wx.qr_login(config)
            if not success:
                wx._release_lock()
                app.notify("WeChat login failed or timed out.", severity="error")
                return
            _save_config(config)
            wx_cfg = wx.WeChatConfig.from_dict(config)

        if wx_cfg is None:
            wx._release_lock()
            app.notify("WeChat login produced no token.", severity="error")
            return

        self._wx_cfg = wx_cfg
        token, base_url = wx_cfg.token, wx_cfg.base_url

        # Outbound send: deliver to WeChat AND mirror into the chat view.
        # Runs in a worker thread (BridgeRunner offloads sends), so UI updates
        # must hop back onto the app thread via call_from_thread.
        def send_fn(uid: str, text: str) -> None:
            wx.wx_send(uid, text, token, base_url)
            try:
                app.call_from_thread(app.mirror_bridge_outbound, text)
            except Exception:
                pass

        bridge_cap = BridgeCapability(send_fn=send_fn)

        # Dedicated non-interactive agent — WeChat users can't answer approval
        # prompts, and its per-user history stays separate from the TUI session.
        agent, deps = create_cli_agent(
            model=app.model_name or None,
            working_dir=app.working_dir,
            non_interactive=True,
            extra_capabilities=[bridge_cap],
        )
        runner = BridgeRunner(agent=agent, deps=deps, send_fn=send_fn)

        # Wrap on_message to mirror inbound WeChat messages. This runs on the
        # event loop (scheduled via run_coroutine_threadsafe), so direct UI
        # calls are safe here.
        orig_on_message = runner.on_message

        async def on_message(uid: str, text: str) -> None:
            app.mirror_bridge_inbound(uid, text)
            await orig_on_message(uid, text)

        loop = asyncio.get_running_loop()
        stop_event = threading.Event()
        poll_thread = wx.start_poll(
            token=token,
            base_url=base_url,
            on_message=on_message,
            loop=loop,
            stop_event=stop_event,
        )

        self._runner = runner
        self._poll_thread = poll_thread
        self._stop_event = stop_event

        acct = wx_cfg.account_id or "unknown"
        app.notify(
            f"WeChat bridge ON (account: {acct}). Incoming chats appear here.",
            severity="information",
        )

    def stop(self, *, notify: bool = True) -> None:
        """Stop the poll loop, runner, and release the lock."""
        from apps.bridge import wechat as wx

        was_running = self.running
        if self._stop_event is not None:
            self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5)
        if self._runner is not None:
            self._runner.stop()
        wx._release_lock()

        self._runner = None
        self._poll_thread = None
        self._stop_event = None

        if notify:
            if was_running:
                self._app.notify("WeChat bridge OFF.", severity="information")
            else:
                self._app.notify("WeChat bridge is not running.", severity="warning")

    def status_text(self) -> str:
        config = _load_config()
        token = config.get("wechat_token") or os.environ.get("WECHAT_BOT_TOKEN", "")
        if self.running:
            acct = ""
            if self._wx_cfg is not None:
                acct = self._wx_cfg.account_id
            acct = acct or config.get("wechat_account_id", "")
            return f"WeChat bridge: running (account: {acct or 'unknown'})"
        if token:
            return "WeChat bridge: configured but stopped — use /wechat on to start."
        return "WeChat bridge: not authenticated — use /wechat on to scan the QR code."


__all__ = ["WeChatBridgeController"]

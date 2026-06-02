"""Tests for the TUI WeChat bridge controller and /wechat command."""

from __future__ import annotations

import contextlib
import threading
from typing import Any
from unittest.mock import patch

from apps.cli.commands import dispatch_command
from apps.cli.wechat_bridge import WeChatBridgeController, _load_config, _save_config


class _FakeThread:
    def __init__(self, alive: bool = True) -> None:
        self._alive = alive
        self.joined = False

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        self.joined = True
        self._alive = False


class _FakeRunner:
    """Stand-in for BridgeRunner — records on_message calls and stop()."""

    def __init__(self, *_: Any, **__: Any) -> None:
        self.messages: list[tuple[str, str]] = []
        self.stopped = False

    async def on_message(self, uid: str, text: str) -> None:
        self.messages.append((uid, text))

    def stop(self) -> None:
        self.stopped = True


class FakeApp:
    """Minimal stand-in for DeepApp used by the controller."""

    model_name = "moonshot:kimi-k2.6"
    working_dir = "."

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.inbound: list[tuple[str, str]] = []
        self.outbound: list[str] = []
        self.suspended = False
        self.raise_on_thread = False

    def notify(self, message: str, *, severity: str = "information", **_: Any) -> None:
        self.notifications.append((severity, message))

    @contextlib.contextmanager
    def suspend(self):  # type: ignore[no-untyped-def]
        self.suspended = True
        try:
            yield
        finally:
            self.suspended = False

    def call_from_thread(self, fn: Any, *args: Any) -> Any:
        if self.raise_on_thread:
            raise RuntimeError("thread boom")
        return fn(*args)

    def mirror_bridge_inbound(self, sender: str, text: str) -> None:
        self.inbound.append((sender, text))

    def mirror_bridge_outbound(self, text: str) -> None:
        self.outbound.append(text)


# ── config helpers ──────────────────────────────────────────────────────────


def test_load_config_missing(tmp_path) -> None:
    cfg = tmp_path / "bridge.json"
    with patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", cfg):
        assert _load_config() == {}


def test_load_config_corrupt(tmp_path) -> None:
    cfg = tmp_path / "bridge.json"
    cfg.write_text("{not json")
    with patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", cfg):
        assert _load_config() == {}


def test_save_and_load_roundtrip(tmp_path) -> None:
    cfg = tmp_path / "sub" / "bridge.json"
    with patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", cfg):
        _save_config({"wechat_token": "abc"})
        assert _load_config() == {"wechat_token": "abc"}


# ── status ──────────────────────────────────────────────────────────────────


def test_status_not_authenticated(tmp_path) -> None:
    import os

    with patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", tmp_path / "bridge.json"):
        os.environ.pop("WECHAT_BOT_TOKEN", None)
        c = WeChatBridgeController(FakeApp())
        assert "not authenticated" in c.status_text()
        assert c.running is False


def test_status_configured(tmp_path) -> None:
    cfg = tmp_path / "bridge.json"
    with patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", cfg):
        _save_config({"wechat_token": "tok"})
        c = WeChatBridgeController(FakeApp())
        assert "configured but stopped" in c.status_text()


def test_status_running(tmp_path) -> None:
    with patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", tmp_path / "bridge.json"):
        from apps.bridge.wechat import WeChatConfig

        c = WeChatBridgeController(FakeApp())
        c._poll_thread = _FakeThread(alive=True)  # type: ignore[assignment]
        c._wx_cfg = WeChatConfig(token="t", account_id="acct-1")
        assert c.running is True
        assert "running" in c.status_text()
        assert "acct-1" in c.status_text()


# ── start / stop ──────────────────────────────────────────────────────────────


async def test_start_lock_held(tmp_path) -> None:
    app = FakeApp()
    c = WeChatBridgeController(app)
    with (
        patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", tmp_path / "bridge.json"),
        patch("apps.bridge.wechat._acquire_lock", return_value=(False, 999)),
    ):
        await c.start()
    assert any("already running elsewhere" in m for _, m in app.notifications)
    assert c.running is False


async def test_start_with_saved_token(tmp_path) -> None:
    app = FakeApp()
    c = WeChatBridgeController(app)
    fake_thread = _FakeThread(alive=True)
    started: dict[str, Any] = {}
    captured: dict[str, Any] = {}

    def _fake_start_poll(*, token, base_url, on_message, loop, stop_event):  # type: ignore[no-untyped-def]
        started.update(token=token, base_url=base_url, on_message=on_message)
        return fake_thread

    class _CapRec:
        def __init__(self, send_fn: Any) -> None:
            captured["send_fn"] = send_fn

    with (
        patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", tmp_path / "bridge.json"),
        patch(
            "apps.cli.wechat_bridge._load_config",
            return_value={
                "wechat_token": "tok",
                "wechat_base_url": "http://x",
                "wechat_account_id": "acct",
            },
        ),
        patch("apps.bridge.wechat._acquire_lock", return_value=(True, 123)),
        patch("apps.bridge.wechat.start_poll", _fake_start_poll),
        patch("apps.bridge.wechat.wx_send") as wx_send,
        patch("apps.bridge.runner.BridgeRunner", _FakeRunner),
        patch("pydantic_deep.capabilities.bridge.BridgeCapability", _CapRec),
        patch("apps.cli.agent.create_cli_agent", return_value=(object(), object())),
    ):
        await c.start()

        assert c.running is True
        assert started["token"] == "tok"
        assert any("WeChat bridge ON" in m for _, m in app.notifications)

        # Idempotent: starting again warns instead of double-starting.
        await c.start()
        assert any("already running" in m for _, m in app.notifications)

        # The wrapped on_message mirrors inbound, then delegates to the runner.
        await started["on_message"]("user42", "hello")
        assert app.inbound[-1] == ("user42", "hello")
        assert c._runner.messages[-1] == ("user42", "hello")  # type: ignore[union-attr]

        # The send_fn delivers to WeChat AND mirrors the reply into the chat.
        captured["send_fn"]("user42", "reply text")
        wx_send.assert_called_once_with("user42", "reply text", "tok", "http://x")
        assert app.outbound[-1] == "reply text"

        # A failure mirroring to the UI must not break delivery.
        app.raise_on_thread = True
        captured["send_fn"]("user42", "second")  # does not raise
        assert wx_send.call_count == 2


async def test_start_running_without_wx_cfg(tmp_path) -> None:
    """status_text reports running using config account when _wx_cfg is unset."""
    cfg = tmp_path / "bridge.json"
    with patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", cfg):
        _save_config({"wechat_token": "tok", "wechat_account_id": "from-config"})
        c = WeChatBridgeController(FakeApp())
        c._poll_thread = _FakeThread(alive=True)  # type: ignore[assignment]
        c._wx_cfg = None
        assert "from-config" in c.status_text()


async def test_start_qr_login_no_token(tmp_path) -> None:
    """qr_login succeeds but yields no token → release lock and report."""
    app = FakeApp()
    c = WeChatBridgeController(app)
    released = {"called": False}

    with (
        patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", tmp_path / "bridge.json"),
        patch("apps.cli.wechat_bridge._load_config", return_value={}),
        patch("apps.cli.wechat_bridge._save_config"),
        patch("apps.bridge.wechat._acquire_lock", return_value=(True, 1)),
        patch("apps.bridge.wechat.WeChatConfig.from_env", return_value=None),
        patch("apps.bridge.wechat.qr_login", return_value=True),  # but config stays empty
        patch(
            "apps.bridge.wechat._release_lock",
            side_effect=lambda: released.update(called=True),
        ),
    ):
        await c.start()

    assert c.running is False
    assert released["called"] is True
    assert any("produced no token" in m for _, m in app.notifications)


async def test_start_qr_login_success(tmp_path) -> None:
    app = FakeApp()
    c = WeChatBridgeController(app)
    fake_thread = _FakeThread(alive=True)

    def _fake_qr_login(config):  # type: ignore[no-untyped-def]
        config["wechat_token"] = "fresh"
        config["wechat_base_url"] = "http://y"
        config["wechat_account_id"] = "acctQR"
        return True

    with (
        patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", tmp_path / "bridge.json"),
        patch("apps.cli.wechat_bridge._load_config", return_value={}),
        patch("apps.cli.wechat_bridge._save_config"),
        patch("apps.bridge.wechat._acquire_lock", return_value=(True, 1)),
        patch("apps.bridge.wechat.WeChatConfig.from_env", return_value=None),
        patch("apps.bridge.wechat.qr_login", _fake_qr_login),
        patch("apps.bridge.wechat.start_poll", return_value=fake_thread),
        patch("apps.bridge.runner.BridgeRunner", _FakeRunner),
        patch("apps.cli.agent.create_cli_agent", return_value=(object(), object())),
    ):
        await c.start()

    assert app.suspended is False  # suspend exited
    assert c.running is True
    assert any("acctQR" in m for _, m in app.notifications)


async def test_start_qr_login_failure(tmp_path) -> None:
    app = FakeApp()
    c = WeChatBridgeController(app)
    released = {"called": False}

    def _release() -> None:
        released["called"] = True

    with (
        patch("apps.cli.wechat_bridge._BRIDGE_CONFIG_PATH", tmp_path / "bridge.json"),
        patch("apps.cli.wechat_bridge._load_config", return_value={}),
        patch("apps.bridge.wechat._acquire_lock", return_value=(True, 1)),
        patch("apps.bridge.wechat.WeChatConfig.from_env", return_value=None),
        patch("apps.bridge.wechat.qr_login", return_value=False),
        patch("apps.bridge.wechat._release_lock", _release),
    ):
        await c.start()

    assert c.running is False
    assert released["called"] is True
    assert any("login failed" in m.lower() for _, m in app.notifications)


def test_stop_when_running(tmp_path) -> None:
    app = FakeApp()
    c = WeChatBridgeController(app)
    fake_thread = _FakeThread(alive=True)
    c._poll_thread = fake_thread  # type: ignore[assignment]
    c._runner = _FakeRunner()
    c._stop_event = threading.Event()

    with patch("apps.bridge.wechat._release_lock"):
        c.stop()

    assert fake_thread.joined is True
    assert c._runner is None
    assert c._poll_thread is None
    assert any("WeChat bridge OFF" in m for _, m in app.notifications)


def test_stop_when_not_running() -> None:
    app = FakeApp()
    c = WeChatBridgeController(app)
    with patch("apps.bridge.wechat._release_lock"):
        c.stop()
    assert any("not running" in m for _, m in app.notifications)


def test_stop_no_notify() -> None:
    app = FakeApp()
    c = WeChatBridgeController(app)
    with patch("apps.bridge.wechat._release_lock"):
        c.stop(notify=False)
    assert app.notifications == []


# ── /wechat command dispatch ─────────────────────────────────────────────────


class _CmdApp:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.calls: list[str] = []
        controller = self

        class _Ctl:
            async def start(_self) -> None:
                controller.calls.append("start")

            def stop(_self) -> None:
                controller.calls.append("stop")

            def status_text(_self) -> str:
                return "STATUS"

        self.wechat_bridge = _Ctl()

    def notify(self, message: str, *, severity: str = "information", **_: Any) -> None:
        self.notifications.append((severity, message))


async def test_dispatch_wechat_on() -> None:
    app = _CmdApp()
    await dispatch_command(app, "/wechat on")  # type: ignore[arg-type]
    assert app.calls == ["start"]


async def test_dispatch_wechat_off() -> None:
    app = _CmdApp()
    await dispatch_command(app, "/wechat off")  # type: ignore[arg-type]
    assert app.calls == ["stop"]


async def test_dispatch_wechat_status() -> None:
    app = _CmdApp()
    await dispatch_command(app, "/wechat")  # type: ignore[arg-type]
    assert any("STATUS" in m for _, m in app.notifications)


async def test_dispatch_wechat_unknown() -> None:
    app = _CmdApp()
    await dispatch_command(app, "/wechat frobnicate")  # type: ignore[arg-type]
    assert any("Usage: /wechat" in m for _, m in app.notifications)

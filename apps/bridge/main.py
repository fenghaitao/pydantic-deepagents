"""Bridge entry point.

Usage:
    python -m apps.bridge --wechat                # token from WECHAT_BOT_TOKEN env
    python -m apps.bridge --wechat --login        # interactive QR login
    python -m apps.bridge --wechat --config ~/.pydantic-deep/bridge.json

Config file (bridge.json):
    {
        "wechat_token": "...",
        "wechat_base_url": "https://ilinkai.weixin.qq.com",
        "model": "anthropic:claude-sonnet-4-6",
        "working_dir": "/path/to/workspace"
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_config(config_path: str | None) -> dict:
    if config_path:
        p = Path(config_path).expanduser()
        if p.exists():
            return json.loads(p.read_text())
    default = Path.home() / ".pydantic-deep" / "bridge.json"
    if default.exists():
        return json.loads(default.read_text())
    return {}


def _save_config(config: dict, config_path: str | None) -> None:
    p = Path(config_path).expanduser() if config_path else Path.home() / ".pydantic-deep" / "bridge.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(config, indent=2, ensure_ascii=False))


async def run_wechat(
    config: dict,
    config_path: str | None,
    *,
    login: bool = False,
    model: str | None = None,
    working_dir: str | None = None,
) -> None:
    from apps.bridge import wechat as wx
    from apps.bridge.runner import BridgeRunner
    from apps.cli.agent import create_cli_agent

    # Acquire single-instance lock
    acquired, holder = wx._acquire_lock()
    if not acquired:
        print(f"WeChat bridge already running (pid={holder}). Use a different terminal.", file=sys.stderr)
        sys.exit(1)

    # QR login if requested or no token available anywhere
    did_login = False
    if login or not (config.get("wechat_token") or os.environ.get("WECHAT_BOT_TOKEN")):
        if not wx.qr_login(config):
            sys.exit(1)
        _save_config(config, config_path)
        did_login = True

    # Precedence: a fresh QR login wins (it carries the redirected base_url);
    # otherwise the environment token takes priority over the saved config.
    if did_login:
        wx_cfg = wx.WeChatConfig.from_dict(config)
    else:
        wx_cfg = wx.WeChatConfig.from_env() or wx.WeChatConfig.from_dict(config)
    if not wx_cfg:
        print("No WeChat token found. Run with --login or set WECHAT_BOT_TOKEN.", file=sys.stderr)
        sys.exit(1)

    effective_model = model or config.get("model")
    effective_working_dir = working_dir or config.get("working_dir") or os.getcwd()

    send_fn = lambda uid, text: wx.wx_send(uid, text, wx_cfg.token, wx_cfg.base_url)  # noqa: E731

    from pydantic_deep.capabilities.bridge import BridgeCapability

    bridge_cap = BridgeCapability(send_fn=send_fn)

    agent, deps = create_cli_agent(
        model=effective_model,
        working_dir=effective_working_dir,
        non_interactive=True,
        extra_capabilities=[bridge_cap],
    )

    runner = BridgeRunner(agent=agent, deps=deps, send_fn=send_fn)

    loop = asyncio.get_running_loop()
    stop_event = threading.Event()

    poll_thread = wx.start_poll(
        token=wx_cfg.token,
        base_url=wx_cfg.base_url,
        on_message=runner.on_message,
        loop=loop,
        stop_event=stop_event,
    )

    print(f"WeChat bridge running (account: {wx_cfg.account_id or 'unknown'})")
    print("Send messages from WeChat — they will be processed by the agent.")
    print("Press Ctrl+C to stop.")

    try:
        await runner.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        stop_event.set()
        poll_thread.join(timeout=5)
        wx._release_lock()
        print("\nWeChat bridge stopped.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="pydantic-deep bridge: WeChat integration")
    parser.add_argument("--wechat", action="store_true", help="Start WeChat bridge")
    parser.add_argument("--login", action="store_true", help="Force QR re-login (WeChat)")
    parser.add_argument("--config", metavar="PATH", help="Path to bridge config JSON")
    parser.add_argument("--model", metavar="MODEL", help="Model override (e.g. anthropic:claude-sonnet-4-6)")
    parser.add_argument("--working-dir", metavar="DIR", help="Agent working directory")
    args = parser.parse_args()

    if not args.wechat:
        parser.print_help()
        sys.exit(1)

    config = _load_config(args.config)

    if args.wechat:
        asyncio.run(
            run_wechat(
                config,
                args.config,
                login=args.login,
                model=args.model,
                working_dir=args.working_dir,
            )
        )


if __name__ == "__main__":
    main()

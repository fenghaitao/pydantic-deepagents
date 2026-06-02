"""WeChat (iLink Bot API) bridge for pydantic-deep agents.

Auth flow:  /wechat login  — scan QR code, saves token to config
Poll loop:  long-polls iLink, puts (from_uid, text) onto an asyncio.Queue
Runner:     async loop consumes queue, calls agent.run_stream(), streams back

Setup: enable "ClawBot" plugin in WeChat → Me → Settings → Plugins → ClawBot
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import struct
import threading
import time
from base64 import b64encode
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── iLink API constants ───────────────────────────────────────────────────────

_ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
_ILINK_APP_ID = "bot"
_ILINK_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0
_ILINK_CHANNEL_VERSION = "2.2.0"
_ILINK_DEFAULT_BOT_TYPE = "3"

_WX_EP_GET_UPDATES = "ilink/bot/getupdates"
_WX_EP_SEND_MESSAGE = "ilink/bot/sendmessage"
_WX_EP_SEND_TYPING = "ilink/bot/sendtyping"
_WX_EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
_WX_EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"

_WX_LONG_POLL_TIMEOUT = 37
_WX_API_TIMEOUT = 15
_WX_QR_TIMEOUT = 37

_WX_MSG_TYPE_BOT = 2
_WX_MSG_STATE_DONE = 2
_WX_ITEM_TEXT = 1
_WX_TYPING_START = 1

_WX_STREAM_INTERVAL = 3.0   # seconds between partial sends (WeChat can't edit)
_WX_STREAM_MIN_LEN = 80     # minimum chars before flushing a partial

_WX_LOCK_PATH = os.path.expanduser("~/.pydantic-deep/wechat.lock")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _random_uin() -> str:
    value = struct.unpack(">I", secrets.token_bytes(4))[0]
    return b64encode(str(value).encode()).decode("ascii")


def _app_headers() -> dict[str, str]:
    return {
        "iLink-App-Id": _ILINK_APP_ID,
        "iLink-App-ClientVersion": str(_ILINK_CLIENT_VERSION),
    }


def _auth_headers(token: str, body: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "Content-Length": str(len(body.encode("utf-8"))),
        "X-WECHAT-UIN": _random_uin(),
        **_app_headers(),
    }


def _wx_get(base_url: str, endpoint: str, timeout: int = _WX_QR_TIMEOUT) -> dict | None:
    import urllib.request

    url = f"{base_url.rstrip('/')}/{endpoint}"
    req = urllib.request.Request(url, headers=_app_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _wx_post(
    base_url: str, endpoint: str, token: str, payload: dict, timeout: int = _WX_API_TIMEOUT
) -> dict | None:
    import urllib.request

    payload["base_info"] = {"channel_version": _ILINK_CHANNEL_VERSION}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    url = f"{base_url.rstrip('/')}/{endpoint}"
    data = body.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_auth_headers(token, body))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _wx_get_updates(base_url: str, token: str, sync_buf: str) -> dict | None:
    import socket
    import urllib.request

    payload = {
        "get_updates_buf": sync_buf,
        "base_info": {"channel_version": _ILINK_CHANNEL_VERSION},
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    url = f"{base_url.rstrip('/')}/{_WX_EP_GET_UPDATES}"
    data = body.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_auth_headers(token, body))
    try:
        with urllib.request.urlopen(req, timeout=_WX_LONG_POLL_TIMEOUT) as resp:
            return json.loads(resp.read())
    except (socket.timeout, TimeoutError):
        return {"ret": 0, "errcode": 0, "msgs": [], "get_updates_buf": sync_buf}
    except Exception:
        return None


def wx_send(user_id: str, text: str, token: str, base_url: str) -> None:
    """Send a text message to a WeChat user (splits if > 2000 chars)."""
    import uuid

    ctx_tokens = _ctx_tokens  # module-level cache populated by poll loop
    ctx_token = ctx_tokens.get(user_id)
    max_len = 2000
    chunks = [text[i : i + max_len] for i in range(0, max(len(text), 1), max_len)]
    for chunk in chunks:
        msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": user_id,
            "client_id": str(uuid.uuid4()),
            "message_type": _WX_MSG_TYPE_BOT,
            "message_state": _WX_MSG_STATE_DONE,
            "item_list": [{"type": _WX_ITEM_TEXT, "text_item": {"text": chunk}}],
        }
        if ctx_token:
            msg["context_token"] = ctx_token
        _wx_post(base_url, _WX_EP_SEND_MESSAGE, token, {"msg": msg})


def _wx_typing(user_id: str, token: str, base_url: str, config: dict) -> None:
    ticket = config.get(f"_wx_typing_ticket_{user_id}")
    if not ticket:
        return
    _wx_post(
        base_url,
        _WX_EP_SEND_TYPING,
        token,
        {"ilink_user_id": user_id, "typing_ticket": ticket, "status": _WX_TYPING_START},
        timeout=5,
    )


def _wx_typing_loop(user_id: str, stop_event: threading.Event, token: str, base_url: str, config: dict) -> None:
    while not stop_event.is_set():
        _wx_typing(user_id, token, base_url, config)
        stop_event.wait(4)


# ── Module-level state (poll loop populates) ──────────────────────────────────

_ctx_tokens: dict[str, str] = {}       # from_uid → context_token
_seen_msgids: set[str] = set()         # dedup rolling set


# ── Single-instance lock ──────────────────────────────────────────────────────

_lock_acquired = False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return isinstance(__import__("sys").exc_info()[1], PermissionError)
    except OSError:
        return False


def _acquire_lock() -> tuple[bool, int]:
    global _lock_acquired
    try:
        os.makedirs(os.path.dirname(_WX_LOCK_PATH), exist_ok=True)
    except OSError:
        _lock_acquired = True
        return True, 0

    if os.path.exists(_WX_LOCK_PATH):
        try:
            with open(_WX_LOCK_PATH) as f:
                holder_pid = int((f.read() or "0").strip() or "0")
        except (OSError, ValueError):
            holder_pid = 0
        if holder_pid and holder_pid != os.getpid() and _pid_alive(holder_pid):
            return False, holder_pid

    tmp_path = _WX_LOCK_PATH + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.write(str(os.getpid()))
        os.replace(tmp_path, _WX_LOCK_PATH)
        _lock_acquired = True
        import atexit
        atexit.register(_release_lock)
        return True, os.getpid()
    except OSError:
        return True, 0


def _release_lock() -> None:
    global _lock_acquired
    if not _lock_acquired:
        return
    try:
        if os.path.exists(_WX_LOCK_PATH):
            with open(_WX_LOCK_PATH) as f:
                holder = (f.read() or "0").strip()
            if holder == str(os.getpid()):
                os.unlink(_WX_LOCK_PATH)
    except OSError:
        pass
    _lock_acquired = False


# ── QR login ──────────────────────────────────────────────────────────────────

def qr_login(config: dict, bot_type: str = _ILINK_DEFAULT_BOT_TYPE, timeout_seconds: int = 480) -> bool:
    """Interactive QR code login flow. Updates config in-place with token + base_url."""
    base_url = _ILINK_BASE_URL

    qr_resp = _wx_get(base_url, f"{_WX_EP_GET_BOT_QR}?bot_type={bot_type}")
    if not qr_resp:
        logger.error("Could not reach iLink API.")
        return False

    qrcode_value = str(qr_resp.get("qrcode") or "")
    qrcode_img = str(qr_resp.get("qrcode_img_content") or "")
    if not qrcode_value:
        logger.error("iLink returned empty QR code.")
        return False

    print("Scan the QR code below with WeChat:")
    _print_qr(qrcode_img or qrcode_value)
    print("Waiting for scan...")

    deadline = time.time() + timeout_seconds
    refresh_count = 0
    current_base = base_url

    while time.time() < deadline:
        status_resp = _wx_get(current_base, f"{_WX_EP_GET_QR_STATUS}?qrcode={qrcode_value}")
        if status_resp is None:
            time.sleep(1)
            continue

        status = str(status_resp.get("status") or "wait")

        if status == "wait":
            print(".", end="", flush=True)
        elif status == "scaned":
            print()
            print("Scanned — confirm in WeChat...")
        elif status == "scaned_but_redirect":
            redirect_host = str(status_resp.get("redirect_host") or "")
            if redirect_host:
                current_base = f"https://{redirect_host}"
        elif status == "expired":
            refresh_count += 1
            if refresh_count > 3:
                print()
                logger.error("QR code expired too many times.")
                return False
            print()
            print(f"QR code expired, refreshing... ({refresh_count}/3)")
            qr_resp = _wx_get(base_url, f"{_WX_EP_GET_BOT_QR}?bot_type={bot_type}")
            if not qr_resp:
                return False
            qrcode_value = str(qr_resp.get("qrcode") or "")
            qrcode_img = str(qr_resp.get("qrcode_img_content") or "")
            _print_qr(qrcode_img or qrcode_value)
        elif status == "confirmed":
            token = str(status_resp.get("bot_token") or "")
            new_base = str(status_resp.get("baseurl") or base_url)
            acct_id = str(status_resp.get("ilink_bot_id") or "")
            if not token:
                logger.error("iLink confirmed but returned no token.")
                return False
            print()
            config["wechat_token"] = token
            config["wechat_base_url"] = new_base
            if acct_id:
                config["wechat_account_id"] = acct_id
            print(f"WeChat authenticated (account: {acct_id or 'unknown'})")
            return True

        time.sleep(1)

    print()
    logger.error("WeChat QR login timed out.")
    return False


def _print_qr(url_or_value: str) -> None:
    try:
        import qrcode  # type: ignore[import-not-found]

        qr = qrcode.QRCode(border=1)
        qr.add_data(url_or_value)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        print(f"\n  {url_or_value}\n")
        print("(Install 'qrcode' for inline QR rendering: pip install qrcode)")


# ── Poll loop (runs in a daemon thread) ───────────────────────────────────────

OnMessageT = Callable[[str, str], Awaitable[None]]


def start_poll(
    token: str,
    base_url: str,
    on_message: OnMessageT,
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> threading.Thread:
    """Start the WeChat long-poll loop in a daemon thread.

    Args:
        token: iLink bot token.
        base_url: iLink base URL (from login response).
        on_message: Async callback ``(from_uid, text)`` called for each inbound message.
        loop: The asyncio event loop to schedule on_message into.
        stop_event: Set this to stop the poll loop.

    Returns:
        The started daemon thread.
    """
    t = threading.Thread(
        target=_supervisor,
        args=(token, base_url, on_message, loop, stop_event),
        daemon=True,
        name="wechat-bridge",
    )
    t.start()
    return t


_BACKOFF_INITIAL = 2.0
_BACKOFF_MAX = 120.0


def _supervisor(
    token: str,
    base_url: str,
    on_message: OnMessageT,
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> None:
    backoff = _BACKOFF_INITIAL
    attempt = 0
    while not stop_event.is_set():
        attempt += 1
        try:
            reason = _poll_loop(token, base_url, on_message, loop, stop_event)
        except Exception as exc:
            if stop_event.is_set():
                break
            logger.warning("WeChat bridge crashed (attempt %d): %s — retrying in %.0fs", attempt, exc, backoff)
            stop_event.wait(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
            continue

        if reason == "auth_error":
            logger.error("WeChat: session expired — re-authenticate with qr_login()")
            break
        break


def _poll_loop(
    token: str,
    base_url: str,
    on_message: OnMessageT,
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
) -> str:
    """Returns 'stopped' or 'auth_error'."""
    sync_buf = ""
    consecutive_failures = 0

    while not stop_event.is_set():
        result = _wx_get_updates(base_url, token, sync_buf)
        if result is None:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                logger.warning("WeChat: repeated connection failures, retrying in 30s...")
                stop_event.wait(30)
                consecutive_failures = 0
            else:
                stop_event.wait(2)
            continue
        consecutive_failures = 0

        ret = result.get("ret", 0)
        errcode = result.get("errcode", 0)
        if ret not in (0, None) or errcode not in (0, None):
            if ret == -14 or errcode == -14:
                logger.warning("WeChat: session expired (ret=%s errcode=%s)", ret, errcode)
                return "auth_error"
            logger.warning("WeChat API error ret=%s errcode=%s — retrying", ret, errcode)
            stop_event.wait(5)
            continue

        new_buf = result.get("get_updates_buf")
        if new_buf:
            sync_buf = new_buf

        for msg in result.get("msgs") or []:
            ctx_tok = msg.get("context_token")
            from_uid = str(msg.get("from_user_id") or "").strip()
            if ctx_tok and from_uid:
                _ctx_tokens[from_uid] = ctx_tok

            # Skip bot's own outbound messages
            if msg.get("message_type") == _WX_MSG_TYPE_BOT:
                continue

            # Dedup
            msg_id = msg.get("message_id") or msg.get("seq") or msg.get("client_id") or ""
            if not msg_id:
                content_preview = ""
                for item in msg.get("item_list") or []:
                    if item.get("type") == _WX_ITEM_TEXT:
                        content_preview = (item.get("text_item") or {}).get("text", "")[:200]
                        break
                if not content_preview:
                    content_preview = str(msg.get("content") or msg.get("text") or "")[:200]
                create_time = str(msg.get("create_time") or msg.get("timestamp") or "")
                seed = f"{from_uid}|{create_time}|{content_preview}"
                msg_id = "auto_" + hashlib.md5(seed.encode("utf-8", "ignore")).hexdigest()[:16]

            if msg_id in _seen_msgids:
                continue
            _seen_msgids.add(msg_id)
            if len(_seen_msgids) > 2000:
                oldest = list(_seen_msgids)[:500]
                for k in oldest:
                    _seen_msgids.discard(k)

            # Extract text
            text = ""
            for item in msg.get("item_list") or []:
                if item.get("type") == _WX_ITEM_TEXT:
                    text = (item.get("text_item") or {}).get("text", "").strip()
                    break
            if not text:
                text = str(msg.get("content") or msg.get("text") or "").strip()

            if not text or not from_uid:
                continue

            logger.info("WeChat [%s]: %s", from_uid, text[:80])
            # Schedule the async callback on the event loop from the poll thread
            asyncio.run_coroutine_threadsafe(on_message(from_uid, text), loop)

    return "stopped"


# ── Config helpers ────────────────────────────────────────────────────────────

@dataclass
class WeChatConfig:
    token: str
    base_url: str = _ILINK_BASE_URL
    account_id: str = ""

    @classmethod
    def from_env(cls) -> "WeChatConfig | None":
        token = os.environ.get("WECHAT_BOT_TOKEN", "").strip()
        if not token:
            return None
        return cls(
            token=token,
            base_url=os.environ.get("WECHAT_BASE_URL", _ILINK_BASE_URL),
        )

    @classmethod
    def from_dict(cls, d: dict) -> "WeChatConfig | None":
        token = (d.get("wechat_token") or "").strip()
        if not token:
            return None
        return cls(
            token=token,
            base_url=d.get("wechat_base_url", _ILINK_BASE_URL),
            account_id=d.get("wechat_account_id", ""),
        )

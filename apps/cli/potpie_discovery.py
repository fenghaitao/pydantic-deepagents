"""Auto-discovery of a running potpie service via the singularity Discovery Server.

Ports the _apply_session_ports logic from potpie_cli.py into a library-friendly
function that can be used without any potpie Python package dependency.

Discovery lookup order for the sessions directory:
  1. POTPIE_SESSIONS_DIR environment variable
  2. POTPIE_REPO_ROOT/.potpie-sessions (if POTPIE_REPO_ROOT is set)
  3. ~/.potpie-sessions
  4. Walk upward from CWD looking for .potpie-sessions/
"""

from __future__ import annotations

import json
import logging
import os
import socket
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _http_get(url: str, timeout: int = 5) -> Optional[dict]:
    """Fetch JSON from *url*. Returns None on any error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    """Return True if *pid* is a live process (Unix only)."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _find_sessions_dir() -> Optional[Path]:
    """Locate the .potpie-sessions directory by searching candidate locations."""
    # 1. Explicit env var override
    explicit = os.environ.get("POTPIE_SESSIONS_DIR")
    if explicit:
        p = Path(explicit)
        if p.is_dir():
            return p

    # 2. POTPIE_REPO_ROOT/.potpie-sessions
    repo_root = os.environ.get("POTPIE_REPO_ROOT")
    if repo_root:
        p = Path(repo_root) / ".potpie-sessions"
        if p.is_dir():
            return p

    # 3. ~/.potpie-sessions
    home_sessions = Path.home() / ".potpie-sessions"
    if home_sessions.is_dir():
        return home_sessions

    # 4. Walk upward from CWD
    cwd = Path.cwd()
    for ancestor in [cwd, *cwd.parents]:
        candidate = ancestor / ".potpie-sessions"
        if candidate.is_dir():
            return candidate

    return None


def discover_potpie_url() -> Optional[str]:
    """Read the singularity discovery file and return the running API URL.

    Returns:
        ``http://localhost:<port>`` if a healthy potpie service is found,
        ``None`` otherwise (caller should fall back to manual config).
    """
    sessions_dir = _find_sessions_dir()
    if sessions_dir is None:
        logger.debug("potpie_discovery: .potpie-sessions directory not found")
        return None

    try:
        user = os.environ.get("USER") or os.environ.get("LOGNAME", "")
        if not user:
            logger.debug("potpie_discovery: USER/LOGNAME not set")
            return None

        try:
            host = socket.gethostname().split(".")[0]
        except Exception:
            host = "localhost"

        session_key = f"{user}@{host}"
        disco_file = sessions_dir / f"{session_key}.discovery"

        if not disco_file.exists():
            logger.debug("potpie_discovery: discovery file not found: %s", disco_file)
            return None

        meta = json.loads(disco_file.read_text())
        disco_port = meta.get("port")
        pid = meta.get("pid")

        if not disco_port or not pid:
            logger.debug("potpie_discovery: incomplete discovery file")
            return None

        if not _pid_alive(int(pid)):
            logger.debug("potpie_discovery: discovery server PID %s is dead", pid)
            return None

        session = _http_get(f"http://127.0.0.1:{disco_port}/session/{session_key}")
        if session is None:
            logger.debug("potpie_discovery: could not reach discovery server")
            return None

        ports = session.get("ports") or {}
        api_port = ports.get("api")
        if not api_port:
            logger.debug("potpie_discovery: no api port in session data")
            return None

        url = f"http://localhost:{api_port}"
        logger.debug("potpie_discovery: discovered potpie API at %s", url)
        return url

    except Exception as exc:
        logger.debug("potpie_discovery: unexpected error: %s", exc)
        return None


__all__ = ["discover_potpie_url"]

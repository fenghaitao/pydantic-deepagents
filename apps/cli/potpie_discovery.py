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


def parse_git_identity(root: Path | None = None) -> Optional[tuple[str, str]]:
    """Return ``(repo_name, branch)`` for the git repo at *root*, or ``None``.

    Pure git operations — no PotpieRuntime needed. Handles submodule
    scenarios by resolving the superproject for remote URL lookups.

    Args:
        root: Directory to inspect. Defaults to CWD.

    Returns:
        ``(repo_name, branch)`` tuple, or ``None`` if not a git repo or
        no remote origin is configured.
    """
    import shutil
    import subprocess

    root = root or Path.cwd()
    git = shutil.which("git")
    if not git:
        logger.debug("parse_git_identity: git not found")
        return None

    def _run(args: list[str], cwd: Path = root) -> Optional[str]:
        try:
            r = subprocess.run(
                args, capture_output=True, text=True, timeout=3, cwd=str(cwd), check=False
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None

    # Resolve git root; if inside a submodule use the superproject for remote URL
    git_root_str = _run([git, "rev-parse", "--show-toplevel"])
    git_root = Path(git_root_str) if git_root_str else root
    superproject_str = _run([git, "rev-parse", "--show-superproject-working-tree"])
    if superproject_str:
        git_root = Path(superproject_str)

    branch = _run([git, "rev-parse", "--abbrev-ref", "HEAD"])
    if not branch:
        logger.debug("parse_git_identity: could not determine branch")
        return None

    remote_url = _run([git, "remote", "get-url", "origin"], cwd=git_root)
    if not remote_url:
        logger.debug("parse_git_identity: no git remote 'origin'")
        return None

    # Strip trailing slash, then .git suffix with proper suffix removal (not rstrip
    # which strips individual characters and would corrupt names like "pytest").
    url = remote_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # Handles both https://host/org/repo and git@host:org/repo
    repo_name = url.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if not repo_name:
        logger.debug("parse_git_identity: could not parse repo name from %s", remote_url)
        return None

    logger.debug("parse_git_identity: repo=%s branch=%s", repo_name, branch)
    return repo_name, branch


async def discover_project_id(
    root: Path | None = None,
    user_id: str = "defaultuser",
) -> Optional[str]:
    """Standalone utility: discover the potpie project ID for the git repo at *root*.

    Creates its own ``PotpieRuntime`` — useful for scripts and one-off lookups
    (e.g. ``evaluation/get_project_id.py``) where no backend is already running.

    When a ``RuntimeBackend`` is already available (e.g. inside the CLI agent
    setup), prefer ``parse_git_identity(root)`` + ``backend.list_projects()``
    directly to avoid a second ``PotpieRuntime`` initialization (~25s overhead).

    Args:
        root: Working directory to inspect. Defaults to CWD.
        user_id: Potpie user ID for project lookup.

    Returns:
        Project ID string if found, ``None`` otherwise.
    """
    root = root or Path.cwd()
    identity = parse_git_identity(root)
    if not identity:
        return None
    repo_name, branch = identity

    try:
        from potpie import PotpieRuntime  # type: ignore[import]

        # Ensure potpie's .env is loaded — walk up from root to find it
        try:
            from dotenv import load_dotenv as _load_dotenv
            for ancestor in [root, *root.parents]:
                env_file = ancestor / ".env"
                if env_file.exists():
                    _load_dotenv(env_file, override=False)
                    break
        except ImportError:
            pass

        rt = PotpieRuntime.from_env()
        await rt.initialize()
        try:
            projects = await rt.projects.list(user_id=user_id)
            for p in projects:
                if p.repo_name == repo_name and p.branch_name == branch:
                    logger.debug("discover_project_id: found project %s", p.id)
                    return p.id
            logger.debug(
                "discover_project_id: no project matched repo=%s branch=%s", repo_name, branch
            )
        finally:
            await rt.close()
    except Exception as exc:
        logger.debug("discover_project_id: runtime error: %s", exc)

    return None


__all__ = ["discover_potpie_url", "discover_project_id", "parse_git_identity"]

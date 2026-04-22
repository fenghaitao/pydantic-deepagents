#!/usr/bin/env python3
"""
Start the agent on a free port, updating .env.local so Next.js knows where to find it.
Scans from the default port upward to find the first available port.
"""
import os
import socket
import sys
from pathlib import Path

DEFAULT_PORT = int(os.getenv("AGENT_PORT", "8000"))
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env.local")


def find_venv_python() -> str:
    """Walk up from this file to find the nearest .venv/bin/python.

    This ensures the correct project venv is used even when the system
    'python' on PATH belongs to a different project's venv.
    """
    d = Path(__file__).resolve().parent
    for _ in range(8):
        candidate = d / ".venv" / "bin" / "python"
        if candidate.exists():
            return str(candidate)
        parent = d.parent
        if parent == d:
            break
        d = parent
    return sys.executable  # fallback to whatever python ran this script


def find_free_port(start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found in range")


def update_env_file(port: int) -> None:
    key = "AGENT_URL"
    value = f"http://localhost:{port}"  # no trailing slash
    lines: list[str] = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            lines = [l for l in f.readlines() if not l.startswith(f"{key}=")]
    lines.append(f"{key}={value}\n")
    with open(ENV_FILE, "w") as f:
        f.writelines(lines)
    print(f"[agent] AGENT_URL={value}", flush=True)


if __name__ == "__main__":
    port = find_free_port(DEFAULT_PORT)
    if port != DEFAULT_PORT:
        print(f"[agent] Port {DEFAULT_PORT} in use, using {port}", flush=True)

    update_env_file(port)

    # Change to agent directory so uvicorn can find main.py regardless of cwd
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    python = find_venv_python()
    print(f"[agent] Using python: {python}", flush=True)

    # Start uvicorn (os.execv replaces this process, keeping the same PID)
    os.execv(
        python,
        [python, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(port)],
    )

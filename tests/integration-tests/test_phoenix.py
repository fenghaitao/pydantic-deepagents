"""Integration test: verify that `pydantic-deep --phoenix run "Hello"` completes
without errors against the Phoenix tracing server.

This test belongs in the pydantic-deepagents repo because it exercises the
``--phoenix`` CLI flag, which is a feature of pydantic-deep (not potpie).
Phoenix is started at the pydantic-deepagents level via ``scripts/phoenix.sh``;
its port is exposed in the ``PHOENIX_PORT`` environment variable (set by that
script, or by the CI workflow via GITHUB_ENV).

Usage (from the pydantic-deepagents repo root):
    bash scripts/phoenix.sh start
    eval $(bash scripts/phoenix.sh start)   # to export PHOENIX_PORT
    .venv/bin/pytest tests/integration-tests/test_phoenix.py -v -s

Prerequisites:
    Phoenix must be running and PHOENIX_PORT must be set:
        bash scripts/phoenix.sh start
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
# This file lives at tests/integration-tests/test_phoenix.py, so:
#   parents[0] = tests/integration-tests
#   parents[1] = tests
#   parents[2] = pydantic-deepagents repo root
_ROOT = Path(__file__).resolve().parents[2]
_PYDANTIC_DEEP = _ROOT / ".venv" / "bin" / "pydantic-deep"
# PHOENIX_PORT is set by scripts/phoenix.sh (written to GITHUB_ENV in CI, or
# exported by the user running `eval $(bash scripts/phoenix.sh start)` locally).


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def test_pydantic_deep_run_with_phoenix():
    """pydantic-deep --phoenix run 'Hello' should exit 0 with Phoenix running."""
    timeout_seconds = 120
    cmd = [str(_PYDANTIC_DEEP), "--phoenix", "run", "--no-browser", "Hello"]
    print(f"[{_ts()}] Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_ROOT),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"pydantic-deep timed out after {timeout_seconds}s.\n"
            f"  partial stdout: {exc.stdout!r}\n"
            f"  partial stderr: {exc.stderr!r}"
        ) from exc

    print(f"[{_ts()}] exit code: {result.returncode}")
    if result.stdout:
        print(f"[{_ts()}] stdout:\n{result.stdout}")
    if result.stderr:
        print(f"[{_ts()}] stderr:\n{result.stderr}")

    assert result.returncode == 0, (
        f"pydantic-deep --phoenix run 'Hello' failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
    )

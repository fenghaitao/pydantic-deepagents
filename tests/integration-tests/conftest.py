"""Pytest fixtures for integration tests that run against live services.

All integration tests in this directory depend on the potpie backend being
healthy.  They are excluded from the regular ``make test`` run via
``addopts = "--ignore=tests/integration-tests"`` in pyproject.toml and are
invoked explicitly from the CI workflow (merge-gate-tests.yml).
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv

# ── Paths ──────────────────────────────────────────────────────────────────────
# This file lives at tests/integration-tests/conftest.py, so:
#   parents[0] = tests/integration-tests
#   parents[1] = tests
#   parents[2] = pydantic-deepagents repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_POTPIE_ROOT = _REPO_ROOT / "code-graph-providers" / "potpie"

# Load the potpie backend's .env (written by start.sh with dynamic port values).
# This populates NEO4J_URI, BOLT_PORT, etc. so tests can connect to the graph.
# Missing file is silently skipped; CI sets these vars via export-ports instead.
load_dotenv(_POTPIE_ROOT / ".env")

# Patch POSTGRES_SERVER to match what potpie_cli.py's _apply_session_ports()
# builds.  export-ports.sh may produce a URL with the wrong database name
# ('potpie' instead of 'momentum') and may omit '?gssencmode=disable'.
# Both cause an immediate SQLAlchemy connection failure in pydantic-deep's
# in-process PotpieRuntime.  We normalise here so that any subprocess
# spawned by pydantic_deep_runner gets the correct value via inheritance.
_ps = os.environ.get("POSTGRES_SERVER", "")
if _ps:
    # Replace any database path that is NOT 'momentum' with 'momentum'.
    # e.g. postgresql://user:pw@host:port/potpie → .../momentum
    _ps = re.sub(r"/([^/?]+)(\?|$)", lambda m: f"/momentum{m.group(2)}", _ps)
    # Ensure gssencmode=disable is appended (required by potpie).
    if "gssencmode" not in _ps:
        _ps += "?gssencmode=disable" if "?" not in _ps else "&gssencmode=disable"
    os.environ["POSTGRES_SERVER"] = _ps


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_json_from_output(output: str) -> str:
    """Strip any banner/warning lines before the JSON array or object.

    ``pydantic-deep`` may emit an "Update available" notice on stdout before
    the requested JSON payload, which breaks ``json.loads`` on the full string.
    We locate the first ``[`` or ``{`` and return everything from there.
    """
    for i, ch in enumerate(output):
        if ch in ("[", "{"):
            return output[i:]
    return output


def _simple_run(
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 120,
    stderr_as_error: bool = True,
) -> tuple[str, str]:
    """Run a subprocess, return (stdout, stderr). Raises on failure."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)

    if proc.returncode != 0 or (stderr and stderr_as_error):
        raise subprocess.CalledProcessError(proc.returncode, cmd, stdout, stderr)

    return stdout.strip(), stderr.strip()


# ── Paths (continued) ──────────────────────────────────────────────────────────
_PYDANTIC_DEEP = _REPO_ROOT / ".venv" / "bin" / "pydantic-deep"


# ── Shared runner helper ───────────────────────────────────────────────────────

def _make_runner(cmd_prefix: list[str], default_cwd: str) -> object:
    """Factory for a runner callable that streams stderr and captures stdout."""
    def run_cmd(
        *args: str,
        check: bool = True,
        cwd: str | None = None,
        timeout: int = 1800,
    ) -> subprocess.CompletedProcess:
        cmd = cmd_prefix + list(args)
        effective_cwd = cwd or default_cwd
        ts = datetime.now().strftime("%H:%M:%S")
        print(
            f"\n[{ts}] Running: {' '.join(cmd)}"
            f"  (cwd={effective_cwd}, timeout={timeout}s)",
            flush=True,
        )
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=effective_cwd,
        )
        stderr_lines: list[str] = []
        stdout_lines: list[str] = []

        def _stream_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                ts = datetime.now().strftime("%H:%M:%S")
                line = line.rstrip("\n")
                print(f"  [{ts}][stderr] {line}", flush=True)
                stderr_lines.append(line)

        def _stream_stdout() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                ts = datetime.now().strftime("%H:%M:%S")
                line = line.rstrip("\n")
                print(f"  [{ts}][stdout] {line}", flush=True)
                stdout_lines.append(line)

        def _heartbeat() -> None:
            """Print a liveness ping every 30 s so CI logs never go silent."""
            start = time.monotonic()
            while proc.poll() is None:
                time.sleep(30)
                if proc.poll() is None:
                    elapsed = int(time.monotonic() - start)
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(
                        f"  [{ts}][heartbeat] command still running "
                        f"({elapsed}s elapsed) …",
                        flush=True,
                    )

        t = threading.Thread(target=_stream_stderr, daemon=True)
        ts_out = threading.Thread(target=_stream_stdout, daemon=True)
        hb = threading.Thread(target=_heartbeat, daemon=True)
        t.start()
        ts_out.start()
        hb.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            # Use wait() instead of a second communicate() call.
            # communicate() opens a raw-FD reader on proc.stderr while _stream
            # is still blocking on readline() on the same pipe; the two compete
            # on the same OS buffer and can deadlock for tens of minutes.
            # wait() just reaps the zombie without touching the pipes.
            proc.wait()
            t.join(timeout=5)
            ts_out.join(timeout=5)
            hb.join(timeout=1)
            raise subprocess.TimeoutExpired(
                cmd, timeout, output=None, stderr="\n".join(stderr_lines)
            )
        finally:
            t.join(timeout=5)
            ts_out.join(timeout=5)
            hb.join(timeout=1)

        stderr_text = "\n".join(stderr_lines)
        stdout_text = "\n".join(stdout_lines)
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] Command finished (exit={proc.returncode})", flush=True)
        result = subprocess.CompletedProcess(
            args=cmd,
            returncode=proc.returncode,
            stdout=stdout_text,
            stderr=stderr_text,
        )
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return result

    return run_cmd


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def pydantic_deep_runner():
    """Return a callable that runs ``pydantic-deep`` from the repo root.

    Uses the pydantic-deepagents venv so no extra deps are needed.
    Talks to the potpie REST API (already running), so ML models are
    pre-loaded in the backend — no heavyweight in-process model loading.

    Signature:
        runner(*args, check=True, cwd=None, timeout=1800) -> CompletedProcess
    """
    return _make_runner([str(_PYDANTIC_DEEP)], str(_REPO_ROOT))


@pytest.fixture(scope="session")
def sparse_checkout():
    """Return a callable that performs a git sparse-checkout.

    Signature:
        checkout(url, paths, branch=None, target=None, timeout=100) -> list[str]

    ``paths`` is a list of repo-relative directories/files to include.
    Returns the list of absolute paths to the checked-out entries.
    """
    def _do(
        url: str,
        paths: list[str],
        branch: str | None = None,
        target: str | None = None,
        timeout: int = 100,
    ) -> list[str]:
        clone_cmd = [
            "git", "clone", "--filter=blob:none", "--no-checkout", "--depth=1", url,
        ]
        if branch:
            clone_cmd += ["--branch", branch]
        if target:
            clone_cmd += [target]

        _, err = _simple_run(clone_cmd, timeout=timeout, stderr_as_error=False)

        if not target:
            first_line = err.splitlines()[0] if err else ""
            m = re.match(r"Cloning into '(.+)'...", first_line)
            assert m, f"Unexpected git clone output: {first_line!r}"
            target = m.group(1)

        _simple_run(
            ["git", "sparse-checkout", "set"] + paths, cwd=target, timeout=timeout
        )
        _simple_run(["git", "checkout"], cwd=target, timeout=timeout)

        result = [f"{target}/{p}" for p in paths]
        for p in result:
            assert os.path.exists(p), f"sparse-checkout did not produce expected path: {p}"
        return result

    return _do

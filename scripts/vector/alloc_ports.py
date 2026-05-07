#!/usr/bin/env python3
"""Allocate (or release) dynamic TCP ports for the observability stack.

Uses ports_allocator.PortManager for allocation, idempotency, and session
persistence — following the same pattern as the potpie submodule.
Service names are namespaced with the ``obs.`` prefix to avoid collisions
with potpie's own allocations (neo4j, postgres, etc.).

Commands
--------
  python alloc_ports.py alloc   → allocate ports (idempotent: reuse existing
                                  session), print SHELL_VAR=VALUE lines for eval.
  python alloc_ports.py free    → release all obs.* sessions for this workspace.
  python alloc_ports.py print   → print current ports without (re)allocating;
                                  exits 1 if no session exists.

Session storage
---------------
Ports are stored by ports_allocator in:
    ~/.ports-allocator/{user}-{machine}.discovery

Environment
-----------
  REPO_ROOT   Override the repo root (default: two directories above this
              script, i.e. the pydantic-deepagents root).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ports_allocator import PortManager

# ── Port catalogue ────────────────────────────────────────────────────────────

# Ordered list of service keys — each is allocated as "obs.<key>" in PortManager.
PORT_KEYS: list[str] = [
    "vector_ingest",
    "vector_api",
    "vector_otlp_http",
    "victoria_metrics",
    "victoria_logs",
    "tempo_http",
    "tempo_otlp_grpc",
    "tempo_otlp_http",
    "tempo_internal_grpc",
    "grafana",
    "phoenix",
    "phoenix_grpc",
]

# Shell variable name for each key (consumed by observability.sh and callers).
ENV_VAR: dict[str, str] = {
    "vector_ingest":        "VECTOR_INGEST_PORT",
    "vector_api":           "VECTOR_API_PORT",
    "vector_otlp_http":     "VECTOR_OTLP_HTTP_PORT",
    "victoria_metrics":     "VICTORIA_METRICS_PORT",
    "victoria_logs":        "VICTORIA_LOGS_PORT",
    "tempo_http":           "TEMPO_HTTP_PORT",
    "tempo_otlp_grpc":      "TEMPO_OTLP_GRPC_PORT",
    "tempo_otlp_http":      "TEMPO_OTLP_HTTP_PORT",
    "tempo_internal_grpc":  "TEMPO_INTERNAL_GRPC_PORT",
    "grafana":              "GRAFANA_PORT",
    "phoenix":              "PHOENIX_PORT",
    "phoenix_grpc":         "PHOENIX_GRPC_PORT",
}

# Service names passed to PortManager (namespaced to avoid potpie collisions).
SVC_NAME: dict[str, str] = {key: f"obs.{key}" for key in PORT_KEYS}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_ports(data: dict[str, object]) -> None:
    for key in PORT_KEYS:
        print(f"{ENV_VAR[key]}={data[key]}")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_alloc(repo_root: Path) -> None:
    """Allocate ports via PortManager (idempotent)."""
    pm = PortManager()
    workspace = str(repo_root)
    data: dict[str, object] = {key: pm.allocate(SVC_NAME[key], workspace=workspace) for key in PORT_KEYS}
    _print_ports(data)


def cmd_free(repo_root: Path) -> None:
    """Release all obs.* port sessions for this workspace."""
    PortManager().stop(workspace=str(repo_root))


def cmd_print(repo_root: Path) -> None:
    """Print current port assignments without allocating."""
    pm = PortManager()
    workspace = str(repo_root)
    data: dict[str, object] = {key: pm.get(SVC_NAME[key], workspace=workspace) for key in PORT_KEYS}
    if not any(data.values()):
        print("No observability session found.", file=sys.stderr)
        sys.exit(1)
    _print_ports(data)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _repo_root = Path(
        os.environ.get("REPO_ROOT", str(Path(__file__).resolve().parent.parent.parent))
    )
    _cmd = sys.argv[1] if len(sys.argv) > 1 else "alloc"
    if _cmd == "alloc":
        cmd_alloc(_repo_root)
    elif _cmd == "free":
        cmd_free(_repo_root)
    elif _cmd == "print":
        cmd_print(_repo_root)
    else:
        print(f"Unknown command: {_cmd!r}. Use: alloc | free | print", file=sys.stderr)
        sys.exit(1)

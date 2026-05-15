"""Integration test: index tests/integration-tests/simics-c++-device with
scip-clang via ``cgc index . --force``, then verify that expected nodes and
edges are present in the KuzuDB knowledge graph.

Usage (from the pydantic-deepagents repo root):
    .venv/bin/pytest tests/integration-tests/test_scip_clang_simics_device.py -v -s

Prerequisites:
    1. scip-clang binary must be available:
           make setup-scip-clang
    2. The Simics project scaffold must have been generated:
           /path/to/simics-7/bin/project-setup --ignore-existing-files \\
               tests/integration-tests/simics-c++-device
    3. compile_commands.json must exist at the project root:
           bash tests/integration-tests/simics-c++-device/gen-compile-commands.sh
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT    = Path(__file__).resolve().parents[2]
_SIMICS_DEV   = _REPO_ROOT / "tests" / "integration-tests" / "simics-c++-device"
_DB_PATH      = _SIMICS_DEV / ".codegraphcontext" / "db" / "kuzudb"
_SCIP_BIN     = _REPO_ROOT / "code-graph-providers" / "scip-languages" / "bin" / "scip-clang"
_CGC          = shutil.which("cgc") or str(_REPO_ROOT / ".venv" / "bin" / "cgc")

# ── Skip conditions ────────────────────────────────────────────────────────────
_SCIP_MISSING       = not _SCIP_BIN.exists()
_CGC_MISSING        = not Path(_CGC).exists()
# project-setup must have been run; CMakeLists.txt is a reliable marker.
_PROJECT_NOT_SET_UP = not (_SIMICS_DEV / "CMakeLists.txt").exists()


@pytest.fixture(scope="module")
def indexed_db():
    """Run ``cgc index . --force`` in simics-c++-device and return a kuzu Connection."""
    if _SCIP_MISSING:
        pytest.skip(
            f"scip-clang binary not found at {_SCIP_BIN}. "
            "Run: make setup-scip-clang"
        )
    if _CGC_MISSING:
        pytest.skip(f"cgc not found at {_CGC}")
    if _PROJECT_NOT_SET_UP:
        pytest.skip(
            "Simics project scaffold not found (CMakeLists.txt missing). "
            "Run: /path/to/simics-7/bin/project-setup --ignore-existing-files "
            f"{_SIMICS_DEV}"
        )

    # Ensure compile_commands.json is at the project root (where scip-clang
    # expects it).  gen-compile-commands.sh both configures and builds, then
    # copies it to the root.
    _compdb_root = _SIMICS_DEV / "compile_commands.json"
    if not _compdb_root.exists():
        gen = subprocess.run(
            ["bash", "gen-compile-commands.sh"],
            cwd=str(_SIMICS_DEV),
            capture_output=True,
            text=True,
            timeout=600,  # full cmake build can be slow
        )
        if gen.returncode != 0:
            pytest.skip(
                f"Could not generate compile_commands.json:\n{gen.stderr}"
            )

    result = subprocess.run(
        [_CGC, "index", ".", "--force"],
        cwd=str(_SIMICS_DEV),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        pytest.fail(
            f"cgc index failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    # Verify scip-clang was used, not Tree-sitter fallback.
    assert "Indexing method: SCIP" in result.stdout, (
        f"Expected SCIP indexing but got:\n{result.stdout}"
    )
    assert "Tree-sitter fallback" not in result.stdout, (
        f"scip-clang failed and fell back to Tree-sitter:\n{result.stdout}"
    )

    try:
        import kuzu
    except ImportError:
        pytest.skip("kuzu not installed")

    db   = kuzu.Database(str(_DB_PATH))
    conn = kuzu.Connection(db)
    yield conn


# ── Helpers ────────────────────────────────────────────────────────────────────

def _one(conn, query: str, params: dict | None = None) -> list:
    """Execute query and return all rows as lists."""
    r = conn.execute(query, parameters=params or {})
    rows = []
    while r.has_next():
        rows.append(r.get_next())
    return rows


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_file_nodes_present(indexed_db):
    """Key .cc source files from sample-device-c++ must be indexed as File nodes."""
    rows = _one(indexed_db, "MATCH (n:File) RETURN n.name")
    names = {r[0] for r in rows}
    assert "sample-class.cc"     in names
    assert "sample-attribute.cc" in names
    assert "sample-event.cc"     in names


def test_repository_node_present(indexed_db):
    """A Repository node for the simics-c++-device path must exist."""
    rows = _one(indexed_db, "MATCH (n:Repository) RETURN n.path")
    assert rows, "No Repository node found"
    assert any("simics-c++-device" in (r[0] or "") for r in rows), (
        f"simics-c++-device repository not found: {rows}"
    )


def test_functions_indexed(indexed_db):
    """At least some Function nodes must be present (device methods)."""
    rows = _one(indexed_db, "MATCH (n:Function) RETURN n.name LIMIT 5")
    assert rows, "No Function nodes found — device methods were not indexed"


def test_scip_clang_binary_resolves():
    """Sanity check: the repo-local scip-clang binary exists and is executable."""
    if _SCIP_MISSING:
        pytest.skip("scip-clang not yet downloaded; run: make setup-scip-clang")
    assert _SCIP_BIN.is_file(), f"Not a file: {_SCIP_BIN}"
    assert os.access(_SCIP_BIN, os.X_OK), f"Not executable: {_SCIP_BIN}"
    result = subprocess.run(
        [str(_SCIP_BIN), "--version"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0 or "scip-clang" in (result.stdout + result.stderr).lower()

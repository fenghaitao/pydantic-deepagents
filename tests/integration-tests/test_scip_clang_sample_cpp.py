"""Integration test: index tests/integration-tests/sample-cpp with scip-clang
via ``cgc index . --force``, then verify that expected nodes and edges are
present in the KuzuDB knowledge graph.

Usage (from the pydantic-deepagents repo root):
    .venv/bin/pytest tests/integration-tests/test_scip_clang.py -v -s

Prerequisites:
    scip-clang binary must be available — either via:
        make setup-scip-clang            (download, default)
        make setup-scip-clang-build      (build from source)
    The sample-cpp project must have a compile_commands.json in its build dir.
    Run gen-compile-commands.sh once if it has not been generated:
        bash tests/integration-tests/sample-cpp/gen-compile-commands.sh
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# ── Paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT   = Path(__file__).resolve().parents[2]
_SAMPLE_CPP  = _REPO_ROOT / "tests" / "integration-tests" / "sample-cpp"
_DB_PATH     = _SAMPLE_CPP / ".codegraphcontext" / "db" / "kuzudb"
_SCIP_BIN    = _REPO_ROOT / "code-graph-providers" / "scip-languages" / "bin" / "scip-clang"
_CGC         = shutil.which("cgc") or str(_REPO_ROOT / ".venv" / "bin" / "cgc")

# ── Skip conditions ────────────────────────────────────────────────────────────
_SCIP_MISSING = not _SCIP_BIN.exists()
_CGC_MISSING  = not Path(_CGC).exists()


@pytest.fixture(scope="module")
def indexed_db():
    """Run ``cgc index . --force`` in sample-cpp and return a kuzu Connection."""
    if _SCIP_MISSING:
        pytest.skip(
            f"scip-clang binary not found at {_SCIP_BIN}. "
            "Run: make setup-scip-clang"
        )
    if _CGC_MISSING:
        pytest.skip(f"cgc not found at {_CGC}")

    # Ensure compile_commands.json is available at the project root (where
    # scip-clang expects it). gen-compile-commands.sh generates it in build/
    # and copies it to the root.
    _compdb_root = _SAMPLE_CPP / "compile_commands.json"
    if not _compdb_root.exists():
        gen = subprocess.run(
            ["bash", "gen-compile-commands.sh"],
            cwd=str(_SAMPLE_CPP),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if gen.returncode != 0:
            pytest.skip(
                f"Could not generate compile_commands.json (cmake missing?):\n"
                f"{gen.stderr}"
            )

    result = subprocess.run(
        [_CGC, "index", ".", "--force"],
        cwd=str(_SAMPLE_CPP),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(
            f"cgc index failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    # Verify the indexing method banner confirms SCIP was used (not Tree-sitter fallback)
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
    # kuzu connections have no explicit close


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
    """graph.h, graph.cpp, and main.cpp must all be indexed as File nodes."""
    rows = _one(indexed_db, "MATCH (n:File) RETURN n.name")
    names = {r[0] for r in rows}
    assert "graph.h"   in names
    assert "graph.cpp" in names
    assert "main.cpp"  in names


def test_class_graph_present(indexed_db):
    """The Graph class from graph.h must be indexed."""
    rows = _one(
        indexed_db,
        "MATCH (n:Class) WHERE n.name CONTAINS 'Graph' RETURN n.name, n.path",
    )
    assert rows, "No Class node with name containing 'Graph' found"
    # At least one entry should come from graph.h
    assert any("graph.h" in (r[1] or "") for r in rows), (
        f"Graph class not found in graph.h: {rows}"
    )


def test_file_contains_class(indexed_db):
    """graph.h must CONTAIN the Graph class (or its inner types)."""
    rows = _one(
        indexed_db,
        "MATCH (f:File)-[:CONTAINS]->(c:Class) "
        "WHERE f.name = 'graph.h' RETURN c.name",
    )
    class_names = {r[0] for r in rows}
    assert class_names, "graph.h CONTAINS no Class nodes"
    # Graph, Node (inner struct), NodeId (type alias) should all appear
    assert any("Graph" in n or "Node" in n for n in class_names), (
        f"Expected Graph/Node classes in graph.h, got: {class_names}"
    )


def test_repository_node_present(indexed_db):
    """A Repository node for the sample-cpp path must exist."""
    rows = _one(indexed_db, "MATCH (n:Repository) RETURN n.path")
    assert rows, "No Repository node found"
    assert any("sample-cpp" in (r[0] or "") for r in rows), (
        f"sample-cpp repository not found: {rows}"
    )


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

"""Integration test: parse a C/C++ project via the pydantic-deep CLI
(which calls the already-running potpie REST API), then verify that expected
nodes and edges produced by scip-clang are present in the Neo4j knowledge graph.

Usage (from the pydantic-deepagents repo root):
    .venv/bin/pytest tests/integration-tests/test_scip_clang_potpie.py -v -s

Prerequisites:
    The potpie backend must be running and healthy:
        make -C code-graph-providers/potpie check-health HEALTH_FLAGS="--api-retries 15"
    scip-clang must be available (SCIP_CLANG_BIN or on PATH):
        bash code-graph-providers/scip-languages/setup-scip-clang.sh
    NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD must be set (via export-ports
    or potpie/.env loaded automatically by the conftest).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import pytest
from conftest import extract_json_from_output
from dotenv import load_dotenv
from neo4j import GraphDatabase

# ── Paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_POTPIE_ROOT = _REPO_ROOT / "code-graph-providers" / "potpie"
_SAMPLE_CPP = Path(__file__).resolve().parent / "sample-cpp-ns"

load_dotenv(_POTPIE_ROOT / ".env")


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── What to verify ─────────────────────────────────────────────────────────────
# Format: (node_type, node_name)
# TODO: populate with expected nodes from scip-clang parsing of sample-cpp
nodes_to_check: List[Tuple[str, str]] = [
    ("FILE", "main.cpp"),
    ("FILE", "graph.h"),
    ("FILE", "graph.cpp"),
    ("NAMESPACE", "CodeAnalysis"),
    ("FUNCTION", "main"),
    ("CLASS", "CodeAnalysis.Graph"),
    ("CLASS", "CodeAnalysis.Graph.Node"),
    ("CLASS", "CodeAnalysis.CodeGraph"),
    ("FUNCTION", "CodeAnalysis.Graph.add_node"),
    ("FUNCTION", "CodeAnalysis.Graph.add_edge"),
    ("FUNCTION", "CodeAnalysis.Graph.count_node"),
    ("FUNCTION", "CodeAnalysis.Graph.count_edge"),
    ("FUNCTION", "CodeAnalysis.CodeGraph.docstring"),
    ("FUNCTION", "CodeAnalysis.CodeGraph.source_code")
]

# Format: (src_type, src_name, edge_type, tgt_type, tgt_name)
# TODO: populate with expected edges from scip-clang parsing of sample-cpp
edges_to_check: List[Tuple[str, str, str, str, str]] = [
    ("FILE", "main.cpp", "CONTAINS", "FUNCTION", "main"),
    ("FILE", "graph.h", "CONTAINS", "CLASS", "CodeAnalysis.Graph"),
    ("NAMESPACE", "CodeAnalysis", "CONTAINS", "CLASS", "CodeAnalysis.Graph"),
    ("NAMESPACE", "CodeAnalysis", "CONTAINS", "CLASS", "CodeAnalysis.CodeGraph"),
    ("CLASS", "CodeAnalysis.Graph", "CONTAINS", "CLASS", "CodeAnalysis.Graph.Node"),
    ("CLASS", "CodeAnalysis.Graph", "CONTAINS", "FUNCTION", "CodeAnalysis.Graph.add_node"),
    ("CLASS", "CodeAnalysis.Graph", "CONTAINS", "FUNCTION", "CodeAnalysis.Graph.add_edge"),
    ("CLASS", "CodeAnalysis.Graph", "CONTAINS", "FUNCTION", "CodeAnalysis.Graph.count_edge"),
    ("CLASS", "CodeAnalysis.Graph", "CONTAINS", "FUNCTION", "CodeAnalysis.Graph.count_node"),
    ("FUNCTION", "main", "REFERENCES", "FUNCTION", "CodeAnalysis.Graph.add_node"),
    ("FUNCTION", "main", "REFERENCES", "FUNCTION", "CodeAnalysis.Graph.add_edge"),
    ("FUNCTION", "main", "REFERENCES", "FUNCTION", "CodeAnalysis.Graph.count_node"),
    ("FUNCTION", "main", "REFERENCES", "FUNCTION", "CodeAnalysis.Graph.count_edge"),
    ("FUNCTION", "main", "REFERENCES", "FUNCTION", "CodeAnalysis.CodeGraph.docstring"),
    ("FUNCTION", "main", "REFERENCES", "FUNCTION", "CodeAnalysis.CodeGraph.source_code"),
    ("CLASS", "CodeAnalysis.CodeGraph", "EXTENDS", "CLASS", "CodeAnalysis.Graph"),
]


# ── Neo4j helper ───────────────────────────────────────────────────────────────

class Neo4jChecker:
    def __init__(self, uri: str, user: str, password: str, project_id: str) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self.project_id = project_id
        # self.dump_all_nodes_and_edges()

    def dump_all_nodes_and_edges(self) -> None:
        print(f"[{_ts()}] Dumping all nodes and edges for project_id={self.project_id}...")
        with self._driver.session() as session:
            nodes = session.run(
                "MATCH (n:NODE {repoId: $project_id}) RETURN n.type AS type, n.name AS name",
                project_id=self.project_id
            ).data()
            edges = session.run(
                """
                MATCH (src:NODE {repoId: $project_id})-[r]->(tgt:NODE {repoId: $project_id})
                RETURN src.type AS src_type, src.name AS src_name,
                       type(r) AS edge_type,
                       tgt.type AS tgt_type, tgt.name AS tgt_name
                """,
                project_id=self.project_id
            ).data()
        print(f"[{_ts()}] Nodes ({len(nodes)}):")
        for node in nodes:
            print(f"  NODE  type={node['type']!r}, name={node['name']!r}")
        print(f"[{_ts()}] Edges ({len(edges)}):")
        for edge in edges:
            print(
                f"  EDGE  ({edge['src_type']}:{edge['src_name']})-[{edge['edge_type']}]->"
                f"({edge['tgt_type']}:{edge['tgt_name']})"
            )

    def close(self) -> None:
        self._driver.close()

    def check_node_exists(self, node_type: str, node_name: str) -> bool:
        query = """
            MATCH (n:NODE {repoId: $project_id})
            WHERE n.type = $node_type AND n.name = $node_name
            RETURN count(n) AS cnt
        """
        with self._driver.session() as session:
            record = session.run(
                query, project_id=self.project_id,
                node_type=node_type, node_name=node_name,
            ).single()
            found = (record["cnt"] > 0) if record else False
            print(f"{'Found' if found else 'Missing'} {node_type}:{node_name}")
            return found

    def check_edge_exists(
        self, src_type: str, src_name: str, edge_type: str, tgt_type: str, tgt_name: str
    ) -> bool:
        query = f"""
            MATCH (src:NODE {{repoId: $project_id}})-[r:{edge_type}]->(tgt:NODE {{repoId: $project_id}})
            WHERE src.type = $src_type AND src.name = $src_name
              AND tgt.type = $tgt_type AND tgt.name = $tgt_name
            RETURN count(r) AS cnt
        """
        with self._driver.session() as session:
            record = session.run(
                query, project_id=self.project_id,
                src_type=src_type, src_name=src_name,
                tgt_type=tgt_type, tgt_name=tgt_name,
            ).single()
            found = (record["cnt"] > 0) if record else False
            print(f"{'Found' if found else 'Missing'} ({src_type}:{src_name})-[{edge_type}]->({tgt_type}:{tgt_name})")
            return found


# ── Test ───────────────────────────────────────────────────────────────────────

def test_scip_clang_parse_and_check_graph(pydantic_deep_runner):
    if not _SAMPLE_CPP.exists():
        pytest.skip(f"sample-cpp not found at {_SAMPLE_CPP}")
    _run_workflow(pydantic_deep_runner, _SAMPLE_CPP)


def _run_workflow(pydantic_deep_runner, sample_cpp_dir: Path) -> None:
    repo_name = sample_cpp_dir.name  # "sample-cpp"

    # Step 1: Check for existing project and delete if present
    print(f"[{_ts()}] Step 1: Checking for existing project entry")
    list_result = pydantic_deep_runner("projects", "list", "--json", check=False)
    print(f"[{_ts()}] projects list exit code: {list_result.returncode}")
    if list_result.stdout:
        print(f"[{_ts()}] projects list stdout:\n{list_result.stdout}")
    if list_result.stderr:
        print(f"[{_ts()}] projects list stderr:\n{list_result.stderr}")

    existing_project_id = None
    try:
        for project in json.loads(extract_json_from_output(list_result.stdout)):
            if project.get("repo_name") == repo_name:
                existing_project_id = project.get("id")
                break
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        print(f"[{_ts()}] Failed to parse projects list output: {exc}")

    if existing_project_id:
        print(f"[{_ts()}] Removing existing project for {repo_name!r} (id={existing_project_id})")
        remove_result = pydantic_deep_runner(
            "projects", "delete", existing_project_id, "-f", check=False
        )
        print(f"[{_ts()}] projects delete exit code: {remove_result.returncode}")
        if remove_result.stdout:
            print(f"[{_ts()}] projects delete stdout:\n{remove_result.stdout}")
        if remove_result.stderr:
            print(f"[{_ts()}] projects delete stderr:\n{remove_result.stderr}")
        assert remove_result.returncode == 0, (
            f"project deletion failed (exit {remove_result.returncode}):\n{remove_result.stderr}"
        )
    else:
        print(f"[{_ts()}] No existing project found for {repo_name!r}")

    # Step 2: Parse the repository
    print(f"[{_ts()}] Step 2: Parsing repository {sample_cpp_dir}")
    parse_result = pydantic_deep_runner("parse", "repo", str(sample_cpp_dir))
    print(f"[{_ts()}] Step 2 done (exit {parse_result.returncode})")
    if parse_result.stdout:
        print(f"[{_ts()}] parse stdout:\n{parse_result.stdout}")
    assert parse_result.returncode == 0, (
        f"parse repo failed (exit {parse_result.returncode}):\n{parse_result.stderr}"
    )

    # Step 3: Resolve the project-id
    print(f"[{_ts()}] Step 3: Resolving project-id")
    list_result = pydantic_deep_runner("projects", "list", "--json", check=False)
    if list_result.stdout:
        print(f"[{_ts()}] projects list stdout:\n{list_result.stdout}")

    project_id = None
    try:
        for project in json.loads(extract_json_from_output(list_result.stdout)):
            if project.get("repo_name") == repo_name:
                project_id = project["id"]
                break
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"[{_ts()}] Failed to parse projects list output: {exc}")

    assert project_id, (
        f"Project should be registered after parsing (repo_name={repo_name!r}).\n"
        f"  exit={list_result.returncode}\n"
        f"  stdout={list_result.stdout!r}\n"
        f"  stderr={list_result.stderr!r}"
    )
    print(f"[{_ts()}] Project ID: {project_id}")

    # Step 4: Check nodes and edges in Neo4j
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    print(
        f"[{_ts()}] Step 4: Checking {len(nodes_to_check)} nodes and "
        f"{len(edges_to_check)} edges in Neo4j (uri={uri}, project_id={project_id})"
    )

    if not nodes_to_check and not edges_to_check:
        print(f"[{_ts()}] WARNING: nodes_to_check and edges_to_check are empty — "
              "test passes trivially. Populate them with expected graph elements.")
        return

    checker = Neo4jChecker(uri, user, password, project_id)

    try:
        missing_nodes = [
            f"  NODE  type={nt!r}, name={nn!r}"
            for nt, nn in nodes_to_check
            if not checker.check_node_exists(nt, nn)
        ]
        missing_edges = [
            f"  EDGE  ({st}:{sn})-[{et}]->({tt}:{tn})"
            for st, sn, et, tt, tn in edges_to_check
            if not checker.check_edge_exists(st, sn, et, tt, tn)
        ]
        failures = missing_nodes + missing_edges
        assert not failures, (
            f"The following graph elements were missing (project_id={project_id}):\n"
            + "\n".join(failures)
        )
    finally:
        checker.close()
        print(f"[{_ts()}] Cleaning up project {project_id}...")
        remove_result = pydantic_deep_runner("projects", "delete", project_id, "-f", check=False)
        print(f"[{_ts()}] Cleanup done (exit {remove_result.returncode})")
        if remove_result.stderr:
            print(f"[{_ts()}] projects delete stderr:\n{remove_result.stderr}")

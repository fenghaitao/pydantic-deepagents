"""Integration test: parse a DML simics-project via the pydantic-deep CLI
(which calls the already-running potpie REST API), then verify that expected
nodes and edges are present in the Neo4j knowledge graph.

Using ``pydantic-deep parse repo`` instead of ``potpie_cli parse repo`` means
the CLI is just a thin REST client — all ML model loading happens inside the
already-running backend, so the command completes in seconds rather than
minutes.

Usage (from the pydantic-deepagents repo root):
    .venv/bin/pytest tests/integration-tests/test_scip_dml.py -v -s

Prerequisites:
    The potpie backend must be running and healthy:
        make -C code-graph-providers/potpie check-health HEALTH_FLAGS="--api-retries 15"
    DLS must be built:
        make -C code-graph-providers/potpie build-dls
    The simics-project must be initialised:
        (cd code-graph-providers/potpie/tests/integration-tests/scip-dml/simics-project && \\
          /nfs/site/disks/.../bin/project-setup --ignore-existing-files .)
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
_SIMICS_PROJECT = (
    _POTPIE_ROOT / "tests" / "integration-tests" / "scip-dml" / "simics-project"
)

load_dotenv(_POTPIE_ROOT / ".env")


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── What to verify ─────────────────────────────────────────────────────────────

nodes_to_check: List[Tuple[str, str]] = [
    ("FILE",     "modules/wdt/wdt.dml"),
    ("FILE",     "modules/wdt/wdt-registers.dml"),
    ("DEVICE",   "wdt"),
    ("BANK",     "modules/wdt/wdt.dml:WatchdogRegisters"),
    ("REGISTER", "modules/wdt/wdt.dml:WatchdogRegisters.WDOGLOAD"),
    ("REGISTER", "modules/wdt/wdt.dml:WatchdogRegisters.WDOGVALUE"),
    ("REGISTER", "modules/wdt/wdt.dml:WatchdogRegisters.WDOGCONTROL"),
    ("REGISTER", "modules/wdt/wdt.dml:WatchdogRegisters.WDOGINTCLR"),
    ("TEMPLATE", "modules/wdt/wdt-registers.dml:WatchdogRegisters_temp"),
    ("CONNECT",  "modules/wdt/wdt.dml:wdogint"),
    ("CONNECT",  "modules/wdt/wdt.dml:wdogres"),
    ("PORT",     "modules/wdt/wdt.dml:wclk"),
    ("PORT",     "modules/wdt/wdt.dml:wclk_en"),
    ("PORT",     "modules/wdt/wdt.dml:wrst_n"),
    ("PORT",     "modules/wdt/wdt.dml:prst_n"),
    ("EVENT",    "modules/wdt/wdt.dml:timeout_event"),
    ("FUNCTION", "modules/wdt/wdt.dml:schedule_timeout"),
    ("FUNCTION", "modules/wdt/wdt.dml:update_interrupt_signal"),
    ("ATTRIBUTE", "modules/wdt/wdt.dml:counter_value"),
    ("FUNCTION", "modules/wdt/wdt.dml:counter_value.refresh"),
]

edges_to_check: List[Tuple[str, str, str, str, str]] = [
    ("FILE",     "modules/wdt/wdt.dml",           "IMPORTS",    "FILE",      "modules/wdt/wdt-registers.dml"),
    ("FILE",     "modules/wdt/wdt.dml",           "CONTAINS",   "DEVICE",    "wdt"),
    ("DEVICE",   "wdt",                           "CONTAINS",   "BANK",      "modules/wdt/wdt.dml:WatchdogRegisters"),
    ("DEVICE",   "wdt",                           "CONTAINS",   "PORT",      "modules/wdt/wdt.dml:wrst_n"),
    ("DEVICE",   "wdt",                           "CONTAINS",   "EVENT",     "modules/wdt/wdt.dml:timeout_event"),
    ("BANK",     "modules/wdt/wdt.dml:WatchdogRegisters", "CONTAINS",   "REGISTER",  "modules/wdt/wdt.dml:WatchdogRegisters.WDOGLOAD"),
    ("BANK",     "modules/wdt/wdt.dml:WatchdogRegisters", "IMPLEMENTS", "TEMPLATE",  "modules/wdt/wdt-registers.dml:WatchdogRegisters_temp"),
    ("PORT",     "modules/wdt/wdt.dml:wclk",      "IMPLEMENTS", "INTERFACE", "signal"),
    ("CONNECT",  "modules/wdt/wdt.dml:wdogint",   "REFERENCES", "INTERFACE", "signal"),
    ("FUNCTION", "modules/wdt/wdt.dml:timeout_event.event", "REFERENCES", "FUNCTION", "modules/wdt/wdt.dml:schedule_timeout"),
    ("EVENT",    "modules/wdt/wdt.dml:timeout_event", "CONTAINS", "FUNCTION", "modules/wdt/wdt.dml:timeout_event.event"),
    ("PORT",     "modules/wdt/wdt.dml:prst_n",    "CONTAINS",   "FUNCTION",  "modules/wdt/wdt.dml:prst_n.signal_raise"),
    ("DEVICE",  "wdt",                           "CONTAINS",   "ATTRIBUTE", "modules/wdt/wdt.dml:counter_value"),
    ("ATTRIBUTE", "modules/wdt/wdt.dml:counter_value", "CONTAINS",   "FUNCTION",  "modules/wdt/wdt.dml:counter_value.refresh"),
]


# ── Neo4j helper ───────────────────────────────────────────────────────────────

class Neo4jChecker:
    def __init__(self, uri: str, user: str, password: str, project_id: str) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self.project_id = project_id

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

def test_parse_repo_then_check_graph(pydantic_deep_runner):
    if not _SIMICS_PROJECT.exists():
        pytest.skip(f"simics-project not found at {_SIMICS_PROJECT}")
    _run_workflow(pydantic_deep_runner, _SIMICS_PROJECT)


def _run_workflow(pydantic_deep_runner, simics_project_dir: Path) -> None:
    repo_name = simics_project_dir.name  # "simics-project"

    # Step 0: remove any pre-existing project entry
    print(f"[{_ts()}] Step 0: Checking for existing project entry")
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

    # Step 1: parse the repository (pydantic-deep calls the REST API; it polls
    # until READY so the CLI exits only when parsing is complete)
    print(f"[{_ts()}] Step 1: Parsing repository {simics_project_dir}")
    parse_result = pydantic_deep_runner("parse", "repo", str(simics_project_dir))
    print(f"[{_ts()}] Step 1 done (exit {parse_result.returncode})")
    if parse_result.stdout:
        print(f"[{_ts()}] parse stdout:\n{parse_result.stdout}")
    assert parse_result.returncode == 0, (
        f"parse repo failed (exit {parse_result.returncode}):\n{parse_result.stderr}"
    )

    # Step 2: resolve the project-id
    print(f"[{_ts()}] Step 2: Resolving project-id")
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

    # Step 3: check nodes and edges
    uri      = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
    user     = os.environ.get("NEO4J_USERNAME",  "neo4j")
    password = os.environ.get("NEO4J_PASSWORD",  "")
    print(
        f"[{_ts()}] Step 3: Checking {len(nodes_to_check)} nodes and "
        f"{len(edges_to_check)} edges in Neo4j (uri={uri}, project_id={project_id})"
    )
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

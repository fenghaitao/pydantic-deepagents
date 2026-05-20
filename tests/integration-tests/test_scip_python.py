"""
Integration test: sparse-checkout srv-pm/modules/srv-pm-testlib from
https://github.com/intel-restricted/applications.simulators.isim.vp,
parse it via the pydantic-deep CLI (which calls the already-running potpie
REST API), then verify that expected nodes and edges are present in the
Neo4j knowledge graph.

Using ``pydantic-deep parse repo`` instead of ``potpie_cli parse repo`` means
the CLI is just a thin REST client — all ML model loading happens inside the
already-running backend, so the command completes in seconds rather than
minutes.

Usage (from the pydantic-deepagents repo root):
    .venv/bin/pytest tests/integration-tests/test_scip_python.py -v -s

Prerequisites:
    The potpie backend must be running and healthy:
        make -C code-graph-providers/potpie check-health HEALTH_FLAGS="--api-retries 15"
    NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD must be set (via export-ports
    or potpie/.env loaded automatically by the conftest).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import pytest
from dotenv import load_dotenv
from conftest import extract_json_from_output
from neo4j import GraphDatabase

# ── Paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_POTPIE_ROOT = _REPO_ROOT / "code-graph-providers" / "potpie"

# Load potpie .env to pick up dynamic port assignments (NEO4J_URI, BOLT_PORT…).
load_dotenv(_POTPIE_ROOT / ".env")

_EVAL_SCRIPT = _POTPIE_ROOT / ".kiro" / "skills" / "potpie-evaluator" / "scripts" / "evaluate_qna.py"
_EVAL_CASES = (
    _POTPIE_ROOT
    / "tests"
    / "integration-tests"
    / "scip-python"
    / "qna_eval_srv_pm_testlib_cases.yaml"
)


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Source repository ──────────────────────────────────────────────────────────

_REPO_URL   = "https://github.com/intel-restricted/applications.simulators.isim.vp"
_SPARSE_PATH = "srv-pm/modules/srv-pm-testlib"
_REPO_NAME  = "srv-pm-testlib"   # directory name after sparse-checkout → potpie project name

# ── What to verify ─────────────────────────────────────────────────────────────

nodes_to_check: List[Tuple[str, str]] = [
    ("FILE",     "base.py"),
    ("FILE",     "checker/base.py"),
    ("CLASS",    "modules.srv-pm-testlib.base.PMTestFlow"),
    ("FUNCTION", "modules.srv-pm-testlib.base.PMTestFlow.action"),
]

edges_to_check: List[Tuple[str, str, str, str, str]] = [
    ("FILE",  "base.py",                                    "CONTAINS", "CLASS", "modules.srv-pm-testlib.base.PMTestFlow"),
    ("CLASS", "modules.srv-pm-testlib.base.BiosCplTestFlow", "EXTENDS",  "CLASS", "modules.srv-pm-testlib.base.PMTestFlow"),
    ("FILE",  "testcase.py",                                "IMPORTS",  "FILE",  "_base.py"),
]


# ── Neo4j helper ───────────────────────────────────────────────────────────────

class Neo4jChecker:
    def __init__(self, uri: str, user: str, password: str, project_id: str) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self.project_id = project_id

    def close(self) -> None:
        self._driver.close()

    def any_nodes_exist(self) -> int:
        query = "MATCH (n:NODE {repoId: $project_id}) RETURN count(n) AS cnt"
        with self._driver.session() as session:
            record = session.run(query, project_id=self.project_id).single()
            return record["cnt"] if record else 0

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


# ── QnA Evaluation ─────────────────────────────────────────────────────────────

def _run_eval(project_id: str, output_dir: Path, *, fast: bool = False) -> None:
    """Run the potpie QnA evaluator for *project_id* using the srv-pm-testlib
    question set and write the score report to *output_dir*.

    Parameters
    ----------
    fast:
        When True (``--fast`` pytest flag), pass ``--max-cases 1`` to the
        evaluator so only the first question is scored.  Useful for a quick
        smoke-test without running the full dataset.
    """
    if not _EVAL_SCRIPT.exists():
        pytest.fail(
            f"QnA evaluator script not found: {_EVAL_SCRIPT}\n"
            "This usually means the potpie sources are unavailable locally. "
            "Ensure the code-graph-providers/potpie git submodule is checked "
            "out and up to date, or verify that the evaluator script has not "
            "been moved or deleted."
        )

    if not _EVAL_CASES.exists():
        pytest.fail(
            f"QnA evaluation cases not found: {_EVAL_CASES}\n"
            "The evaluator test data is missing. Ensure the "
            "code-graph-providers/potpie git submodule is checked out and up "
            "to date, or verify that the evaluation cases path is correct."
        )

    output_path = output_dir / "qna_eval_srv_pm_testlib_score.md"
    cmd = [
        sys.executable,
        str(_EVAL_SCRIPT),
        "--cases",      str(_EVAL_CASES),
        "--project-id", project_id,
        "--output",     str(output_path),
        # AgentBehaviorCompliance requires an agentic judge with multiple LLM
        # tool-call rounds per rubric (5 rubrics × 15 cases ≈ 300+ LLM calls)
        # and scores only ~15% — skip it to keep the test under 30 minutes.
        "--skip-metrics", "AgentBehaviorCompliance",
    ]
    if fast:
        cmd += ["--max-cases", "1"]
        print(f"[{_ts()}] Fast mode: evaluating 1 case only")
    print(f"[{_ts()}] Running QnA evaluation (project_id={project_id})")
    print(f"[{_ts()}]   command: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    output_lines: list[str] = []

    def _stream() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            print(f"  [eval] {line}", flush=True)
            output_lines.append(line)

    t = threading.Thread(target=_stream, daemon=True)
    t.start()
    try:
        proc.wait(timeout=7200)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        t.join(timeout=5)
        tail_lines = output_lines[-200:] if len(output_lines) > 200 else output_lines
        pytest.fail(
            "QnA evaluator timed out after 7200 seconds and was terminated.\n"
            f"output (last {len(tail_lines)} lines):\n" + "\n".join(tail_lines)
        )
    t.join(timeout=5)

    print(f"[{_ts()}] QnA evaluator returncode: {proc.returncode}", flush=True)
    tail_lines = output_lines[-200:] if len(output_lines) > 200 else output_lines
    if proc.returncode != 0:
        pytest.fail(
            f"QnA evaluator failed (exit {proc.returncode}).\n"
            f"output (last {len(tail_lines)} lines):\n" + "\n".join(tail_lines)
        )

    if not output_path.exists():
        pytest.fail(
            "QnA evaluator exited successfully but did not produce the expected "
            f"report file: {output_path}"
        )

    score_text = output_path.read_text()
    for line in score_text.splitlines()[:30]:
        print(f"  [eval] {line}")
    print(f"[{_ts()}] Full eval report: {output_path}")


# ── Test ───────────────────────────────────────────────────────────────────────

def test_parse_repo_then_check_graph(pydantic_deep_runner, sparse_checkout, fast_mode):
    workspace = tempfile.TemporaryDirectory(prefix="test-scip-python-")
    saved_cwd = os.getcwd()
    try:
        os.chdir(workspace.name)
        checked_out = sparse_checkout(_REPO_URL, [_SPARSE_PATH])
        # Resolve to absolute path now while still cwd'd inside the temp dir.
        # pydantic_deep_runner runs with cwd=_REPO_ROOT, so relative paths
        # produced by sparse_checkout would not be found there.
        src_dir = Path(checked_out[0]).resolve()
        # Mark the checked-out directory as Python-only for potpie's indexer.
        with open(src_dir / ".potpieallowed.json", "w") as fh:
            json.dump({"language": [".py"]}, fh)
        print(f"[{_ts()}] Sparse-checkout ready at {src_dir}")
        if fast_mode:
            print(f"[{_ts()}] Fast mode enabled: QnA eval will run only the first case")
        _run_workflow(pydantic_deep_runner, src_dir, output_dir=Path(saved_cwd), fast=fast_mode)
    finally:
        os.chdir(saved_cwd)
        workspace.cleanup()


def _run_workflow(pydantic_deep_runner, src_dir: Path, output_dir: Path = Path("."), *, fast: bool = False) -> None:
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
            if project.get("repo_name") == _REPO_NAME:
                existing_project_id = project.get("id")
                break
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        print(f"[{_ts()}] Failed to parse projects list output: {exc}")

    if existing_project_id:
        print(f"[{_ts()}] Removing existing project for {_REPO_NAME!r} (id={existing_project_id})")
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
        print(f"[{_ts()}] No existing project found for {_REPO_NAME!r}")

    # Step 1: parse the repository (pydantic-deep calls the REST API; it polls
    # until READY so the CLI exits only when parsing is complete)
    print(f"[{_ts()}] Step 1: Parsing repository {src_dir}")
    parse_result = pydantic_deep_runner("parse", "repo", str(src_dir))
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
    if list_result.stderr:
        print(f"[{_ts()}] projects list stderr:\n{list_result.stderr}")

    project_id = None
    try:
        for project in json.loads(extract_json_from_output(list_result.stdout)):
            if project.get("repo_name") == _REPO_NAME:
                project_id = project["id"]
                break
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"[{_ts()}] Failed to parse projects list output: {exc}")

    assert project_id, (
        f"Project should be registered after parsing (repo_name={_REPO_NAME!r}).\n"
        f"  exit={list_result.returncode}\n"
        f"  stdout={list_result.stdout!r}\n"
        f"  stderr={list_result.stderr!r}"
    )
    print(f"[{_ts()}] Project ID: {project_id}")

    # Step 3: check nodes and edges
    uri      = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
    user     = os.environ.get("NEO4J_USERNAME",  "neo4j")
    password = os.environ.get("NEO4J_PASSWORD",  "")
    checker = Neo4jChecker(uri, user, password, project_id)

    try:
        total_nodes = checker.any_nodes_exist()
        print(f"[{_ts()}] Total nodes in graph: {total_nodes}")
        assert total_nodes > 0, (
            f"No nodes found in Neo4j for project_id={project_id}. "
            "scip-python may have failed to index the repository."
        )

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

        # Step 4: QnA evaluation against the indexed project
        _run_eval(project_id, output_dir, fast=fast)

    finally:
        checker.close()
        print(f"[{_ts()}] Cleaning up project {project_id}...")
        remove_result = pydantic_deep_runner("projects", "delete", project_id, "-f", check=False)
        print(f"[{_ts()}] Cleanup done (exit {remove_result.returncode})")
        if remove_result.stderr:
            print(f"[{_ts()}] projects delete stderr:\n{remove_result.stderr}")

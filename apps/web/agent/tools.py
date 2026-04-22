"""
Tools for the pydantic-deep web agent — uses PotpieRuntime directly.

PotpieRuntime makes direct in-process calls to the code graph runtime
(no HTTP overhead). Same backend used by the pydantic-deep CLI.
"""
import asyncio
import json
import logging
import os
import subprocess
import uuid
from pydantic_ai import RunContext
from pydantic_ai.ag_ui import StateDeps
from models import PotpieState

from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

logger = logging.getLogger(__name__)

# Module-level singleton — lazily initialises PotpieRuntime on first call.
runtime = PotpieRuntime(
    user_id=os.getenv("POTPIE_USER_ID", "defaultuser"),
)

# In-memory parse job tracker: job_id → {"status": ..., "result": ...}
_parse_jobs: dict[str, dict] = {}


def _detect_head_commit(repo_path: str) -> str | None:
    """Detect the HEAD commit SHA for a local repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


async def list_projects(ctx: RunContext[StateDeps[PotpieState]]) -> list[dict]:
    """List all parsed projects. Always call this first to find available projects."""
    projects = await runtime.list_projects()
    ctx.deps.state.projects = projects
    return projects


async def parse_repo(
    ctx: RunContext[StateDeps[PotpieState]],
    repo_path: str,
    branch: str = "main",
) -> str:
    """Start parsing a local repository in the background.
    Returns a job_id immediately — use get_parsing_status(job_id) to poll progress."""
    commit_id = _detect_head_commit(repo_path)
    job_id = str(uuid.uuid4())[:8]
    _parse_jobs[job_id] = {"status": "running", "result": None}

    async def _run():
        try:
            result = await runtime.parse(
                repo_path=repo_path,
                repo_name=None,
                branch=branch,
                commit_id=commit_id,
            )
            _parse_jobs[job_id] = {"status": result.get("status", "done"), "result": result}
        except Exception as exc:
            _parse_jobs[job_id] = {"status": "error", "result": {"error": str(exc)}}

    asyncio.create_task(_run())
    return (
        f"Parsing started for {repo_path} (branch={branch}). "
        f"job_id={job_id}. Call get_parsing_status('{job_id}') to check progress."
    )


async def get_parsing_status(
    ctx: RunContext[StateDeps[PotpieState]],
    project_id_or_job_id: str,
) -> dict:
    """Check parsing status. Pass either a job_id from parse_repo or a project_id."""
    if project_id_or_job_id in _parse_jobs:
        job = _parse_jobs[project_id_or_job_id]
        result = {"job_id": project_id_or_job_id, "status": job["status"]}
        if job["result"]:
            result.update(job["result"])
        return result
    return await runtime.parsing_status(project_id_or_job_id)


async def search_codebase(
    ctx: RunContext[StateDeps[PotpieState]],
    query: str,
    project_id: str | None = None,
) -> str:
    """Fast keyword search across indexed codebase. Returns matching code snippets.
    Use this for quick lookups of specific symbols, function names, or code patterns."""
    pid = project_id or ctx.deps.state.project_id
    if not pid:
        raise ValueError("No project selected. Call list_projects or parse_repo first.")
    results = await runtime.search(project_id=pid, query=query)
    return json.dumps(results, indent=2)


async def query_code_graph(
    ctx: RunContext[StateDeps[PotpieState]],
    question: str,
    project_id: str | None = None,
) -> str:
    """Structural query on the code knowledge graph (call graphs, imports, inheritance).
    Use this for questions like 'What functions call X?' or 'What does class Y inherit from?'"""
    pid = project_id or ctx.deps.state.project_id
    if not pid:
        raise ValueError("No project selected. Call list_projects or parse_repo first.")
    result = await runtime.nl_query(project_id=pid, query=question)
    return json.dumps(result, indent=2)


async def ask_knowledge_graph(
    ctx: RunContext[StateDeps[PotpieState]],
    questions: list[str],
    project_id: str | None = None,
) -> str:
    """Semantic search via knowledge graph embeddings. Good for finding code by description
    or docstring similarity. Pass one or more natural language questions.
    Note: requires project to be fully parsed (not in INFERRING state)."""
    pid = project_id or ctx.deps.state.project_id
    if not pid:
        raise ValueError("No project selected. Call list_projects or parse_repo first.")
    status_resp = await runtime.parsing_status(pid)
    status = status_resp.get("status", "").upper()
    if status in ("INFERRING", "PARSING", "SUBMITTED"):
        return (
            f"Project is still {status} — semantic search is not available yet. "
            "Use search_codebase or query_code_graph instead."
        )
    results = await runtime.kg_search(project_id=pid, queries=questions)
    return json.dumps(results, indent=2)


async def set_active_project(
    ctx: RunContext[StateDeps[PotpieState]],
    project_id: str,
) -> str:
    """Set the active project for subsequent queries."""
    ctx.deps.state.project_id = project_id
    return f"Active project set to {project_id}"


# ── Shell / CLI tools (aligned with pydantic-deep CLI capabilities) ───────

from pathlib import Path  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[4]  # pydantic-deep root
_VENV_BIN = _REPO_ROOT / ".venv" / "bin"
_PYDANTIC_DEEP = str(_VENV_BIN / "pydantic-deep")

# Commands the web agent is allowed to run.
_ALLOW_LIST = [
    "pydantic-deep", "git", "ls", "cat", "head", "tail", "find", "grep",
    "wc", "tree", "file", "python", "pip", "which", "echo", "pwd",
]


def _is_allowed(command: str) -> tuple[bool, str]:
    """Check if a shell command is in the allow-list."""
    cmd_base = command.strip().split()[0] if command.strip() else ""
    for allowed in _ALLOW_LIST:
        if cmd_base == allowed or command.strip().startswith(f"{allowed} "):
            return True, ""
    return False, (
        f"Command '{cmd_base}' is not allowed. "
        f"Allowed: {', '.join(_ALLOW_LIST)}"
    )


async def execute(
    ctx: RunContext[StateDeps[PotpieState]],
    command: str,
    working_dir: str | None = None,
) -> str:
    """Run a shell command and return its output (stdout + stderr).
    Only commands in the allow-list are permitted.
    Use this for git operations, file inspection, and running pydantic-deep CLI."""
    allowed, reason = _is_allowed(command)
    if not allowed:
        return reason

    # Rewrite bare "pydantic-deep" to the full venv path
    if command.strip().startswith("pydantic-deep"):
        command = command.replace("pydantic-deep", _PYDANTIC_DEEP, 1)

    cwd = working_dir or str(_REPO_ROOT)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ, "PATH": f"{_VENV_BIN}:{os.environ.get('PATH', '')}"},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        output = (stdout or b"").decode(errors="replace")
        err = (stderr or b"").decode(errors="replace")
        result = output + ("\n" + err if err else "")
        if proc.returncode != 0:
            result += f"\n[exit code: {proc.returncode}]"
        return result.strip() or "(no output)"
    except asyncio.TimeoutError:
        return "Command timed out after 120 seconds."
    except Exception as e:
        return f"Error: {e}"


async def read_file(
    ctx: RunContext[StateDeps[PotpieState]],
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read a file's contents. Optionally specify start_line and end_line for a range."""
    try:
        p = Path(file_path).expanduser()
        if not p.is_absolute():
            p = _REPO_ROOT / p
        text = p.read_text(errors="replace")
        lines = text.splitlines(keepends=True)
        if start_line or end_line:
            s = (start_line or 1) - 1
            e = end_line or len(lines)
            lines = lines[s:e]
        # Truncate large files
        content = "".join(lines)
        if len(content) > 50_000:
            content = content[:50_000] + "\n...[truncated]"
        return content or "(empty file)"
    except FileNotFoundError:
        return f"File not found: {file_path}"
    except Exception as e:
        return f"Error reading file: {e}"


async def list_files(
    ctx: RunContext[StateDeps[PotpieState]],
    directory: str = ".",
    pattern: str = "*",
) -> str:
    """List files in a directory. Supports glob patterns."""
    try:
        p = Path(directory).expanduser()
        if not p.is_absolute():
            p = _REPO_ROOT / p
        matches = sorted(p.glob(pattern))[:200]
        return "\n".join(str(m.relative_to(p)) for m in matches) or "(no matches)"
    except Exception as e:
        return f"Error: {e}"


tools = [
    list_projects,
    parse_repo,
    get_parsing_status,
    search_codebase,
    query_code_graph,
    ask_knowledge_graph,
    set_active_project,
    execute,
    read_file,
    list_files,
]

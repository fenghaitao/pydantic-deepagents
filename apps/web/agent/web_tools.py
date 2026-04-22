"""Web-specific tools that extend CLI capabilities.

These tools are NOT in the CLI — they handle web-specific concerns:
- parse_repo: async background parsing with job_id tracking
- get_parsing_status: poll parse job completion
- set_active_project: update frontend state for CopilotKit sync

Standalone helpers (start_parse_job / query_parse_job) are also exposed for
direct use by HTTP routes so they don't require an agent RunContext.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

logger = logging.getLogger(__name__)

# Module-level singleton — shared across requests.
runtime = PotpieRuntime(
    user_id=os.getenv("POTPIE_USER_ID", "defaultuser"),
)

# In-memory parse job tracker: job_id → {"status": ..., "result": ...}
_parse_jobs: dict[str, dict[str, Any]] = {}


def _validate_repo_path(repo_path: str) -> Path:
    """Return an absolute resolved Path, or raise ValueError."""
    p = Path(repo_path).resolve()
    if not p.exists():
        raise ValueError(f"Path does not exist: {p}")
    if not p.is_dir():
        raise ValueError(f"Path is not a directory: {p}")
    if not (p / ".git").exists():
        raise ValueError(f"Not a git repository: {p}")
    return p


# ── Standalone helpers (no RunContext needed) ─────────────────────────────

def start_parse_job(repo_path: str, branch: str = "main") -> str:
    """Validate repo, enqueue a background parse task and return a job_id."""
    validated = _validate_repo_path(repo_path)

    job_id = str(uuid.uuid4())[:8]
    _parse_jobs[job_id] = {"status": "started", "result": None}

    async def _do_parse() -> None:
        try:
            result = await runtime.parse(
                repo_path=str(validated),
                repo_name=validated.name,
                branch=branch,
            )
            _parse_jobs[job_id] = {"status": "done", "result": result}
        except Exception as e:
            logger.exception("parse_repo failed for job %s", job_id)
            _parse_jobs[job_id] = {"status": "error", "result": str(e)}

    asyncio.create_task(_do_parse())
    return job_id


def query_parse_job(job_id: str) -> dict[str, Any]:
    """Return the current state of a parse job, or an error dict."""
    job = _parse_jobs.get(job_id)
    if job is None:
        return {"error": f"Unknown job_id: {job_id}"}
    return dict(job)


# ── Agent tool wrappers ────────────────────────────────────────────────────

async def parse_repo(
    ctx: RunContext[DeepAgentDeps],
    repo_path: str,
    branch: str = "main",
) -> str:
    """Parse a repository and build its code knowledge graph.
    Returns a job_id — use get_parsing_status to check completion."""
    try:
        job_id = start_parse_job(repo_path, branch)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    # Wire up state update on completion in the background
    state = getattr(ctx.deps, "state", None)

    async def _watch_and_update() -> None:
        while True:
            await asyncio.sleep(1)
            job = query_parse_job(job_id)
            if job.get("status") in ("done", "error"):
                if state and job.get("status") == "done":
                    result = job.get("result") or {}
                    if isinstance(result, dict) and result.get("project_id"):
                        state.project_id = result["project_id"]
                break

    asyncio.create_task(_watch_and_update())
    return json.dumps({"job_id": job_id, "status": "started", "repo": repo_path})


async def get_parsing_status(
    ctx: RunContext[DeepAgentDeps],
    job_id: str,
) -> str:
    """Check the status of a parse_repo job."""
    return json.dumps(query_parse_job(job_id), default=str)


async def set_active_project(
    ctx: RunContext[DeepAgentDeps],
    project_id: str,
) -> str:
    """Set the active project for code graph queries and frontend display."""
    # Update frontend state (synced with CopilotKit via AG-UI)
    state = getattr(ctx.deps, "state", None)
    if state:
        state.project_id = project_id

    # Also update kg_context so CLI tools use this project immediately
    from pydantic_deep.toolsets.code_graph.potpie.context import PotpieContext

    ctx.deps.kg_context = PotpieContext(
        project_id=project_id,
        user_id=os.getenv("POTPIE_USER_ID", "defaultuser"),
    )
    return f"Active project set to {project_id}"


def create_web_toolset() -> FunctionToolset[DeepAgentDeps]:
    """Create a FunctionToolset with web-specific tools."""
    toolset: FunctionToolset[DeepAgentDeps] = FunctionToolset(id="web-tools")
    toolset.tool(parse_repo)
    toolset.tool(get_parsing_status)
    toolset.tool(set_active_project)
    return toolset

"""
pydantic-deep Web Agent Server

Uses create_deep_agent() (same factory as CLI) to get ALL CLI tools and
capabilities. Wraps it with per-request WebDeepDeps for session isolation
and CopilotKit state sync via AG-UI protocol.

Architecture:
  Browser → CopilotKit → Next.js → AG-UI → this server
  This server: create_deep_agent() + handle_ag_ui_request(per-request deps)

Model selection (same precedence as CLI):
  1. PYDANTIC_DEEP_MODEL env var
  2. .pydantic-deep/config.toml [model] field
  3. Auto-detect from available API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, …)
  4. Fallback: litellm:github_copilot/gpt-4o  (GitHub Copilot via LiteLLM OAuth)
"""

import logging
import os
from pathlib import Path

from contextlib import asynccontextmanager

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load root project .env before any imports that read DB credentials.
_REPO_ROOT = Path(__file__).resolve().parents[3]  # pydantic-deep/

# Load potpie backend .env first (has POSTGRES_SERVER, NEO4J_*, REDIS*, etc.)
_POTPIE_ENV = _REPO_ROOT / "code-graph-providers" / "potpie" / ".env"
if _POTPIE_ENV.exists():
    load_dotenv(_POTPIE_ENV, override=False)

# Then repo-root .env (may override specific vars for local dev)
_ROOT_ENV = _REPO_ROOT / ".env"
if _ROOT_ENV.exists():
    load_dotenv(_ROOT_ENV, override=False)

# Finally, CWD .env / .env.local
load_dotenv(override=False)

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from pydantic_ai.ag_ui import handle_ag_ui_request  # noqa: E402
from pydantic_ai_backends import LocalBackend  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse, Response  # noqa: E402

from pydantic_deep.agent import create_deep_agent  # noqa: E402
from apps.cli.config import load_config  # noqa: E402
from apps.cli.providers import select_default_model  # noqa: E402

from models import PotpieState  # noqa: E402
from web_deps import WebDeepDeps  # noqa: E402
from web_kg import WebPotpieCapability  # noqa: E402
from web_tools import create_web_toolset, runtime, start_parse_job, query_parse_job  # noqa: E402

# ── Model resolution (same logic as CLI) ─────────────────────────────────

# Load config from repo root's .pydantic-deep/config.toml (if present)
_config = load_config(_REPO_ROOT / ".pydantic-deep" / "config.toml")

# Precedence: PYDANTIC_DEEP_MODEL env > config.toml > auto-detect from API keys
_model_str: str = os.getenv("PYDANTIC_DEEP_MODEL") or _config.model or select_default_model()

# Handle litellm: prefix exactly like CLI does
if isinstance(_model_str, str) and _model_str.startswith("litellm:"):
    from pydantic_deep.litellm import infer_litellm_model  # noqa: E402
    _model = infer_litellm_model(_model_str)
else:
    _model = _model_str  # pydantic-ai resolves provider:model strings natively

# ── Build the agent once at startup (toolsets are stateless) ──────────────

_kg_cap = WebPotpieCapability(runtime=runtime)

_web_toolset = create_web_toolset()

agent = create_deep_agent(
    model=_model,
    instructions=(
        "You are pydantic-deep AI, a coding assistant with full access to filesystem, "
        "shell commands, code graph, memory, and skills.\n\n"
        "Key tools:\n"
        "- File operations: read_file, write_file, edit_file, grep, glob\n"
        "- Shell: execute (git, pydantic-deep CLI, python, etc.)\n"
        "- Code graph: search_codebase, nl_query, ask_knowledge_graph, list_code_projects\n"
        "- Web-specific: parse_repo, get_parsing_status, set_active_project\n"
        "- Memory: read_memory, write_memory\n\n"
        "For code questions, use search_codebase + nl_query. "
        "For semantic/behavior questions, use ask_knowledge_graph."
    ),
    backend=LocalBackend(root_dir=_REPO_ROOT),
    toolsets=[_web_toolset],
    capabilities=[_kg_cap],
    include_filesystem=True,
    include_execute=True,
    include_todo=False,
    include_skills=True,
    include_memory=True,
    include_subagents=False,
    include_teams=False,
    include_checkpoints=False,
    interrupt_on={"execute": False, "write_file": False, "edit_file": False},
    web_search=False,
    web_fetch=False,
    thinking=False,
    cost_tracking=False,
    context_manager=False,
)


class ParseBody(BaseModel):
    repo_path: str
    branch: str = "main"


# ── Per-request handler (session isolation) ───────────────────────────────

async def _ag_ui_handler(request: Request) -> Response:
    """Handle each AG-UI request with fresh per-request deps."""
    deps = WebDeepDeps(
        backend=LocalBackend(root_dir=_REPO_ROOT),
        state=PotpieState(),
    )
    return await handle_ag_ui_request(agent, request, deps=deps)


async def _health() -> Response:
    return JSONResponse({"status": "ok", "model": str(_model_str)})


async def _projects_list() -> Response:
    """GET /projects — list all parsed projects for this user."""
    try:
        projects = await runtime.list_projects()
    except Exception as exc:
        logger.exception("list_projects failed")
        return JSONResponse({"error": str(exc)}, status_code=500)
    return JSONResponse(projects)


async def _parse_start(body: ParseBody) -> Response:
    """POST /parse — start a background parse job.

    Body: {"repo_path": str, "branch": str (optional, default "main")}
    Returns: {"job_id": str, "status": "started"}
    """
    try:
        job_id = start_parse_job(body.repo_path, body.branch)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    return JSONResponse({"job_id": job_id, "status": "started"})


async def _parse_status(job_id: str) -> Response:
    """GET /parse/status/{job_id} — poll a parse job.

    Returns: {"status": "started"|"done"|"error", "result": ...}
    """
    data = query_parse_job(job_id)
    if "error" in data:
        return JSONResponse(data, status_code=404)
    return JSONResponse(data)


# ── FastAPI ASGI app ─────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Eagerly warm up the potpie runtime so /projects is ready immediately.
    try:
        await runtime._get_runtime()
        logger.info("PotpieRuntime: ready")
    except Exception:
        logger.warning("PotpieRuntime: warm-up failed (will retry on first request)", exc_info=True)
    yield
    await runtime.close()


# Disable auto-generated docs endpoints — this is an internal agent API.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=_lifespan)

app.add_api_route("/", _ag_ui_handler, methods=["POST"], response_class=Response)
app.add_api_route("/health", _health, methods=["GET"])
app.add_api_route("/projects", _projects_list, methods=["GET"])
app.add_api_route("/parse", _parse_start, methods=["POST"])
app.add_api_route("/parse/status/{job_id}", _parse_status, methods=["GET"])

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("AGENT_PORT", "8000"))
    reload = os.getenv("DEBUG", "false").lower() == "true"
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload)


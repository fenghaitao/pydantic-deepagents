"""Potpie KG toolset for pydantic-deep agents.

Wraps potpie's knowledge graph tools as a pydantic-ai FunctionToolset
so they can be injected into create_deep_agent().
"""

from __future__ import annotations

import copy
import functools
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext, Tool
from pydantic_ai.toolsets import FunctionToolset

from app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils import (
    wrap_structured_tools,
)
from app.modules.intelligence.tools.tool_service import ToolService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from potpie.runtime import PotpieRuntime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KG_TOOL_NAMES: list[str] = [
    "ask_knowledge_graph_queries",
    "get_code_from_multiple_node_ids",
    "get_code_from_probable_node_name",
    "get_code_file_structure",
    "fetch_file",
    "fetch_files_batch",
    "get_node_neighbours_from_node_id",
    "analyze_code_structure",
]


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def _inject_project_id(tool: Tool) -> Tool:
    """Wrap a tool function to inject project_id from ctx.deps when the schema has it.

    If the tool's JSON schema has a 'project_id' property, we wrap the function
    to accept RunContext as the first argument and fill project_id from
    ctx.deps.potpie_project_id, removing it from the schema so the LLM never
    needs to supply it.
    """
    schema = getattr(tool, "parameters_json_schema", None)
    if schema is None:
        # pydantic-ai stores schema on function_schema.json_schema for plain Tool objects
        fs = getattr(tool, "function_schema", None)
        schema = getattr(fs, "json_schema", None) or {}

    props = schema.get("properties", {})
    if "project_id" not in props:
        return tool

    original_func = tool.function

    # NOTE: functools.wraps would copy the original signature, hiding ctx.
    # pydantic-ai detects RunContext by inspecting the first parameter annotation,
    # so we must NOT use @functools.wraps here.
    def ctx_wrapper(ctx: RunContext[Any], **kwargs: Any) -> Any:
        project_id = getattr(ctx.deps, "potpie_project_id", None)
        if project_id:
            kwargs["project_id"] = project_id
        return original_func(**kwargs)

    ctx_wrapper.__name__ = getattr(original_func, "__name__", tool.name)
    ctx_wrapper.__doc__ = tool.description

    # Build a new schema without project_id so the LLM doesn't try to fill it
    new_schema = copy.deepcopy(schema)
    new_schema.get("properties", {}).pop("project_id", None)
    required = new_schema.get("required", [])
    if "project_id" in required:
        required.remove("project_id")

    return Tool.from_schema(
        function=ctx_wrapper,
        name=tool.name,
        description=tool.description,
        json_schema=new_schema,
        takes_ctx=True,
    )


def create_potpie_toolset(
    runtime: PotpieRuntime,
    project_id: str,
    user_id: str,
    toolset_id: str = "potpie-kg",
) -> FunctionToolset:
    """Create a FunctionToolset containing potpie's KG tools.

    Opens a sync DB session from *runtime*, instantiates ToolService with
    *user_id* for per-user access control, retrieves the 8 KG tools, wraps
    them as pydantic-ai Tool objects (with handle_exception), and returns a
    FunctionToolset ready to be passed to create_deep_agent().

    The caller is responsible for closing the session when the agent run
    finishes — use the returned ``_close_session`` attribute or call
    ``_close_session(toolset)`` directly.

    Args:
        runtime: Initialised PotpieRuntime instance.
        project_id: Registered project ID (baked into tool closures).
        user_id: User ID forwarded to ToolService for access control.
        toolset_id: Identifier for the FunctionToolset (default "potpie-kg").

    Returns:
        FunctionToolset with all KG tools wrapped and ready for use.
    """
    db_session: Session = runtime.db.get_session()

    tool_service = ToolService(db=db_session, user_id=user_id)
    langchain_tools = tool_service.get_tools(KG_TOOL_NAMES)
    pydantic_tools = [_inject_project_id(t) for t in wrap_structured_tools(langchain_tools)]

    toolset: FunctionToolset = FunctionToolset(tools=pydantic_tools, id=toolset_id)

    # Attach the session so callers can close it after the agent run.
    toolset._db_session = db_session  # type: ignore[attr-defined]

    return toolset


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------


def _close_session(toolset: FunctionToolset) -> None:
    """Close the DB session that was opened by create_potpie_toolset.

    Call this after the agent run completes to release the database
    connection back to the pool.

    Args:
        toolset: The FunctionToolset returned by create_potpie_toolset.
    """
    session: Session | None = getattr(toolset, "_db_session", None)
    if session is not None:
        session.close()
        toolset._db_session = None  # type: ignore[attr-defined]

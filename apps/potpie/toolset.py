"""Potpie KG toolset for pydantic-deep agents.

Wraps potpie's knowledge graph tools as a pydantic-ai FunctionToolset
so they can be injected into create_deep_agent().

Uses PotpieBackend.get_tools() so it works with any backend implementation
that supports direct tool registry access (RuntimeBackend). RestBackend
raises NotImplementedError for get_tools() — use CodeGraphToolset instead.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext, Tool
from pydantic_ai.toolsets import FunctionToolset

from app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils import (
    wrap_structured_tools,
)
from pydantic_deep.toolsets.code_graph.backend import PotpieBackend

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KG_TOOL_NAMES: list[str] = [
    "ask_knowledge_graph_queries",
    "nl_cypher_query",
    "get_code_from_multiple_node_ids",
    "get_code_from_probable_node_name",
    "get_code_file_structure",
    "fetch_file",
    "fetch_files_batch",
    "get_node_neighbours_from_node_id",
    "analyze_code_structure",
]

# Tools that require embeddings — unavailable when project is in INFERRING state
_EMBEDDING_DEPENDENT_TOOLS: frozenset[str] = frozenset({
    "ask_knowledge_graph_queries",
})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _inject_project_id(tool: Tool) -> Tool:
    """Wrap a tool to inject project_id from ctx.deps when the schema has it.

    If the tool's JSON schema has a 'project_id' property, wraps the function
    to accept RunContext as the first argument and fills project_id from
    ctx.deps.potpie_project_id, removing it from the schema so the LLM never
    needs to supply it.
    """
    schema = getattr(tool, "parameters_json_schema", None)
    if schema is None:
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
        project_id = ctx.deps.potpie.project_id if ctx.deps.potpie is not None else None
        if project_id:
            kwargs["project_id"] = project_id

        # Guard: embedding-dependent tools fail silently during INFERRING state.
        # Return a clear message instead so the agent can try a different tool.
        if tool.name in _EMBEDDING_DEPENDENT_TOOLS:
            status = (
                ctx.deps.potpie.parsing_status
                if ctx.deps.potpie is not None else None
            )
            if status == "INFERRING":
                return (
                    f"Tool '{tool.name}' is unavailable while the project is being indexed "
                    f"(status: INFERRING). Embeddings are not ready yet. "
                    f"Use 'nl_cypher_query' or 'get_code_file_structure' instead."
                )

        return original_func(**kwargs)

    ctx_wrapper.__name__ = getattr(original_func, "__name__", tool.name)
    ctx_wrapper.__doc__ = tool.description

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


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


async def create_potpie_toolset(
    backend: PotpieBackend,
    tool_names: list[str] | None = None,
    toolset_id: str = "potpie-kg",
    exclude_embedding_tools: bool = False,
) -> FunctionToolset:
    """Create a FunctionToolset containing potpie KG tools via a PotpieBackend.

    Fetches StructuredTool instances from the backend's tool registry,
    wraps them as pydantic-ai Tool objects with project_id injection,
    and returns a FunctionToolset ready to be passed to create_deep_agent().

    Requires a backend that supports get_tools() — i.e. RuntimeBackend.
    RestBackend will raise NotImplementedError.

    Args:
        backend: An initialised PotpieBackend (RuntimeBackend recommended).
        tool_names: Tool names to retrieve. Defaults to KG_TOOL_NAMES.
        toolset_id: Identifier for the FunctionToolset (default "potpie-kg").
        exclude_embedding_tools: Skip embedding-dependent tools (use when
            project is in INFERRING state).

    Returns:
        FunctionToolset with all requested tools wrapped and ready for use.
    """
    names = tool_names if tool_names is not None else KG_TOOL_NAMES
    langchain_tools = await backend.get_tools(
        names, exclude_embedding_tools=exclude_embedding_tools
    )
    pydantic_tools = [_inject_project_id(t) for t in wrap_structured_tools(langchain_tools)]
    return FunctionToolset(tools=pydantic_tools, id=toolset_id)

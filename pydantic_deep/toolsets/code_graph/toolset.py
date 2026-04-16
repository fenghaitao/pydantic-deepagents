"""CodeGraphToolset — pydantic-ai FunctionToolset that exposes potpie code-graph tools.

The toolset is backend-agnostic: it accepts a CodeGraphRuntime instance
and exposes four agent-callable tools:

  list_code_projects   — enumerate indexed repositories
  search_codebase      — fast keyword search (SQL index)
  nl_query             — structural NL→Cypher query (call graphs, imports, etc.)
  ask_knowledge_graph  — semantic / docstring similarity search

For subagent use, ``CodeGraphToolset.from_runtime()`` fetches the full set of
low-level KG tools from a CodeGraphRuntime and wraps them with project_id injection.

``get_instructions()`` injects the list of available project IDs into the
system prompt so the agent can reference them without a round-trip.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from pydantic_ai import RunContext, Tool
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.toolsets.code_graph.runtime import CodeGraphRuntime

# ── Tool descriptions ─────────────────────────────────────────────────────────

_LIST_PROJECTS_DESC = """\
List all code repositories that have been indexed in the potpie code graph.

Returns a list of projects with their IDs, names, branch names, and status.
Use this to discover which project_id values are available before running
other code-graph tools."""

_SEARCH_DESC = """\
Fast keyword search over the indexed code base (SQL-backed).

Use this when you know the name of a function, class, or file and want to find
it quickly. Returns matching nodes with file paths and brief metadata.

:param query: Search term — function name, class name, file path fragment, etc."""

_NL_QUERY_DESC = """\
Query the code knowledge graph using a natural language structural question.

Translates the question to a Cypher query and runs it against the Neo4j graph.
Use this for STRUCTURAL / RELATIONAL questions:
  - "What functions does UserService call?"
  - "Which files import auth.py?"
  - "List all classes in the payments module."
  - "What are the call-graph neighbours of parse_directory?"

Returns: {"cypher_used": str, "results": list[dict], "count": int}

:param question: Natural language question about code structure."""

_KG_SEARCH_DESC = """\
Semantic search over code docstrings and summaries using embedding similarity.

Use this for MEANING / BEHAVIOUR questions:
  - "What does authentication look like in this codebase?"
  - "Find code that handles retry logic."
  - "Which functions validate user input?"

Returns a ranked list of nodes with docstrings, file paths, and similarity scores.

:param questions: One or more natural-language questions (list of strings).
:param node_ids: Optional list of node IDs to narrow the search scope."""

# ── Low-level KG tool names (CodeGraphRuntime only) ────────────────────────────

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

_EMBEDDING_DEPENDENT_TOOLS: frozenset[str] = frozenset({"ask_knowledge_graph_queries"})


def _inject_project_id(tool: Tool) -> Tool:
    """Wrap a tool to inject project_id from ctx.deps.kg_context, removing it from the schema.

    If the tool's JSON schema has a 'project_id' property, wraps the function
    to accept RunContext as the first argument and fills project_id from
    ctx.deps.kg_context.project_id, so the LLM never needs to supply it.
    """
    schema = getattr(tool, "parameters_json_schema", None)
    if schema is None:
        fs = getattr(tool, "function_schema", None)
        schema = getattr(fs, "json_schema", None) or {}

    if "project_id" not in schema.get("properties", {}):
        return tool

    original_func = tool.function
    import asyncio as _asyncio
    _is_async = _asyncio.iscoroutinefunction(original_func)

    if _is_async:
        async def ctx_wrapper(ctx: RunContext[Any], **kwargs: Any) -> Any:
            kg_context = ctx.deps.kg_context if ctx.deps.kg_context is not None else None
            project_id = getattr(kg_context, "project_id", None) if kg_context else None
            if project_id:
                kwargs["project_id"] = project_id
            if tool.name in _EMBEDDING_DEPENDENT_TOOLS:
                status = getattr(kg_context, "parsing_status", None) if kg_context else None
                if status == "INFERRING":
                    return (
                        f"Tool '{tool.name}' is unavailable while the project is being indexed "
                        "(status: INFERRING). Use 'nl_cypher_query' or 'get_code_file_structure'."
                    )
            return await original_func(**kwargs)
    else:
        def ctx_wrapper(ctx: RunContext[Any], **kwargs: Any) -> Any:  # type: ignore[misc]
            kg_context = ctx.deps.kg_context if ctx.deps.kg_context is not None else None
            project_id = getattr(kg_context, "project_id", None) if kg_context else None
            if project_id:
                kwargs["project_id"] = project_id
            if tool.name in _EMBEDDING_DEPENDENT_TOOLS:
                status = getattr(kg_context, "parsing_status", None) if kg_context else None
                if status == "INFERRING":
                    return (
                        f"Tool '{tool.name}' is unavailable while the project is being indexed "
                        "(status: INFERRING). Use 'nl_cypher_query' or 'get_code_file_structure'."
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


class CodeGraphToolset(FunctionToolset[Any]):
    """Agent toolset for potpie code-graph operations.

    Constructed with a runtime (CodeGraphRuntime) and an optional
    default project_id that is injected into the system prompt.

    Tools:
        - ``list_code_projects``: enumerate indexed repos
        - ``search_codebase``: fast keyword search
        - ``nl_query``: structural NL→Cypher query
        - ``ask_knowledge_graph``: semantic/docstring similarity search
    """

    def __init__(
        self,
        *,
        runtime: CodeGraphRuntime,
        project_id: str | None = None,
    ) -> None:
        super().__init__(id="potpie-code-graph")
        self._runtime = runtime
        self._project_id = project_id

        @self.tool(description=_LIST_PROJECTS_DESC)
        async def list_code_projects(ctx: RunContext[Any]) -> str:
            projects = await self._runtime.list_projects()
            if not projects:
                return (
                    "No projects indexed yet. Use 'pydantic-deep parse repo' to index a repository."
                )
            return json.dumps(projects, default=str)

        @self.tool(description=_SEARCH_DESC)
        async def search_codebase(
            ctx: RunContext[Any],
            query: str,
        ) -> str:
            """Fast keyword search.

            Args:
                query: Search term.
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            results = await self._runtime.search(project_id, query)
            if not results:
                return f"No results for '{query}' in project {project_id}."
            return json.dumps(results, default=str)

        @self.tool(description=_NL_QUERY_DESC)
        async def nl_query(
            ctx: RunContext[Any],
            question: str,
        ) -> str:
            """Structural NL→Cypher query.

            Args:
                question: Natural language structural question.
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            result = await self._runtime.nl_query(project_id, question)
            return json.dumps(result, default=str)

        @self.tool(description=_KG_SEARCH_DESC)
        async def ask_knowledge_graph(
            ctx: RunContext[Any],
            questions: list[str],
            node_ids: list[str] | None = None,
        ) -> str:
            """Semantic knowledge-graph search.

            Args:
                questions: List of natural language questions.
                node_ids: Optional list of node IDs to restrict the search.
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            # Guard: embeddings are not available during INFERRING state
            if kg_context is not None and getattr(kg_context, "parsing_status", None) == "INFERRING":
                return (
                    "Semantic search is unavailable while the project is being indexed "
                    "(status: INFERRING). Embeddings are not ready yet. "
                    "Use `nl_query` for structural questions instead."
                )
            results = await self._runtime.kg_search(project_id, questions, node_ids or [])
            if not results:
                return "No results found for the given questions."
            return json.dumps(results, default=str)

    async def get_instructions(self, ctx: RunContext[Any]) -> list[str] | None:
        """Inject project context into the system prompt."""
        parts: list[str] = []

        # Check parsing status from PotpieContext if available
        kg_context = getattr(ctx.deps, "kg_context", None)
        parsing_status = getattr(kg_context, "parsing_status", None) if kg_context else None
        is_inferring = parsing_status == "INFERRING"
        is_parsing = parsing_status in ("PARSING", "SUBMITTED")

        if self._project_id:
            status_note = ""
            if is_inferring:
                status_note = (
                    "\n\n> **Note:** Project is in INFERRING state — embeddings are being built. "
                    "`ask_knowledge_graph` is unavailable. Use `nl_query` instead."
                )
            elif is_parsing:
                status_note = (
                    "\n\n> **Note:** Project is still being parsed (status: "
                    f"{parsing_status}). Graph queries may return incomplete results."
                )

            parts.append(
                f"## Code Graph\n\n"
                f"Default project ID: `{self._project_id}`\n\n"
                "You have access to code-graph tools (`nl_query`, "
                "`ask_knowledge_graph`, `search_codebase`, `list_code_projects`) "
                "to answer questions about the indexed codebase.\n"
                "Use `nl_query` for structural/relational questions "
                "(call graphs, imports, inheritance). "
                "Use `ask_knowledge_graph` for semantic/behaviour questions." + status_note
            )
        else:
            parts.append(
                "## Code Graph\n\n"
                "You have access to code-graph tools. Use `list_code_projects` "
                "to discover available project IDs, then pass the relevant ID "
                "to `nl_query`, `ask_knowledge_graph`, or `search_codebase`."
            )

        return parts if parts else None

    @classmethod
    async def from_runtime(
        cls,
        runtime: CodeGraphRuntime,
        tool_names: list[str] | None = None,
        toolset_id: str = "potpie-kg",
        exclude_embedding_tools: bool = False,
    ) -> FunctionToolset[Any]:
        """Create a FunctionToolset of low-level KG tools from a CodeGraphRuntime.

        Fetches StructuredTool instances via backend.get_tools(), wraps them
        with project_id injection, and returns a FunctionToolset for subagent use.

        Requires CodeGraphRuntime — only CodeGraphRuntime supports get_tools().

        Args:
            runtime: An initialised CodeGraphRuntime.
            tool_names: Tool names to retrieve. Defaults to KG_TOOL_NAMES.
            toolset_id: FunctionToolset identifier.
            exclude_embedding_tools: Skip embedding-dependent tools.

        Returns:
            FunctionToolset with all requested tools wrapped and ready for use.
        """
        # Lazy import — keeps pydantic_deep importable without app.* at module load time.
        from app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils import (
            wrap_structured_tools,
        )

        names = tool_names if tool_names is not None else KG_TOOL_NAMES
        langchain_tools = await runtime.get_tools(
            names, exclude_embedding_tools=exclude_embedding_tools
        )
        pydantic_tools = [_inject_project_id(t) for t in wrap_structured_tools(langchain_tools)]
        return FunctionToolset(tools=pydantic_tools, id=toolset_id)




__all__ = ["CodeGraphToolset"]

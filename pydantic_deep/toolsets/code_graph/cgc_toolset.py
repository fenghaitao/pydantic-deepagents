"""CGCToolset — pydantic-ai FunctionToolset exposing CodeGraphContext tools.

Exposes four agent-callable tools over a CGCRuntime:

  list_code_projects         — list indexed repositories
  find_code                  — keyword / fuzzy search
  analyze_code_relationships — structural queries (callers, callees, hierarchy)
  execute_cypher_query       — raw Cypher graph query (fallback)

``get_instructions()`` injects repository context into the system prompt so
the agent knows which codebase it is operating on.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.toolsets.code_graph.cgc_runtime import CGCRuntime

# ── Tool descriptions ──────────────────────────────────────────────────────────

_LIST_REPOS_DESC = """\
List all code repositories that have been indexed in the CodeGraphContext graph.

Returns a list of repositories with their paths, file counts, and status.
Use this to discover which repositories are available before running other
code-graph tools."""

_FIND_CODE_DESC = """\
Search the indexed codebase for a keyword, function name, class name, or phrase.

Use this to locate where something is defined or used across the codebase.
Returns matching code snippets with file paths and line numbers.

:param query: Keyword or symbol name to search for.
:param fuzzy_search: Enable fuzzy matching for approximate searches."""

_ANALYZE_RELATIONSHIPS_DESC = """\
Analyze structural code relationships — callers, callees, class hierarchies, and more.

Supported query types:
  - find_callers       — functions that call ``target``
  - find_callees       — functions called by ``target``
  - find_all_callers   — transitive callers (all indirect callers)
  - find_all_callees   — transitive callees (all indirect callees)
  - find_importers     — files/modules that import ``target``
  - who_modifies       — functions that modify a variable/attribute
  - class_hierarchy    — inheritance chain for a class
  - overrides          — methods that override ``target``
  - dead_code          — potentially unused functions
  - call_chain         — execution path between two functions
  - module_deps        — module-level dependency graph
  - variable_scope     — scope analysis for a variable
  - find_complexity    — cyclomatic complexity
  - find_functions_by_argument   — functions accepting a given argument type
  - find_functions_by_decorator  — functions with a given decorator

:param query_type: One of the query type strings listed above.
:param target: Function, class, module, or variable to analyze.
:param context: Optional file path to disambiguate when the target name is
    not unique across the codebase."""

_CYPHER_DESC = """\
Execute a read-only Cypher query directly against the code knowledge graph.

Use this as a fallback for complex structural questions not covered by
``analyze_code_relationships``.

Graph schema:
  Nodes: Repository, File, Module, Class, Function
  Relationships: CONTAINS, CALLS, IMPORTS, INHERITS

:param cypher_query: Read-only Cypher query string."""


class CGCToolset(FunctionToolset[Any]):
    """Agent toolset for CodeGraphContext code-graph operations.

    Constructed with a ``CGCRuntime`` and an optional ``repo_path`` that
    is injected into tool calls and the system prompt.

    Tools:
        - ``list_code_projects``: enumerate indexed repos
        - ``find_code``: keyword / fuzzy search
        - ``analyze_code_relationships``: structural queries
        - ``execute_cypher_query``: raw Cypher fallback
    """

    def __init__(
        self,
        *,
        runtime: CGCRuntime,
        repo_path: str | None = None,
    ) -> None:
        super().__init__(id="cgc-code-graph")
        self._runtime = runtime
        self._repo_path = repo_path

        @self.tool(description=_LIST_REPOS_DESC)
        async def list_code_projects(ctx: RunContext[Any]) -> str:
            result = await self._runtime.list_repositories()
            return json.dumps(result, default=str)

        @self.tool(description=_FIND_CODE_DESC)
        async def find_code(
            ctx: RunContext[Any],
            query: str,
            fuzzy_search: bool = False,
        ) -> str:
            """Keyword and fuzzy search over the indexed codebase.

            Args:
                query: Search term.
                fuzzy_search: Whether to enable fuzzy matching.
            """
            result = await self._runtime.find_code(
                query=query,
                repo_path=self._repo_path,
                fuzzy_search=fuzzy_search,
            )
            return json.dumps(result, default=str)

        @self.tool(description=_ANALYZE_RELATIONSHIPS_DESC)
        async def analyze_code_relationships(
            ctx: RunContext[Any],
            query_type: str,
            target: str,
            context: str | None = None,
        ) -> str:
            """Structural relationship query.

            Args:
                query_type: Relationship type (e.g. ``find_callers``).
                target: Symbol to analyze.
                context: Optional file path for disambiguation.
            """
            result = await self._runtime.analyze_relationships(
                query_type=query_type,
                target=target,
                context=context,
                repo_path=self._repo_path,
            )
            return json.dumps(result, default=str)

        @self.tool(description=_CYPHER_DESC)
        async def execute_cypher_query(
            ctx: RunContext[Any],
            cypher_query: str,
        ) -> str:
            """Raw Cypher graph query.

            Args:
                cypher_query: Read-only Cypher query string.
            """
            result = await self._runtime.execute_cypher(cypher_query)
            return json.dumps(result, default=str)

    async def get_instructions(self, ctx: RunContext[Any]) -> list[str] | None:
        """Inject repository context into the system prompt."""
        cgc_context = getattr(ctx.deps, "cgc_context", None)
        repo_path = (
            getattr(cgc_context, "repo_path", None) if cgc_context else None
        ) or self._repo_path

        if repo_path:
            return [
                f"## Code Graph (CGC)\n\n"
                f"Default repository: `{repo_path}`\n\n"
                "You have access to code-graph tools (`find_code`, "
                "`analyze_code_relationships`, `execute_cypher_query`, "
                "`list_code_projects`) to explore and understand the indexed codebase.\n"
                "Use `find_code` for keyword searches. "
                "Use `analyze_code_relationships` for structural queries "
                "(call graphs, imports, class hierarchy). "
                "Use `execute_cypher_query` for advanced graph queries."
            ]
        return [
            "## Code Graph (CGC)\n\n"
            "You have access to code-graph tools. Use `list_code_projects` "
            "to discover indexed repositories, then use `find_code` and "
            "`analyze_code_relationships` to explore the codebase."
        ]


__all__ = ["CGCToolset"]

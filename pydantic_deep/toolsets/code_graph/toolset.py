"""CodeGraphToolset — pydantic-ai FunctionToolset that exposes potpie code-graph tools.

The toolset is backend-agnostic: it accepts any PotpieBackend implementation
(RestBackend or RuntimeBackend) and exposes four agent-callable tools:

  list_code_projects   — enumerate indexed repositories
  search_codebase      — fast keyword search (SQL index)
  query_code_graph     — structural NL→Cypher query (call graphs, imports, etc.)
  ask_knowledge_graph  — semantic / docstring similarity search

``get_instructions()`` injects the list of available project IDs into the
system prompt so the agent can reference them without a round-trip.

Pattern follows pydantic_deep/toolsets/memory.py exactly.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.toolsets.code_graph.backend import PotpieBackend

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

:param project_id: The project UUID to search in.
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

:param project_id: The project UUID to query.
:param question: Natural language question about code structure."""

_KG_SEARCH_DESC = """\
Semantic search over code docstrings and summaries using embedding similarity.

Use this for MEANING / BEHAVIOUR questions:
  - "What does authentication look like in this codebase?"
  - "Find code that handles retry logic."
  - "Which functions validate user input?"

Returns a ranked list of nodes with docstrings, file paths, and similarity scores.

:param project_id: The project UUID to search.
:param questions: One or more natural-language questions (list of strings).
:param node_ids: Optional list of node IDs to narrow the search scope."""


class CodeGraphToolset(FunctionToolset[Any]):
    """Agent toolset for potpie code-graph operations.

    Constructed with a backend (RestBackend or RuntimeBackend) and an optional
    default project_id that is injected into the system prompt.

    Tools:
        - ``list_code_projects``: enumerate indexed repos
        - ``search_codebase``: fast keyword search
        - ``query_code_graph``: structural NL→Cypher query
        - ``ask_knowledge_graph``: semantic/docstring similarity search
    """

    def __init__(
        self,
        *,
        backend: PotpieBackend,
        project_id: str | None = None,
    ) -> None:
        super().__init__(id="potpie-code-graph")
        self._backend = backend
        self._project_id = project_id

        @self.tool(description=_LIST_PROJECTS_DESC)
        async def list_code_projects(ctx: RunContext[Any]) -> str:
            projects = await self._backend.list_projects()
            if not projects:
                return "No projects indexed yet. Use 'pydantic-deep parse repo' to index a repository."
            return json.dumps(projects, default=str)

        @self.tool(description=_SEARCH_DESC)
        async def search_codebase(
            ctx: RunContext[Any],
            project_id: str,
            query: str,
        ) -> str:
            """Fast keyword search.

            Args:
                project_id: Project UUID.
                query: Search term.
            """
            results = await self._backend.search(project_id, query)
            if not results:
                return f"No results for '{query}' in project {project_id}."
            return json.dumps(results, default=str)

        @self.tool(description=_NL_QUERY_DESC)
        async def query_code_graph(
            ctx: RunContext[Any],
            project_id: str,
            question: str,
        ) -> str:
            """Structural NL→Cypher query.

            Args:
                project_id: Project UUID.
                question: Natural language structural question.
            """
            result = await self._backend.nl_query(project_id, question)
            return json.dumps(result, default=str)

        @self.tool(description=_KG_SEARCH_DESC)
        async def ask_knowledge_graph(
            ctx: RunContext[Any],
            project_id: str,
            questions: list[str],
            node_ids: list[str] | None = None,
        ) -> str:
            """Semantic knowledge-graph search.

            Args:
                project_id: Project UUID.
                questions: List of natural language questions.
                node_ids: Optional list of node IDs to restrict the search.
            """
            results = await self._backend.kg_search(
                project_id, questions, node_ids or []
            )
            if not results:
                return "No results found for the given questions."
            return json.dumps(results, default=str)

    async def get_instructions(self, ctx: RunContext[Any]) -> list[str] | None:
        """Inject project context into the system prompt."""
        parts: list[str] = []

        if self._project_id:
            parts.append(
                f"## Code Graph\n\n"
                f"Default project ID: `{self._project_id}`\n\n"
                "You have access to code-graph tools (`query_code_graph`, "
                "`ask_knowledge_graph`, `search_codebase`, `list_code_projects`) "
                "to answer questions about the indexed codebase.\n"
                "Use `query_code_graph` for structural/relational questions "
                "(call graphs, imports, inheritance). "
                "Use `ask_knowledge_graph` for semantic/behaviour questions."
            )
        else:
            parts.append(
                "## Code Graph\n\n"
                "You have access to code-graph tools. Use `list_code_projects` "
                "to discover available project IDs, then pass the relevant ID "
                "to `query_code_graph`, `ask_knowledge_graph`, or `search_codebase`."
            )

        return parts if parts else None


__all__ = ["CodeGraphToolset"]

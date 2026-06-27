"""GraphifyToolset — pydantic-ai FunctionToolset exposing Graphify tools.

Exposes agent-callable tools over a :class:`GraphifyRuntime`:

  query_code_graph     — natural-language query over the knowledge graph
  explain_code_node    — describe a node and its connections
  find_code_path       — shortest path between two nodes
  code_graph_god_nodes — most connected ("god") nodes
  code_graph_stats     — graph statistics

``get_instructions()`` injects graph context into the system prompt so the
agent knows which codebase it is operating on and prefers graph queries over
blind file reads.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.toolsets.code_graph.graphify.runtime import GraphifyRuntime

# ── Tool descriptions ──────────────────────────────────────────────────────────

_QUERY_DESC = """\
Ask a natural-language question about the codebase and get back a scoped,
relevant subgraph rendered as text.

This is the primary way to explore the codebase — prefer it over grepping or
reading files blindly. The graph already maps how code, docs, and concepts
connect, so a single query orients you quickly.

:param question: Natural-language question (e.g. "how does auth work?").
:param mode: Traversal strategy — "bfs" (default, broad) or "dfs" (deep).
:param depth: Traversal depth from the matched seed nodes (default 2).
:param token_budget: Approximate size of the rendered subgraph (default 2000)."""

_EXPLAIN_DESC = """\
Describe a single node (a concept, function, class, or file) and list its
strongest connections in the graph.

Use this to understand what one thing is and what it relates to.

:param label: Node label, concept, or symbol name to look up."""

_PATH_DESC = """\
Find the shortest relationship path between two nodes in the graph.

Use this to understand how two parts of the codebase are connected (e.g.
"how does the HTTP handler reach the database layer?").

:param source: Label or symbol name of the start node.
:param target: Label or symbol name of the end node."""

_GOD_NODES_DESC = """\
List the most connected ("god") nodes in the graph — the hubs that the rest
of the codebase depends on. A good starting point for understanding overall
architecture.

:param top_n: Number of top nodes to return (default 10)."""

_STATS_DESC = """\
Return summary statistics about the knowledge graph: node count, edge count,
and number of detected communities."""

_LIST_PROJECTS_DESC = """\
List the Graphify knowledge graph(s) available for this workspace.

Use this to confirm a graph has been built before running other tools."""


class GraphifyToolset(FunctionToolset[Any]):
    """Agent toolset for Graphify code-graph operations.

    Constructed with a :class:`GraphifyRuntime`. The runtime already knows the
    graph location, so tool functions take no path arguments.
    """

    def __init__(
        self,
        *,
        runtime: GraphifyRuntime,
        repo_path: str | None = None,
    ) -> None:
        super().__init__(id="graphify-code-graph")
        self._runtime = runtime
        self._repo_path = repo_path

        @self.tool(description=_LIST_PROJECTS_DESC)
        async def list_code_projects(ctx: RunContext[Any]) -> str:
            result = await self._runtime.list_projects()
            return json.dumps(result, default=str)

        @self.tool(description=_QUERY_DESC)
        async def query_code_graph(
            ctx: RunContext[Any],
            question: str,
            mode: str = "bfs",
            depth: int = 2,
            token_budget: int = 2000,
        ) -> str:
            """Natural-language query over the knowledge graph.

            Args:
                question: Question about the codebase.
                mode: ``"bfs"`` or ``"dfs"``.
                depth: Traversal depth.
                token_budget: Approximate rendered-subgraph budget.
            """
            return await self._runtime.query(
                question, mode=mode, depth=depth, token_budget=token_budget
            )

        @self.tool(description=_EXPLAIN_DESC)
        async def explain_code_node(ctx: RunContext[Any], label: str) -> str:
            """Describe a node and its connections.

            Args:
                label: Node label or symbol name.
            """
            result = await self._runtime.explain(label)
            return json.dumps(result, default=str)

        @self.tool(description=_PATH_DESC)
        async def find_code_path(
            ctx: RunContext[Any], source: str, target: str
        ) -> str:
            """Shortest path between two nodes.

            Args:
                source: Start node label.
                target: End node label.
            """
            return await self._runtime.path(source, target)

        @self.tool(description=_GOD_NODES_DESC)
        async def code_graph_god_nodes(
            ctx: RunContext[Any], top_n: int = 10
        ) -> str:
            """Most connected nodes.

            Args:
                top_n: Number of nodes to return.
            """
            result = await self._runtime.god_nodes(top_n=top_n)
            return json.dumps(result, default=str)

        @self.tool(description=_STATS_DESC)
        async def code_graph_stats(ctx: RunContext[Any]) -> str:
            result = await self._runtime.stats()
            return json.dumps(result, default=str)

    async def get_instructions(self, ctx: RunContext[Any]) -> list[str] | None:
        """Inject Graphify graph context into the system prompt."""
        graphify_context = getattr(ctx.deps, "graphify_context", None)
        repo_path = (
            getattr(graphify_context, "repo_path", None) if graphify_context else None
        ) or self._repo_path
        return [_format_instructions(repo_path)]


def _format_instructions(repo_path: str | None) -> str:
    """Build the system-prompt guidance string for Graphify tools."""
    header = "## Code Graph (Graphify)\n\n"
    if repo_path:
        header += f"Default repository: `{repo_path}`\n\n"
    return (
        header
        + "A Graphify knowledge graph maps this codebase (and its docs) into "
        "queryable nodes and relationships. Prefer graph queries over blind "
        "file reads:\n"
        "- Use `query_code_graph` to answer questions and get a scoped subgraph.\n"
        "- Use `explain_code_node` to understand a single concept or symbol.\n"
        "- Use `find_code_path` to see how two parts of the code connect.\n"
        "- Use `code_graph_god_nodes` and `code_graph_stats` to grasp the "
        "overall architecture.\n"
        "Only read raw files after the graph has oriented you, or to "
        "modify/debug specific lines."
    )


__all__ = ["GraphifyToolset"]

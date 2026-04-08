"""PotpieBackend protocol — shared interface for REST and local-runtime backends.

All CLI commands and the CodeGraphToolset depend only on this Protocol,
staying backend-agnostic regardless of whether potpie is accessed via
HTTP (RestBackend) or in-process (RuntimeBackend).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from langchain_core.tools import StructuredTool


@runtime_checkable
class PotpieBackend(Protocol):
    """Common interface for all potpie backend implementations."""

    # ── Tool registry (RuntimeBackend only) ──────────────────────────────

    async def get_tools(
        self,
        tool_names: list[str],
        exclude_embedding_tools: bool = False,
    ) -> list[StructuredTool]:
        """Fetch raw StructuredTool instances by name from the tool registry.

        Only meaningful for RuntimeBackend (direct ToolService access).
        RestBackend raises NotImplementedError — use the high-level graph
        query methods instead.

        Args:
            tool_names: Names of tools to retrieve from ToolService.
            exclude_embedding_tools: When True, skip tools that require
                embeddings (use during project INFERRING state).

        Returns:
            List of StructuredTool instances ready for wrapping.
        """
        ...

    # ── Graph query (used by CodeGraphToolset / agent) ────────────────────

    async def nl_query(self, project_id: str, query: str) -> dict:
        """Translate a natural-language structural question to Cypher and run it.

        Returns:
            ``{"cypher_used": str, "results": list[dict], "count": int}``
        """
        ...

    async def kg_search(
        self,
        project_id: str,
        queries: list[str],
        node_ids: list[str] | None = None,
    ) -> list:
        """Semantic / docstring similarity search over the knowledge graph.

        Returns:
            List of result dicts with ``node_id``, ``docstring``, ``file_path``,
            ``start_line``, ``end_line``, ``similarity``.
        """
        ...

    async def search(self, project_id: str, query: str) -> list:
        """Fast keyword search over the SQL search index.

        Returns:
            List of result dicts.
        """
        ...

    # ── Parsing ───────────────────────────────────────────────────────────

    async def parse(
        self,
        repo_path: str | None,
        repo_name: str | None,
        branch: str,
        commit_id: str | None = None,
    ) -> dict:
        """Register and parse a repository into the code graph.

        Returns:
            ``{"project_id": str, "status": str, "message": str}``
        """
        ...

    async def parsing_status(self, project_id: str) -> dict:
        """Return current parsing status for *project_id*.

        Returns:
            ``{"project_id": str, "status": str}``
        """
        ...

    # ── Projects ──────────────────────────────────────────────────────────

    async def list_projects(self) -> list:
        """List all projects for the configured user.

        Returns:
            List of project dicts with at least ``id``, ``repo_name``,
            ``branch_name``, ``status``.
        """
        ...

    async def delete_project(self, project_id: str) -> dict:
        """Delete *project_id* and its graph data.

        Returns:
            ``{"deleted": str}``
        """
        ...

    async def delete_all_projects(self) -> dict:
        """Delete all projects for the configured user.

        Returns:
            ``{"deleted": int}``
        """
        ...

    # ── Agents ────────────────────────────────────────────────────────────

    async def list_agents(self) -> list:
        """List available potpie agent definitions.

        Returns:
            List of dicts with at least ``id``, ``name``, ``description``.
        """
        ...

    # ── Inference cache ───────────────────────────────────────────────────

    async def cache_stats(self, project_id: str | None = None) -> dict:
        """Return inference cache statistics.

        Returns:
            Dict with ``total_entries``, ``total_access_count``,
            ``average_access_count``, and TTL info.
        """
        ...

    async def cache_clean(
        self,
        *,
        all: bool = False,
        project_id: str | None = None,
        expired: bool = False,
        trim: bool = False,
        max_entries: int = 100_000,
    ) -> dict:
        """Clean inference cache rows.

        Returns:
            Dict with ``removed`` count(s) per operation performed.
        """
        ...


__all__ = ["PotpieBackend"]

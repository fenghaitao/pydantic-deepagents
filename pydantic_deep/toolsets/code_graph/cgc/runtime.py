"""Runtime backend — calls CodeGraphContext MCPServer directly in-process.

This wraps the synchronous ``MCPServer`` tool methods from the
``codegraphcontext`` package via ``asyncio.to_thread``, making them safe
to call from async pydantic-ai agent code.

The MCPServer is initialized lazily on the first call and reused for the
lifetime of the backend instance. Call ``close()`` when done (or use
``async with CGCRuntime(...) as r:``).

Requires:
  - ``codegraphcontext`` Python package installed
  - A ``.codegraphcontext/`` database directory either in ``repo_path``
    or in the current working directory (created by ``cgc index <path>``)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CGCRuntime:
    """Runtime that calls CodeGraphContext MCPServer directly in-process.

    Instantiation is cheap; the MCPServer is created on the first call.
    All tool methods are async and delegate to the underlying synchronous
    MCPServer methods via ``asyncio.to_thread``.
    """

    def __init__(self, repo_path: str | None = None) -> None:
        self._repo_path = repo_path
        self._server: Any | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def _get_server(self) -> Any:
        if self._server is None:
            from codegraphcontext.server import MCPServer

            cwd = Path(self._repo_path) if self._repo_path else Path.cwd()
            self._server = MCPServer(cwd=cwd)
            logger.debug("CGCRuntime: MCPServer initialized at %s", cwd)
        return self._server

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None

    async def __aenter__(self) -> CGCRuntime:
        return self

    async def __aexit__(self, *_: Any) -> None:
        self.close()

    # ── Search ─────────────────────────────────────────────────────────────

    async def find_code(
        self,
        query: str,
        repo_path: str | None = None,
        fuzzy_search: bool = False,
    ) -> dict[str, Any]:
        """Find code by keyword or symbol name.

        Args:
            query: Keyword or phrase to search for.
            repo_path: Optional repository path to restrict the search.
            fuzzy_search: Enable fuzzy matching.

        Returns:
            Dict with ``results`` list and status information.
        """
        server = self._get_server()
        kwargs: dict[str, Any] = {"query": query}
        if repo_path:
            kwargs["repo_path"] = repo_path
        if fuzzy_search:
            kwargs["fuzzy_search"] = fuzzy_search
        return await asyncio.to_thread(server.find_code_tool, **kwargs)

    async def analyze_relationships(
        self,
        query_type: str,
        target: str,
        context: str | None = None,
        repo_path: str | None = None,
    ) -> dict[str, Any]:
        """Analyze code relationships (callers, callees, class hierarchy, etc.).

        Args:
            query_type: One of ``find_callers``, ``find_callees``,
                ``find_all_callers``, ``find_all_callees``, ``find_importers``,
                ``who_modifies``, ``class_hierarchy``, ``overrides``,
                ``dead_code``, ``call_chain``, ``module_deps``,
                ``variable_scope``, ``find_complexity``,
                ``find_functions_by_argument``, ``find_functions_by_decorator``.
            target: Function, class, or module to analyze.
            context: Optional file path for disambiguation.
            repo_path: Optional repository path to restrict the query.

        Returns:
            Dict with relationship results.
        """
        server = self._get_server()
        kwargs: dict[str, Any] = {"query_type": query_type, "target": target}
        if context:
            kwargs["context"] = context
        if repo_path:
            kwargs["repo_path"] = repo_path
        return await asyncio.to_thread(server.analyze_code_relationships_tool, **kwargs)

    async def execute_cypher(self, cypher_query: str) -> dict[str, Any]:
        """Execute a read-only Cypher query directly against the code graph.

        Args:
            cypher_query: Read-only Cypher query string.

        Returns:
            Dict with query results.
        """
        server = self._get_server()
        return await asyncio.to_thread(
            server.execute_cypher_query_tool, cypher_query=cypher_query
        )

    # ── Repository management ──────────────────────────────────────────────

    async def list_repositories(self) -> dict[str, Any]:
        """List all indexed repositories.

        Returns:
            Dict with list of indexed repositories and their metadata.
        """
        server = self._get_server()
        return await asyncio.to_thread(server.list_indexed_repositories_tool)

    async def add_code_to_graph(
        self, path: str, is_dependency: bool = False
    ) -> dict[str, Any]:
        """Index a local directory into the code graph.

        Returns a job_id for background processing; use
        ``check_job_status()`` to poll for completion.

        Args:
            path: Absolute path to the directory to index.
            is_dependency: Whether this code is a third-party dependency.

        Returns:
            Dict with ``job_id`` for polling.
        """
        server = self._get_server()
        return await asyncio.to_thread(
            server.add_code_to_graph_tool, path=path, is_dependency=is_dependency
        )

    async def check_job_status(self, job_id: str) -> dict[str, Any]:
        """Check the progress of a background indexing job.

        Args:
            job_id: Job ID returned by ``add_code_to_graph()``.

        Returns:
            Dict with job status and progress information.
        """
        server = self._get_server()
        return await asyncio.to_thread(server.check_job_status_tool, job_id=job_id)

    async def delete_repository(self, repo_path: str) -> dict[str, Any]:
        """Remove an indexed repository from the graph.

        Args:
            repo_path: Absolute path to the repository to remove.

        Returns:
            Dict with deletion result.
        """
        server = self._get_server()
        return await asyncio.to_thread(
            server.delete_repository_tool, repo_path=repo_path
        )

    async def get_stats(self, repo_path: str | None = None) -> dict[str, Any]:
        """Get statistics about indexed repositories.

        Args:
            repo_path: Optional path to a specific repository. If omitted,
                returns overall database statistics.

        Returns:
            Dict with counts of files, functions, classes, and modules.
        """
        server = self._get_server()
        kwargs: dict[str, Any] = {}
        if repo_path:
            kwargs["repo_path"] = repo_path
        return await asyncio.to_thread(server.get_repository_stats_tool, **kwargs)


__all__ = ["CGCRuntime"]

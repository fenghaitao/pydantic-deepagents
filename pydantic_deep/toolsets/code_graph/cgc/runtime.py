"""Runtime backend — calls CodeGraphContext tools directly in-process.

Bypasses ``MCPServer`` and wires directly to the underlying components:
  ``get_database_manager`` / ``CodeFinder`` / ``GraphBuilder`` / ``JobManager``
  and the handler functions in ``codegraphcontext.tools.handlers``.

The components are initialized lazily on the first call and reused for the
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
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CGCRuntime:
    """Runtime that calls CodeGraphContext components directly in-process.

    Instantiation is cheap; components are created on the first call.
    All tool methods are async and delegate to synchronous handler functions
    via ``asyncio.to_thread``.
    """

    def __init__(self, repo_path: str | None = None) -> None:
        self._repo_path = repo_path
        self._db_manager: Any | None = None
        self._code_finder: Any | None = None
        self._graph_builder: Any | None = None
        self._job_manager: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def _get_components(self) -> tuple[Any, Any, Any, Any]:
        """Lazily initialize and return (db_manager, code_finder, graph_builder, job_manager)."""
        if self._db_manager is None:
            from codegraphcontext.cli.config_manager import resolve_context
            from codegraphcontext.core import get_database_manager
            from codegraphcontext.core.jobs import JobManager
            from codegraphcontext.tools.code_finder import CodeFinder
            from codegraphcontext.tools.graph_builder import GraphBuilder

            cwd = Path(self._repo_path) if self._repo_path else Path.cwd()
            ctx = resolve_context(cwd=cwd)
            if ctx.database:
                os.environ["CGC_RUNTIME_DB_TYPE"] = ctx.database

            self._db_manager = get_database_manager(db_path=ctx.db_path)
            self._db_manager.get_driver()

            self._job_manager = JobManager()
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:  # pragma: no cover
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)

            self._graph_builder = GraphBuilder(self._db_manager, self._job_manager, self._loop)
            self._code_finder = CodeFinder(self._db_manager)
            logger.debug("CGCRuntime: components initialized at %s", cwd)

        return self._db_manager, self._code_finder, self._graph_builder, self._job_manager

    def close(self) -> None:
        if self._db_manager is not None:
            self._db_manager.close_driver()
            self._db_manager = None
            self._code_finder = None
            self._graph_builder = None
            self._job_manager = None
            self._loop = None

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
        _, code_finder, _, _ = self._get_components()
        from codegraphcontext.tools.handlers import analysis_handlers

        kwargs: dict[str, Any] = {"query": query}
        if repo_path:
            kwargs["repo_path"] = repo_path
        if fuzzy_search:
            kwargs["fuzzy_search"] = fuzzy_search
        return await asyncio.to_thread(analysis_handlers.find_code, code_finder, **kwargs)

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
        _, code_finder, _, _ = self._get_components()
        from codegraphcontext.tools.handlers import analysis_handlers

        kwargs: dict[str, Any] = {"query_type": query_type, "target": target}
        if context:
            kwargs["context"] = context
        if repo_path:
            kwargs["repo_path"] = repo_path
        return await asyncio.to_thread(
            analysis_handlers.analyze_code_relationships, code_finder, **kwargs
        )

    async def execute_cypher(self, cypher_query: str) -> dict[str, Any]:
        """Execute a read-only Cypher query directly against the code graph.

        Args:
            cypher_query: Read-only Cypher query string.

        Returns:
            Dict with query results.
        """
        db_manager, _, _, _ = self._get_components()
        from codegraphcontext.tools.handlers import query_handlers

        return await asyncio.to_thread(
            query_handlers.execute_cypher_query, db_manager, cypher_query=cypher_query
        )

    # ── Repository management ──────────────────────────────────────────────

    async def list_repositories(self) -> dict[str, Any]:
        """List all indexed repositories.

        Returns:
            Dict with list of indexed repositories and their metadata.
        """
        _, code_finder, _, _ = self._get_components()
        from codegraphcontext.tools.handlers import management_handlers

        return await asyncio.to_thread(
            management_handlers.list_indexed_repositories, code_finder
        )

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
        _, code_finder, graph_builder, job_manager = self._get_components()
        from codegraphcontext.tools.handlers import indexing_handlers, management_handlers

        loop = self._loop
        list_repos_func = lambda: management_handlers.list_indexed_repositories(code_finder)  # noqa: E731
        return await asyncio.to_thread(
            indexing_handlers.add_code_to_graph,
            graph_builder,
            job_manager,
            loop,
            list_repos_func,
            path=path,
            is_dependency=is_dependency,
        )

    async def check_job_status(self, job_id: str) -> dict[str, Any]:
        """Check the progress of a background indexing job.

        Args:
            job_id: Job ID returned by ``add_code_to_graph()``.

        Returns:
            Dict with job status and progress information.
        """
        _, _, _, job_manager = self._get_components()
        from codegraphcontext.tools.handlers import management_handlers

        return await asyncio.to_thread(
            management_handlers.check_job_status, job_manager, job_id=job_id
        )

    async def delete_repository(self, repo_path: str) -> dict[str, Any]:
        """Remove an indexed repository from the graph.

        Args:
            repo_path: Absolute path to the repository to remove.

        Returns:
            Dict with deletion result.
        """
        _, _, graph_builder, _ = self._get_components()
        from codegraphcontext.tools.handlers import management_handlers

        return await asyncio.to_thread(
            management_handlers.delete_repository, graph_builder, repo_path=repo_path
        )

    async def get_stats(self, repo_path: str | None = None) -> dict[str, Any]:
        """Get statistics about indexed repositories.

        Args:
            repo_path: Optional path to a specific repository. If omitted,
                returns overall database statistics.

        Returns:
            Dict with counts of files, functions, classes, and modules.
        """
        _, code_finder, _, _ = self._get_components()
        from codegraphcontext.tools.handlers import management_handlers

        kwargs: dict[str, Any] = {}
        if repo_path:
            kwargs["repo_path"] = repo_path
        return await asyncio.to_thread(
            management_handlers.get_repository_stats, code_finder, **kwargs
        )


__all__ = ["CGCRuntime"]

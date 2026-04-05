"""Runtime backend — calls PotpieRuntime directly in-process (no HTTP).

This mirrors the approach used by potpie_cli.py: no HTTP server required,
only the DB credentials (NEO4J_URI, POSTGRES_SERVER, etc.) in the environment.

The runtime is initialized lazily on the first call and reused for the
lifetime of the backend instance.  Call ``close()`` when done (or use
``async with RuntimeBackend() as b:``).

Requires:
  - ``potpie`` Python package installed (in the same environment)
  - Database credentials available in environment variables
  - POTPIE_USER_ID env var for the default user (falls back to "defaultuser")
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from potpie import PotpieRuntime

logger = logging.getLogger(__name__)

_DEFAULT_USER_ID = "defaultuser"


class RuntimeBackend:
    """PotpieBackend implementation that calls PotpieRuntime directly.

    Instantiation is cheap; the runtime is initialized on the first call.
    """

    def __init__(self, user_id: str | None = None) -> None:
        self._user_id: str = (
            user_id
            or os.environ.get("POTPIE_USER_ID", _DEFAULT_USER_ID)
        )
        self._runtime: Optional[PotpieRuntime] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def _get_runtime(self) -> PotpieRuntime:
        if self._runtime is None:
            from potpie import PotpieRuntime as _RT

            self._runtime = _RT.from_env()
            await self._runtime.initialize()
            logger.debug("RuntimeBackend: PotpieRuntime initialized")
        return self._runtime

    async def close(self) -> None:
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

    async def __aenter__(self) -> RuntimeBackend:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── Graph query ───────────────────────────────────────────────────────

    async def nl_query(self, project_id: str, query: str) -> dict:
        from app.modules.intelligence.tools.kg_based_tools.nl_cypher_query_tool import (
            NLCypherQueryTool,
        )

        rt = await self._get_runtime()
        session = rt.db.get_session()
        try:
            tool = NLCypherQueryTool(sql_db=session, user_id=self._user_id)
            return await tool.arun(project_id=project_id, query=query)
        finally:
            session.close()

    async def kg_search(
        self,
        project_id: str,
        queries: list[str],
        node_ids: list[str] | None = None,
    ) -> list:
        from app.modules.intelligence.tools.kg_based_tools.ask_knowledge_graph_queries_tool import (
            KnowledgeGraphQueryTool,
        )

        rt = await self._get_runtime()
        session = rt.db.get_session()
        try:
            tool = KnowledgeGraphQueryTool(sql_db=session, user_id=self._user_id)
            result = await tool.arun(
                queries=queries,
                project_id=project_id,
                node_ids=node_ids or [],
            )
            return result if isinstance(result, list) else list(result.values())
        finally:
            session.close()

    async def search(self, project_id: str, query: str) -> list:
        from app.modules.search.search_service import SearchService

        rt = await self._get_runtime()
        session = rt.db.get_session()
        try:
            svc = SearchService(session)
            results = await svc.search_codebase(project_id, query)
            return results if isinstance(results, list) else []
        finally:
            session.close()

    # ── Parsing ───────────────────────────────────────────────────────────

    async def parse(
        self,
        repo_path: str | None,
        repo_name: str | None,
        branch: str,
        commit_id: str | None = None,
    ) -> dict:
        rt = await self._get_runtime()

        # Auto-detect git commit if not provided
        effective_commit = commit_id
        if not effective_commit and repo_path:
            try:
                from git import Repo as GitRepo

                effective_commit = GitRepo(repo_path).head.commit.hexsha
            except Exception:
                pass

        # Determine canonical repo_name for registration
        canonical_name: str
        if repo_name:
            canonical_name = repo_name
        elif repo_path:
            canonical_name = Path(repo_path).name
        else:
            raise ValueError("Either repo_path or repo_name must be provided.")

        project_id = await rt.projects.register(
            repo_name=canonical_name,
            branch_name=branch,
            user_id=self._user_id,
            repo_path=repo_path,
            commit_id=effective_commit,
        )

        result = await rt.parsing.parse_project(
            project_id=project_id,
            user_id=self._user_id,
            user_email=f"{self._user_id}@cli.local",
            cleanup_graph=True,
            commit_id=effective_commit,
        )

        status = "READY" if result.success else "ERROR"
        return {
            "project_id": project_id,
            "status": status,
            "message": result.error_message or "Parsing complete.",
        }

    async def parsing_status(self, project_id: str) -> dict:
        rt = await self._get_runtime()
        status = await rt.parsing.get_status(project_id)
        return {"project_id": project_id, "status": status.value}

    # ── Projects ──────────────────────────────────────────────────────────

    async def list_projects(self) -> list:
        rt = await self._get_runtime()
        projects = await rt.projects.list(user_id=self._user_id)
        return [
            {
                "id": p.id,
                "repo_name": p.repo_name,
                "branch_name": p.branch_name,
                "status": p.status.value,
                "repo_path": getattr(p, "repo_path", "") or "",
            }
            for p in projects
        ]

    async def delete_project(self, project_id: str) -> dict:
        rt = await self._get_runtime()
        await rt.projects.delete(project_id)
        return {"deleted": project_id}

    async def delete_all_projects(self) -> dict:
        rt = await self._get_runtime()
        projects = await rt.projects.list(user_id=self._user_id)
        deleted = 0
        errors: list[str] = []
        for p in projects:
            try:
                await rt.projects.delete(p.id)
                deleted += 1
            except Exception as exc:
                errors.append(f"{p.id}: {exc}")
        result: dict[str, Any] = {"deleted": deleted}
        if errors:
            result["errors"] = errors
        return result

    # ── Agents ────────────────────────────────────────────────────────────

    async def list_agents(self) -> list:
        rt = await self._get_runtime()
        agents = rt.agents.list_agents()
        return [
            {"id": a.id, "name": a.name, "description": a.description}
            for a in agents
        ]

    # ── Cache ─────────────────────────────────────────────────────────────

    async def cache_stats(self, project_id: str | None = None) -> dict:
        from app.modules.parsing.services.cache_cleanup_service import (
            CacheCleanupService,
        )
        from app.modules.parsing.services.inference_cache_service import (
            InferenceCacheService,
        )

        rt = await self._get_runtime()
        session = rt.db.get_session()
        try:
            stats = InferenceCacheService(session).get_cache_stats(
                project_id=project_id
            )
            cstats = CacheCleanupService(session).get_cleanup_stats()
            return {**stats, **cstats}
        finally:
            session.close()

    async def cache_clean(
        self,
        *,
        all: bool = False,
        project_id: str | None = None,
        expired: bool = False,
        trim: bool = False,
        max_entries: int = 100_000,
    ) -> dict:
        from app.modules.parsing.services.cache_cleanup_service import (
            CacheCleanupService,
        )

        rt = await self._get_runtime()
        session = rt.db.get_session()
        removed: dict[str, int] = {}
        try:
            svc = CacheCleanupService(session)
            if all:
                removed["all"] = svc.clear_all_entries()
            elif project_id:
                removed["project"] = svc.clear_entries_for_project(project_id)
            if expired and not all:
                removed["expired"] = svc.cleanup_expired_entries()
            if trim and not all:
                n = svc.cleanup_least_accessed(max_entries=max_entries)
                removed["trimmed"] = n or 0
            return removed
        finally:
            session.close()


__all__ = ["RuntimeBackend"]

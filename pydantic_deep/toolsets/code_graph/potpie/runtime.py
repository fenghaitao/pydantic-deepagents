"""Runtime backend — calls PotpieRuntime directly in-process (no HTTP).

This mirrors the approach used by potpie_cli.py: no HTTP server required,
only the DB credentials (NEO4J_URI, POSTGRES_SERVER, etc.) in the environment.

The runtime is initialized lazily on the first call and reused for the
lifetime of the backend instance.  Call ``close()`` when done (or use
``async with PotpieRuntime() as b:``).

Requires:
  - ``potpie`` Python package installed (in the same environment)
  - Database credentials available in environment variables
  - POTPIE_USER_ID env var for the default user (falls back to "defaultuser")
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from potpie import PotpieRuntime as _PotpieRuntime

logger = logging.getLogger(__name__)

_DEFAULT_USER_ID = "defaultuser"


class PotpieRuntime:
    """Async adapter that calls potpie's PotpieRuntime directly in-process.

    Instantiation is cheap; the runtime is initialized on the first call.
    """

    def __init__(self, user_id: str | None = None) -> None:
        self._user_id: str = user_id or os.environ.get("POTPIE_USER_ID", _DEFAULT_USER_ID)
        self._runtime: _PotpieRuntime | None = None
        self._init_lock: asyncio.Lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def _get_runtime(self) -> _PotpieRuntime:
        # Fast path — already initialized (lock-free read is safe in Python's GIL)
        if self._runtime is not None:
            return self._runtime
        # Slow path — only one coroutine does the initialization; others wait.
        async with self._init_lock:
            if self._runtime is not None:  # pragma: no cover
                return self._runtime  # pragma: no cover
            from potpie import PotpieRuntime as _RT

            rt = _RT.from_env()
            await rt.initialize()
            # Only assign after successful init so callers never see a
            # partially-initialized runtime.
            self._runtime = rt
            logger.debug("PotpieRuntime: initialized")
        return self._runtime

    async def close(self) -> None:
        if self._runtime is not None:
            await self._runtime.close()
            self._runtime = None

    async def __aenter__(self) -> PotpieRuntime:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── Tool registry ─────────────────────────────────────────────────────

    async def get_tools(
        self,
        tool_names: list[str],
        exclude_embedding_tools: bool = False,
    ) -> list:
        """Fetch StructuredTool instances by name from ToolService.

        Opens a short-lived DB session, retrieves the requested tools, and
        closes the session immediately. The returned StructuredTool objects
        are stateless after construction and manage their own DB access.

        Args:
            tool_names: Names of tools to retrieve.
            exclude_embedding_tools: Skip embedding-dependent tools (use
                when project is in INFERRING state).

        Returns:
            List of StructuredTool instances.
        """
        from app.modules.intelligence.tools.tool_service import ToolService

        rt = await self._get_runtime()
        session = rt.db.get_session()
        try:
            svc = ToolService(db=session, user_id=self._user_id)
            return svc.get_tools(tool_names, exclude_embedding_tools=exclude_embedding_tools)
        finally:
            session.close()

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

    async def analyze_register_side_effect(
        self,
        project_id: str,
        device_name: str,
        refresh: bool = False,
        batch_size: int = 30,
        chunk_tokens: int = 15000,
    ) -> dict:
        from app.modules.intelligence.tools.simics_device_tools.analyze_register_side_effect_tool import (
            AnalyzeRegisterSideEffectTool,
        )

        rt = await self._get_runtime()
        session = rt.db.get_session()
        try:
            tool = AnalyzeRegisterSideEffectTool(sql_db=session, user_id=self._user_id)
            return await tool.arun(
                project_id=project_id,
                device_name=device_name,
                refresh=refresh,
                batch_size=batch_size,
                chunk_tokens=chunk_tokens,
            )
        finally:
            session.close()

    async def analyze_capability(
        self,
        project_id: str,
        device_name: str,
        refresh: bool = False,
        chunk_tokens: int = 15000,
    ) -> dict:
        from app.modules.intelligence.tools.simics_device_tools.analyze_capability_tool import (
            AnalyzeCapabilityTool,
        )

        rt = await self._get_runtime()
        session = rt.db.get_session()
        try:
            tool = AnalyzeCapabilityTool(sql_db=session, user_id=self._user_id)
            return await tool.arun(
                project_id=project_id,
                device_name=device_name,
                refresh=refresh,
                chunk_tokens=chunk_tokens,
            )
        finally:
            session.close()

    async def list_capability(
        self,
        project_id: str,
        device_name: str,
    ) -> dict:
        from app.modules.intelligence.tools.simics_device_tools.list_capability_tool import (
            ListCapabilityTool,
        )

        rt = await self._get_runtime()
        session = rt.db.get_session()
        try:
            tool = ListCapabilityTool(sql_db=session, user_id=self._user_id)
            return await tool.arun(
                project_id=project_id,
                device_name=device_name,
            )
        finally:
            session.close()

    async def list_register_side_effect(
        self,
        project_id: str,
        device_name: str,
    ) -> dict:
        from app.modules.intelligence.tools.simics_device_tools.list_register_side_effect_tool import (
            ListRegisterSideEffectTool,
        )

        rt = await self._get_runtime()
        session = rt.db.get_session()
        try:
            tool = ListRegisterSideEffectTool(sql_db=session, user_id=self._user_id)
            return await tool.arun(
                project_id=project_id,
                device_name=device_name,
            )
        finally:
            session.close()

    # ── Parsing ───────────────────────────────────────────────────────────

    async def register_project(
        self,
        project_name: str,
        branch: str = "main",
    ) -> dict:
        """Register a named project without parsing any repository.

        Creates a project record keyed by *project_name* and *branch*.  No
        graph parsing or embedding is performed, so the project can be used
        immediately as a LightRAG workspace target (e.g. for ``spec index``).

        Args:
            project_name: Human-readable name for the project.
            branch: Branch label stored with the project (default ``"main"``).

        Returns:
            ``{"project_id": str, "status": str}``
        """
        rt = await self._get_runtime()
        project_id = await rt.projects.register(
            repo_name=project_name,
            branch_name=branch,
            user_id=self._user_id,
            repo_path=None,
            commit_id=None,
        )
        return {"project_id": project_id, "status": "REGISTERED"}

    async def parse(
        self,
        repo_path: str | None,
        repo_name: str | None,
        branch: str | None,
        commit_id: str | None = None,
    ) -> dict:
        rt = await self._get_runtime()

        # Resolve relative paths (e.g. ".") to absolute before deriving the name
        # — mirrors potpie_cli.py's _parse_repo which does the same.
        if repo_path:
            repo_path = str(Path(repo_path).expanduser().resolve())

        # Derive repo_name from path when not explicitly provided (matches potpie_cli behaviour)
        if not repo_name and repo_path:
            repo_name = Path(repo_path).name

        # Auto-detect git commit if not provided
        effective_commit = commit_id
        if not effective_commit and repo_path:
            try:
                from git import Repo as GitRepo

                effective_commit = GitRepo(repo_path).head.commit.hexsha
            except Exception:
                pass

        if not branch:
            try:
                from git import Repo as GitRepo

                branch = GitRepo(repo_path).active_branch.name if repo_path else "main"
            except Exception:
                branch = "main"

        # Determine canonical repo_name for registration
        canonical_name: str
        if repo_name:
            canonical_name = repo_name
        elif repo_path:
            canonical_name = Path(repo_path).name
        else:
            raise ValueError("Either repo_path or repo_name must be provided.")

        print(f"[kg] Starting parse: repo='{canonical_name}' branch='{branch}' commit='{effective_commit or 'unspecified'}'...")
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

        repo_paths: dict[str, str] = {}
        try:
            from app.modules.projects.projects_model import Project as _Project  # pragma: no cover

            session = rt.db.get_session()  # pragma: no cover
            try:  # pragma: no cover
                rows = (  # pragma: no cover
                    session.query(_Project)
                    .filter(_Project.user_id == self._user_id)
                    .all()
                )
                repo_paths = {r.id: r.repo_path or "" for r in rows}  # pragma: no cover
            finally:  # pragma: no cover
                session.close()  # pragma: no cover
        except Exception:  # pragma: no cover
            pass  # pragma: no cover

        return [
            {
                "id": p.id,
                "repo_name": p.repo_name,
                "branch_name": p.branch_name or "",
                "status": str(p.status.value) if hasattr(p.status, "value") else str(p.status) if p.status is not None else "",
                "repo_path": repo_paths.get(p.id) or getattr(p, "repo_path", "") or "",
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
        return [{"id": a.id, "name": a.name, "description": a.description} for a in agents]

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
            stats = InferenceCacheService(session).get_cache_stats(project_id=project_id)
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

    # ── Spec documentation (LightRAG) ─────────────────────────────────────

    async def spec_insert_texts(
        self,
        project_id: str,
        user_id: str,
        texts: list[str],
        file_paths: list[str] | None = None,
        prompt: str | None = None,
    ) -> dict:
        """Insert raw text documents directly into the LightRAG workspace.

        The caller provides the document texts to index; the result shares the
        same workspace so ``spec_query`` can read it.

        Args:
            project_id: Potpie project UUID (used to derive workspace name).
            user_id: User ID (used to derive workspace name).
            texts: List of document text strings to insert.
            file_paths: List of file paths corresponding to the texts.
            prompt: Additional user prompt for LightRAG entity extraction.

        Returns:
            ``{"inserted": int, "workspace": str}``
        """
        from app.core.config_provider import config_provider
        from app.modules.parsing.lightrag_sync.lightrag_ingest_service import (
            LightRAGIngestService,
        )
        svc = LightRAGIngestService.from_config(config_provider.get_neo4j_config())
        return await svc.insert_texts(project_id=project_id, user_id=user_id, texts=texts, file_paths=file_paths, prompt=prompt)

    async def spec_query(
        self,
        project_id: str,
        user_id: str,
        query: str,
        mode: str = "hybrid",
        summarize: bool = False,
    ) -> str:
        """Query the LightRAG workspace for *project_id* with natural language.

        Args:
            project_id: Potpie project UUID.
            user_id: User ID.
            query: Natural language query string.
            mode: LightRAG query mode — ``local``, ``global``, ``hybrid``,
                  ``mix``, ``naive``, or ``bypass``.  Default ``hybrid``.

        Returns:
            Answer string from LightRAG.
        """
        from app.modules.parsing.lightrag_sync.lightrag_query_service import (
            LightRAGQueryService,
        )
        svc = LightRAGQueryService()
        return await svc.query(project_id=project_id, user_id=user_id, question=query, mode=mode, summarize=summarize)

    async def spec_diff(
        self,
        project_id_a: str,
        project_id_b: str,
        user_id: str,
        mode: str = "hybrid",
        summarize: bool = False,
    ) -> str:
        """Query two LightRAG workspaces and return an LLM-generated delta.

        Traverses both knowledge graphs directly, computes the structural delta,
        then asks the LLM to narrate the changes.

        Args:
            project_id_a: Potpie project UUID for the base (first) spec.
            project_id_b: Potpie project UUID for the new (second) spec.
            user_id: User ID shared by both workspaces.
            mode: LightRAG query mode.  Default ``hybrid``.
            summarize: When ``True`` (default) produce a high-level feature
                summary grouped under broad headings.  When ``False`` produce
                signal-level detail: exact register/field/signal names, bit
                widths, reset values, and precise behavioural differences.

        Returns:
            LLM-generated delta string comparing the two specs.
        """
        from app.modules.parsing.lightrag_sync.lightrag_query_service import (
            LightRAGQueryService,
        )

        svc = LightRAGQueryService()
        return await svc.diff(
            user_id=user_id,
            project_id_a=project_id_a,
            project_id_b=project_id_b,
            mode=mode,
            summarize=summarize,
        )


__all__ = ["PotpieRuntime"]

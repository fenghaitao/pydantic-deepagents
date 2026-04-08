"""REST backend — communicates with the running potpie FastAPI service via HTTP.

Requires:
  - potpie service is running (started via singularity or manually)
  - ``base_url`` pointing at the service (auto-discovered if not set)
  - ``api_key`` provided via config / env POTPIE_API_KEY

All HTTP errors are mapped to plain RuntimeError with a human-readable message
so callers don't need to import httpx.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RestBackend:
    """PotpieBackend implementation that talks to the potpie REST API.

    All endpoints live under ``/api/v2`` (API-key authenticated).
    Graph-specific endpoints are under ``/api/v2/graph/`` (new endpoints
    added to ``app/api/graph_router.py``).
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    # ── Tool registry ─────────────────────────────────────────────────────

    async def get_tools(
        self,
        tool_names: list[str],
        exclude_embedding_tools: bool = False,
    ) -> list:
        """Not supported over REST — raises NotImplementedError.

        The REST backend exposes only the four high-level graph query
        endpoints. Direct ToolService access requires RuntimeBackend.
        """
        raise NotImplementedError(
            "get_tools() is not available in REST mode. "
            "Switch to local mode (potpie_mode=local) to access the full tool registry."
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key, "Content-Type": "application/json"}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        import httpx

        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=self._headers(), params=params)
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        import httpx

        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            return resp.json()

    async def _delete(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        import httpx

        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.delete(url, headers=self._headers(), params=params)
            resp.raise_for_status()
            return resp.json()

    # ── Graph query ───────────────────────────────────────────────────────

    async def nl_query(self, project_id: str, query: str) -> dict:
        return await self._post(
            "/api/v2/graph/nl-query",
            {"project_id": project_id, "query": query},
        )

    async def kg_search(
        self,
        project_id: str,
        queries: list[str],
        node_ids: list[str] | None = None,
    ) -> list:
        result = await self._post(
            "/api/v2/graph/kg-search",
            {
                "project_id": project_id,
                "queries": queries,
                "node_ids": node_ids or [],
            },
        )
        return result if isinstance(result, list) else result.get("results", [])

    async def search(self, project_id: str, query: str) -> list:
        result = await self._post(
            "/api/v2/search",
            {"project_id": project_id, "query": query},
        )
        return result if isinstance(result, list) else result.get("results", [])

    # ── Parsing ───────────────────────────────────────────────────────────

    async def parse(
        self,
        repo_path: str | None,
        repo_name: str | None,
        branch: str,
        commit_id: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"branch_name": branch}
        if repo_path:
            body["repo_path"] = repo_path
        if repo_name:
            body["repo_name"] = repo_name
        if commit_id:
            body["commit_id"] = commit_id
        return await self._post("/api/v1/parse", body)

    async def parsing_status(self, project_id: str) -> dict:
        return await self._get(f"/api/v1/parsing-status/{project_id}")

    # ── Projects ──────────────────────────────────────────────────────────

    async def list_projects(self) -> list:
        # /api/v1/projects/list is the canonical endpoint also used by potpie-ui;
        # it uses AuthService.check_auth which auto-returns defaultUsername in dev mode.
        result = await self._get("/api/v1/projects/list")
        return result if isinstance(result, list) else result.get("projects", [])

    async def delete_project(self, project_id: str) -> dict:
        # Uses the existing DELETE /api/v1/projects?project_id=<id> endpoint
        return await self._delete("/api/v1/projects", params={"project_id": project_id})

    async def delete_all_projects(self) -> dict:
        return await self._delete("/api/v2/graph/projects")

    # ── Agents ────────────────────────────────────────────────────────────

    async def list_agents(self) -> list:
        # Uses the existing GET /api/v1/list-available-agents endpoint
        result = await self._get("/api/v1/list-available-agents/")
        return result if isinstance(result, list) else result.get("agents", [])

    # ── Cache ─────────────────────────────────────────────────────────────

    async def cache_stats(self, project_id: str | None = None) -> dict:
        params: dict[str, Any] = {}
        if project_id:
            params["project_id"] = project_id
        return await self._get("/api/v2/graph/cache/stats", params=params or None)

    async def cache_clean(
        self,
        *,
        all: bool = False,
        project_id: str | None = None,
        expired: bool = False,
        trim: bool = False,
        max_entries: int = 100_000,
    ) -> dict:
        params: dict[str, Any] = {
            "all": all,
            "expired": expired,
            "trim": trim,
            "max_entries": max_entries,
        }
        if project_id:
            params["project_id"] = project_id
        return await self._delete("/api/v2/graph/cache/clean", params=params)


__all__ = ["RestBackend"]

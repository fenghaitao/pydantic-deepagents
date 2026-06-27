"""Code-graph provider protocol and adapters.

Defines a common ``CodeGraphProvider`` protocol that the Potpie, CGC, and
Graphify runtimes satisfy (directly or via thin adapters), so CLI commands
like ``projects list`` and ``projects delete`` work with any backend.

Usage::

    from pydantic_deep.providers.code_graph import make_provider

    provider = make_provider("cgc")
    projects = await provider.list_projects()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


@runtime_checkable
class CodeGraphProvider(Protocol):
    """Protocol for code-graph providers (Potpie, CGC, Graphify, etc.).

    Any object implementing these async methods can be used as the backend
    for CLI project-management commands.
    """

    async def list_projects(self) -> list[dict[str, Any]]:
        """Return all indexed projects/repositories.

        Each entry must contain at least:
          - ``id``         — unique identifier (UUID for Potpie, path for CGC)
          - ``repo_name``  — display name
          - ``branch_name``— branch (empty string for CGC)
          - ``status``     — ready/error/etc.
        """
        ...  # pragma: no cover

    async def delete_project(self, project_id: str) -> dict[str, Any]:
        """Delete a single project/repository by its ``id``."""
        ...  # pragma: no cover

    async def delete_all_projects(self) -> dict[str, Any]:
        """Delete all projects/repositories.

        Returns a dict with at minimum ``{"deleted": <count>}``.
        """
        ...  # pragma: no cover


class CGCProvider:
    """Adapts :class:`~pydantic_deep.toolsets.code_graph.cgc.runtime.CGCRuntime`
    to the :class:`CodeGraphProvider` protocol.

    ``list_projects()`` maps the CGC ``list_repositories()`` response to the
    common shape so the same table-rendering code works for both providers.
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    async def list_projects(self) -> list[dict[str, Any]]:
        result = await self._runtime.list_repositories()
        repos = result.get("repositories", [])
        return [
            {
                "id": r.get("path", r.get("name", "")),
                "repo_name": r.get("name", r.get("path", "")),
                "branch_name": "",
                "status": "ready",
            }
            for r in repos
        ]

    async def delete_project(self, project_id: str) -> dict[str, Any]:
        return await self._runtime.delete_repository(project_id)

    async def delete_all_projects(self) -> dict[str, Any]:
        repos = await self.list_projects()
        deleted = 0
        errors: list[str] = []
        for r in repos:
            try:
                await self._runtime.delete_repository(r["id"])
                deleted += 1
            except Exception as exc:
                errors.append(f"{r['id']}: {exc}")
        result: dict[str, Any] = {"deleted": deleted}
        if errors:
            result["errors"] = errors
        return result


def make_provider(provider: str, **kwargs: Any) -> CodeGraphProvider:
    """Factory that returns an appropriate :class:`CodeGraphProvider`.

    Args:
        provider: ``"potpie"`` (default), ``"cgc"``, or ``"graphify"``.
        **kwargs: Forwarded to the underlying runtime constructor.
            - Potpie:   ``user_id``
            - CGC:      ``repo_path``
            - Graphify: ``repo_path``, ``graph_path``

    Returns:
        A :class:`CodeGraphProvider`-compatible object.

    Raises:
        ValueError: If *provider* is not a known value.
    """
    if provider == "cgc":
        from pydantic_deep.toolsets.code_graph.cgc.runtime import CGCRuntime

        return CGCProvider(CGCRuntime(repo_path=kwargs.get("repo_path")))

    if provider == "potpie":
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        return PotpieRuntime(user_id=kwargs.get("user_id"))  # type: ignore[return-value]

    if provider == "graphify":
        from pydantic_deep.toolsets.code_graph.graphify.runtime import GraphifyRuntime

        return GraphifyRuntime(  # type: ignore[return-value]
            repo_path=kwargs.get("repo_path"),
            graph_path=kwargs.get("graph_path"),
        )

    raise ValueError(
        f"Unknown code-graph provider: '{provider}'. "
        "Valid values: 'potpie', 'cgc', 'graphify'."
    )


__all__ = ["CodeGraphProvider", "CGCProvider", "make_provider"]

"""Potpie resource setup for CLI agents.

Shared by interactive and non-interactive modes. Builds all potpie
resources (CodeGraphToolset, subagents, PotpieContext) from a single
RuntimeBackend, with optional git-based project auto-discovery.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PotpieResources:
    """All potpie resources needed by a CLI agent session.

    Attributes:
        toolset: CodeGraphToolset for the main agent, or None if unavailable.
        subagents: SubAgentConfig list for potpie subagents.
        context: PotpieContext to set on deps.potpie, or None.
        backend: The RuntimeBackend — caller MUST close in a finally block.
        project_id: The resolved project UUID, or None if not found.
    """

    toolset: Any = None
    subagents: list[Any] = field(default_factory=list)
    context: Any = None
    backend: Any = None
    project_id: str | None = None


async def build_potpie_resources(
    project_id: str | None,
    user_id: str,
    root: Path | None = None,
    on_status: Any | None = None,
) -> PotpieResources:
    """Build all potpie resources sharing one RuntimeBackend.

    When *project_id* is ``None`` and *root* is provided, auto-discovers
    the project from the git repo using the already-created backend,
    avoiding a second PotpieRuntime initialization.

    The caller is responsible for closing ``result.backend`` in a finally
    block after the agent run completes.

    Args:
        project_id: Explicit project UUID, or None to auto-discover.
        user_id: User ID forwarded to ToolService for access control.
        root: Working directory root for git-based auto-discovery.
        on_status: Optional callable ``(message: str) -> None`` for status
            messages (e.g. auto-discovery notice, loaded notice).

    Returns:
        PotpieResources with all fields populated on success, or a
        PotpieResources with all-None fields on failure (warning printed
        to stderr).
    """
    try:
        from apps.cli.config import load_config
        from pydantic_deep.toolsets.code_graph.context import PotpieContext
        from pydantic_deep.subagents_potpie import make_potpie_subagents
        from pydantic_deep.toolsets.code_graph import CodeGraphToolset, make_backend

        cfg = load_config()
        if cfg.potpie_mode != "local":
            return PotpieResources()

        backend = make_backend(cfg)

        try:
            # Auto-discover project from git if not explicitly provided.
            resolved_by_discovery = False
            if not project_id and root is not None:
                from apps.cli.potpie_discovery import parse_git_identity

                identity = parse_git_identity(root)
                if identity:
                    repo_name, branch = identity
                    for p in await backend.list_projects():
                        if p["repo_name"] == repo_name and p["branch_name"] == branch:
                            project_id = p["id"]
                            resolved_by_discovery = True
                            break

            if not project_id:
                await backend.close()
                return PotpieResources()

            toolset = CodeGraphToolset(backend=backend, project_id=project_id)
            context = PotpieContext(project_id=project_id, user_id=user_id)
            subagents = await make_potpie_subagents(backend=backend, user_id=user_id)

            if on_status:
                if resolved_by_discovery:
                    on_status(f"Auto-discovered Potpie project: {project_id}")
                else:
                    on_status(f"Potpie KG tools loaded for project {project_id}")

            return PotpieResources(
                toolset=toolset,
                subagents=subagents,
                context=context,
                backend=backend,
                project_id=project_id,
            )
        except Exception:
            await backend.close()
            raise

    except Exception as e:
        print(f"[potpie] Warning: could not load KG tools/subagents: {e}", file=sys.stderr)
        return PotpieResources()


__all__ = ["PotpieResources", "build_potpie_resources"]

"""Code-graph resource setup for CLI agents.

Shared by interactive and non-interactive modes. Builds a
PotpieCapability from a single PotpieRuntime, with optional
git-based project auto-discovery.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_deep.capabilities.code_graph.potpie import PotpieCapability


async def build_kg_capability(
    project_id: str | None,
    user_id: str,
    root: Path | None = None,
    on_status: Any | None = None,
) -> PotpieCapability | None:
    """Build a PotpieCapability sharing one PotpieRuntime.

    When *project_id* is ``None`` and *root* is provided, auto-discovers
    the project from the git repo using the already-created runtime,
    avoiding a second PotpieRuntime initialization.

    Eagerly builds subagent toolsets so that ``cap.subagents`` is populated
    before ``create_cli_agent`` is called (subagents must be wired at agent
    construction time, not lazily in ``for_run``).

    The caller is responsible for closing ``result.runtime.close()`` in a
    finally block after the agent run completes.

    Args:
        project_id: Explicit project UUID, or None to auto-discover.
        user_id: User ID forwarded to ToolService for access control.
        root: Working directory root for git-based auto-discovery.
        on_status: Optional callable ``(message: str) -> None`` for status
            messages (e.g. auto-discovery notice, loaded notice).

    Returns:
        PotpieCapability on success, or None on failure (warning printed
        to stderr).
    """
    try:
        from pydantic_deep.capabilities.code_graph.potpie import PotpieCapability
        from pydantic_deep.toolsets.code_graph.potpie.context import PotpieContext
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

        runtime = PotpieRuntime(user_id=user_id)

        try:
            # Auto-discover project from git if not explicitly provided.
            resolved_by_discovery = False
            if not project_id and root is not None:
                from apps.cli.code_graph.potpie_discovery import parse_git_identity

                identity = parse_git_identity(root)
                if identity:
                    repo_name, branch = identity
                    for p in await runtime.list_projects():
                        if p["repo_name"] == repo_name and p["branch_name"] == branch:
                            project_id = p["id"]
                            resolved_by_discovery = True
                            break

            if not project_id:
                await runtime.close()
                return None

            context = PotpieContext(project_id=project_id, user_id=user_id)
            cap = PotpieCapability(
                runtime=runtime, project_id=project_id, context=context
            )

            if on_status:
                if resolved_by_discovery:
                    on_status(f"Auto-discovered KG project: {project_id}")
                else:
                    on_status(f"KG tools loaded for project {project_id}")

            # Build toolset and subagent configs here (async context) and inject
            # directly — no build methods on the capability class needed.
            from pydantic_deep.toolsets.code_graph.potpie.toolset import (
                KG_TOOL_NAMES,
                PotpieToolset,
            )
            from pydantic_deep.capabilities.code_graph.potpie import (
                _BLAST_RADIUS_INSTRUCTIONS,
                _BLAST_RADIUS_TOOL_NAMES,
                _QNA_INSTRUCTIONS,
                _QNA_TOOL_NAMES,
            )

            ts = await PotpieToolset.from_runtime(
                runtime=runtime, tool_names=KG_TOOL_NAMES, toolset_id="potpie-kg"
            )
            object.__setattr__(cap, "_toolset", ts)

            qna_ts = await PotpieToolset.from_runtime(
                runtime=runtime, tool_names=_QNA_TOOL_NAMES, toolset_id="potpie-qna"
            )
            blast_ts = await PotpieToolset.from_runtime(
                runtime=runtime, tool_names=_BLAST_RADIUS_TOOL_NAMES, toolset_id="potpie-blast-radius"
            )
            object.__setattr__(cap, "_subagents", [
                {
                    "name": "codebase_qna",
                    "description": (
                        "Answer questions about the codebase using the knowledge graph. "
                        "Use for: 'What does X do?', 'How is Y implemented?', "
                        "'Where is Z defined?', 'Which files import A?'"
                    ),
                    "instructions": _QNA_INSTRUCTIONS,
                    "toolsets": [qna_ts],
                    "include_filesystem": False,
                    "preferred_mode": "async",
                },
                {
                    "name": "blast_radius",
                    "description": (
                        "Analyse the blast radius of code changes — which functions, APIs, "
                        "and consumers are affected by changes in the current branch. "
                        "Use for: 'What is the impact of my changes?', "
                        "'Which tests might break?', 'What depends on X?'"
                    ),
                    "instructions": _BLAST_RADIUS_INSTRUCTIONS,
                    "toolsets": [blast_ts],
                    "include_filesystem": True,
                    "preferred_mode": "async",
                },
            ])

            return cap
        except Exception:
            await runtime.close()
            raise

    except Exception as e:
        print(f"[kg] Warning: could not load KG tools: {e}", file=sys.stderr)
        return None


__all__ = ["build_kg_capability"]

"""Code-graph resource setup for CLI agents.

Shared by interactive and non-interactive modes. Builds a
PotpieCapability from a single PotpieRuntime, with optional
git-based project auto-discovery.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pydantic_deep.capabilities.code_graph.potpie import PotpieCapability
    from pydantic_deep.capabilities.code_graph.simics_device import SimicsDeviceCapability


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



async def build_simics_dev_capability(
    project_id: str | None,
    user_id: str,
    root: Path | None = None,
    on_status: Any | None = None,
) -> "SimicsDeviceCapability | None":
    """Build a SimicsDeviceCapability sharing one PotpieRuntime.

    When *project_id* is ``None`` and *root* is provided, auto-discovers
    the project from the git repo, mirroring the logic in
    :func:`build_kg_capability`.

    The caller is responsible for closing ``result.runtime.close()`` in a
    finally block after the agent run completes.

    Args:
        project_id: Explicit project UUID, or None to auto-discover.
        user_id: User ID forwarded to ToolService for access control.
        root: Working directory root for git-based auto-discovery.
        on_status: Optional callable ``(message: str) -> None`` for status
            messages.

    Returns:
        SimicsDeviceCapability on success, or None on failure.
    """
    try:
        from pydantic_deep.capabilities.code_graph.simics_device import SimicsDeviceCapability
        from pydantic_deep.toolsets.code_graph.potpie.context import PotpieContext
        from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime
        from pydantic_deep.toolsets.code_graph.potpie.toolset import (
            SIMICS_TOOL_NAMES,
            PotpieToolset,
        )

        runtime = PotpieRuntime(user_id=user_id)

        try:
            resolved_by_discovery = False
            if not project_id and root is not None:
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
            cap = SimicsDeviceCapability(
                runtime=runtime, project_id=project_id, context=context
            )

            if on_status:
                if resolved_by_discovery:
                    on_status(f"Auto-discovered Simics device project: {project_id}")
                else:
                    on_status(f"Simics device tools loaded for project {project_id}")

            ts = await PotpieToolset.from_runtime(
                runtime=runtime, tool_names=SIMICS_TOOL_NAMES, toolset_id="simics-device"
            )
            object.__setattr__(cap, "_toolset", ts)

            return cap
        except Exception:
            await runtime.close()
            raise

    except Exception as e:
        print(f"[simics] Warning: could not load Simics device tools: {e}", file=sys.stderr)
        return None


def parse_git_identity(root: Path | None = None) -> tuple[str, str] | None:
    """Return ``(repo_name, branch)`` for the git repo at *root*, or ``None``.

    Pure git operations — no PotpieRuntime needed. Handles submodule
    scenarios by resolving the superproject for remote URL lookups.

    Args:
        root: Directory to inspect. Defaults to CWD.

    Returns:
        ``(repo_name, branch)`` tuple, or ``None`` if not a git repo or
        no remote origin is configured.
    """
    root = root or Path.cwd()
    git = shutil.which("git")
    if not git:
        logger.debug("parse_git_identity: git not found")
        return None

    def _run(args: list[str], cwd: Path = root) -> str | None:
        try:
            r = subprocess.run(
                args, capture_output=True, text=True, timeout=3, cwd=str(cwd), check=False
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None

    # Resolve git root; if inside a submodule use the superproject for remote URL
    git_root_str = _run([git, "rev-parse", "--show-toplevel"])
    git_root = Path(git_root_str) if git_root_str else root
    superproject_str = _run([git, "rev-parse", "--show-superproject-working-tree"])
    if superproject_str:
        git_root = Path(superproject_str)

    branch = _run([git, "rev-parse", "--abbrev-ref", "HEAD"])
    if not branch:
        logger.debug("parse_git_identity: could not determine branch")
        return None

    remote_url = _run([git, "remote", "get-url", "origin"], cwd=git_root)
    if not remote_url:
        logger.debug("parse_git_identity: no git remote 'origin'")
        return None

    # Strip trailing slash, then .git suffix with proper suffix removal (not rstrip
    # which strips individual characters and would corrupt names like "pytest").
    url = remote_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # Handles both https://host/org/repo and git@host:org/repo
    repo_name = url.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if not repo_name:
        logger.debug("parse_git_identity: could not parse repo name from %s", remote_url)
        return None

    logger.debug("parse_git_identity: repo=%s branch=%s", repo_name, branch)
    return repo_name, branch


__all__ = ["build_kg_capability", "build_simics_dev_capability", "parse_git_identity"]

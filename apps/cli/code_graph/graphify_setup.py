"""Code-graph resource setup for CLI agents (Graphify provider).

Shared by interactive and non-interactive modes. Builds a
GraphifyCapability from a GraphifyRuntime pointed at the given repository
path (the directory that contains ``graphify-out/graph.json``).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_deep.capabilities.code_graph.graphify import GraphifyCapability


async def build_graphify_capability(
    repo_path: str | None,
    root: Path | None = None,
    graph_path: str | None = None,
    on_status: Any | None = None,
) -> GraphifyCapability | None:
    """Build a GraphifyCapability for the given repository.

    Uses *repo_path* directly when provided. Falls back to *root* (typically
    the CLI working directory) when *repo_path* is ``None``.

    The caller is responsible for calling ``cap.runtime.close()`` in a
    finally block after the agent run completes.

    Args:
        repo_path: Explicit path to an indexed repository, or None to use root.
        root: Working directory root (used when repo_path is None).
        graph_path: Optional explicit path to a ``graph.json`` file.
        on_status: Optional callable ``(message: str) -> None`` for status
            messages.

    Returns:
        GraphifyCapability on success, or None when no repository path is
        available, no graph exists, or the import fails (warning to stderr).
    """
    try:
        from pydantic_deep.capabilities.code_graph.graphify import GraphifyCapability
        from pydantic_deep.toolsets.code_graph.graphify.context import GraphifyContext
        from pydantic_deep.toolsets.code_graph.graphify.runtime import GraphifyRuntime
        from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

        effective_repo = repo_path or (str(root.resolve()) if root is not None else None)
        if not effective_repo and not graph_path:
            return None

        runtime = GraphifyRuntime(repo_path=effective_repo, graph_path=graph_path)
        if not runtime.resolve_graph_path().exists():
            print(
                "[graphify] Warning: no graphify-out/graph.json found at "
                f"{runtime.resolve_graph_path()}. Run `graphify .` to build it.",
                file=sys.stderr,
            )
            return None

        context = GraphifyContext(repo_path=effective_repo or "", graph_path=graph_path)
        cap = GraphifyCapability(runtime=runtime, context=context)

        toolset = GraphifyToolset(runtime=runtime, repo_path=effective_repo)
        object.__setattr__(cap, "_toolset", toolset)

        if on_status:
            on_status(f"Graphify code graph loaded from {runtime.resolve_graph_path()}")

        return cap

    except Exception as e:
        print(f"[graphify] Warning: could not load Graphify tools: {e}", file=sys.stderr)
        return None


__all__ = ["build_graphify_capability"]

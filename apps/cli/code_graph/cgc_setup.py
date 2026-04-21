"""Code-graph resource setup for CLI agents (CGC provider).

Shared by interactive and non-interactive modes. Builds a
CGCCapability from a CGCRuntime pointed at the given repository path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_deep.capabilities.code_graph.cgc import CGCCapability


async def build_cgc_capability(
    repo_path: str | None,
    root: Path | None = None,
    on_status: Any | None = None,
) -> CGCCapability | None:
    """Build a CGCCapability for the given repository.

    Uses *repo_path* directly when provided. Falls back to *root* (typically
    the CLI working directory) when *repo_path* is ``None``.

    The caller is responsible for calling ``cap.runtime.close()`` in a
    finally block after the agent run completes.

    Args:
        repo_path: Explicit path to an indexed repository, or None to use root.
        root: Working directory root (used when repo_path is None).
        on_status: Optional callable ``(message: str) -> None`` for status
            messages.

    Returns:
        CGCCapability on success, or None when no repository path is available
        or the import fails (warning printed to stderr).
    """
    try:
        from pydantic_deep.capabilities.code_graph.cgc import CGCCapability
        from pydantic_deep.toolsets.code_graph.cgc.context import CGCContext
        from pydantic_deep.toolsets.code_graph.cgc.runtime import CGCRuntime
        from pydantic_deep.toolsets.code_graph.cgc.toolset import CGCToolset

        effective_repo = repo_path or (str(root.resolve()) if root is not None else None)
        if not effective_repo:
            return None

        runtime = CGCRuntime(repo_path=effective_repo)
        context = CGCContext(repo_path=effective_repo)
        cap = CGCCapability(runtime=runtime, context=context)

        toolset = CGCToolset(runtime=runtime, repo_path=effective_repo)
        object.__setattr__(cap, "_toolset", toolset)

        if on_status:
            on_status(f"CGC code graph loaded for {effective_repo}")

        return cap

    except Exception as e:
        print(f"[cgc] Warning: could not load CGC tools: {e}", file=sys.stderr)
        return None


__all__ = ["build_cgc_capability"]

"""Code-graph integration package for pydantic-deep.

Provides two providers:
  - Potpie (the original): CodeGraphRuntime, PotpieContext, CodeGraphToolset
  - CodeGraphContext (CGC): CGCRuntime, CGCContext, CGCToolset

Usage::

    # Potpie provider
    from pydantic_deep.toolsets.code_graph import CodeGraphRuntime, CodeGraphToolset
    runtime = CodeGraphRuntime(user_id="defaultuser")

    # CGC provider
    from pydantic_deep.toolsets.code_graph import CGCRuntime, CGCToolset
    runtime = CGCRuntime(repo_path="/path/to/repo")
"""

from __future__ import annotations

from pydantic_deep.toolsets.code_graph.cgc_context import CGCContext
from pydantic_deep.toolsets.code_graph.cgc_runtime import CGCRuntime
from pydantic_deep.toolsets.code_graph.cgc_toolset import CGCToolset
from pydantic_deep.toolsets.code_graph.context import PotpieContext
from pydantic_deep.toolsets.code_graph.runtime import CodeGraphRuntime
from pydantic_deep.toolsets.code_graph.toolset import KG_TOOL_NAMES, CodeGraphToolset


def make_runtime(user_id: str | None = None) -> CodeGraphRuntime:
    """Return a new CodeGraphRuntime (Potpie) instance."""
    return CodeGraphRuntime(user_id=user_id)


def make_cgc_runtime(repo_path: str | None = None) -> CGCRuntime:
    """Return a new CGCRuntime (CodeGraphContext) instance."""
    return CGCRuntime(repo_path=repo_path)


__all__ = [
    "CodeGraphRuntime",
    "PotpieContext",
    "CodeGraphToolset",
    "KG_TOOL_NAMES",
    "make_runtime",
    "CGCRuntime",
    "CGCContext",
    "CGCToolset",
    "make_cgc_runtime",
]

"""Code-graph integration package for pydantic-deep.

Provides two providers:
  - Potpie (the original): PotpieRuntime, PotpieContext, PotpieToolset
  - CodeGraphContext (CGC): CGCRuntime, CGCContext, CGCToolset

Usage::

    # Potpie provider
    from pydantic_deep.toolsets.code_graph import PotpieRuntime, PotpieToolset
    runtime = PotpieRuntime(user_id="defaultuser")

    # CGC provider
    from pydantic_deep.toolsets.code_graph import CGCRuntime, CGCToolset
    runtime = CGCRuntime(repo_path="/path/to/repo")
"""

from __future__ import annotations

from pydantic_deep.toolsets.code_graph.cgc.context import CGCContext
from pydantic_deep.toolsets.code_graph.cgc.runtime import CGCRuntime
from pydantic_deep.toolsets.code_graph.cgc.toolset import CGCToolset
from pydantic_deep.toolsets.code_graph.potpie.context import PotpieContext
from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime
from pydantic_deep.toolsets.code_graph.potpie.toolset import KG_TOOL_NAMES, PotpieToolset


def make_runtime(user_id: str | None = None) -> PotpieRuntime:
    """Return a new PotpieRuntime (Potpie) instance."""
    return PotpieRuntime(user_id=user_id)


def make_cgc_runtime(repo_path: str | None = None) -> CGCRuntime:
    """Return a new CGCRuntime (CodeGraphContext) instance."""
    return CGCRuntime(repo_path=repo_path)


from pydantic_deep.providers.code_graph import CGCProvider, CodeGraphProvider, make_provider  # noqa: E402

__all__ = [
    "PotpieRuntime",
    "PotpieContext",
    "PotpieToolset",
    "KG_TOOL_NAMES",
    "make_runtime",
    "CGCRuntime",
    "CGCContext",
    "CGCToolset",
    "make_cgc_runtime",
    "CodeGraphProvider",
    "CGCProvider",
    "make_provider",
]

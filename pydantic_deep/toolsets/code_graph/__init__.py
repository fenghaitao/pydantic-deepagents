"""Code-graph integration package for pydantic-deep.

Provides:
  - CodeGraphRuntime — direct PotpieRuntime implementation (runtime.py)
  - CodeGraphToolset — pydantic-ai FunctionToolset (toolset.py)
  - make_runtime() — returns a CodeGraphRuntime instance

Usage::

    from pydantic_deep.toolsets.code_graph import CodeGraphRuntime, CodeGraphToolset

    runtime = CodeGraphRuntime(user_id="defaultuser")
    toolset = CodeGraphToolset(backend=runtime, project_id="<uuid>")
"""

from __future__ import annotations

from pydantic_deep.toolsets.code_graph.context import PotpieContext
from pydantic_deep.toolsets.code_graph.runtime import CodeGraphRuntime
from pydantic_deep.toolsets.code_graph.toolset import KG_TOOL_NAMES, CodeGraphToolset


def make_runtime(user_id: str | None = None) -> CodeGraphRuntime:
    """Return a new CodeGraphRuntime instance."""
    return CodeGraphRuntime(user_id=user_id)


__all__ = [
    "CodeGraphRuntime",
    "PotpieContext",
    "CodeGraphToolset",
    "KG_TOOL_NAMES",
    "make_runtime",
]

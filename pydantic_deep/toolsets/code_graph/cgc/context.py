"""CGCContext — runtime context for CodeGraphContext code-graph integration.

Carried in ``DeepAgentDeps.cgc_context`` so tools can access repository
identity without polluting the core deps namespace.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CGCContext:
    """Runtime context for the CodeGraphContext (CGC) code-graph integration.

    Attributes:
        repo_path: Absolute path to the indexed repository. Injected into
            tool calls so the LLM never needs to supply it explicitly.
    """

    repo_path: str


__all__ = ["CGCContext"]

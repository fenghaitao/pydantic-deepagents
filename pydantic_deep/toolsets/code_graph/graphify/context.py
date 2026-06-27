"""GraphifyContext — runtime context for Graphify code-graph integration.

Carried in ``DeepAgentDeps.graphify_context`` so tools can access the graph
location without polluting the core deps namespace.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GraphifyContext:
    """Runtime context for the Graphify code-graph integration.

    Attributes:
        repo_path: Absolute path to the indexed repository (the directory that
            contains the ``graphify-out/`` folder). Injected into the system
            prompt so the LLM knows which codebase it is operating on.
        graph_path: Optional explicit path to the ``graph.json`` file. When
            omitted, it defaults to ``{repo_path}/graphify-out/graph.json``.
    """

    repo_path: str
    graph_path: str | None = None


__all__ = ["GraphifyContext"]

"""PotpieContext — runtime context for potpie code-graph integration.

Carried in ``DeepAgentDeps.potpie`` so tools can access project identity
and parsing state without polluting the core deps namespace.

Usage::

    from apps.potpie.context import PotpieContext

    deps = DeepAgentDeps(
        backend=...,
        potpie=PotpieContext(project_id="<uuid>", user_id="alice"),
    )

    # Inside a tool:
    ctx.deps.potpie.project_id
    ctx.deps.potpie.parsing_status
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PotpieContext:
    """Runtime context for the potpie code-graph integration.

    Attributes:
        project_id: Active potpie project UUID. Injected into tool calls
            so the LLM never needs to supply it explicitly.
        user_id: User ID forwarded to ToolService for per-user access
            control.
        parsing_status: Current parsing status of the active project
            (e.g. ``"READY"``, ``"INFERRING"``, ``"PARSING"``). Used to
            exclude embedding-dependent tools while the graph is still
            being built. ``None`` means unknown / not yet queried.
    """

    project_id: str
    user_id: str
    parsing_status: str | None = None


__all__ = ["PotpieContext"]

"""PotpieContext — runtime context for potpie code-graph integration.

Carried in ``DeepAgentDeps.potpie`` so tools can access project identity
and parsing state without polluting the core deps namespace.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PotpieContext:
    """Runtime context for the potpie code-graph integration.

    Attributes:
        project_id: Active potpie project UUID. Injected into tool calls
            so the LLM never needs to supply it explicitly.
        user_id: User ID forwarded to ToolService for per-user access control.
        parsing_status: Current parsing status of the active project
            (e.g. ``"READY"``, ``"INFERRING"``, ``"PARSING"``). ``None`` means unknown.
    """

    project_id: str
    user_id: str
    parsing_status: str | None = None


__all__ = ["PotpieContext"]

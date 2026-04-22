"""WebDeepDeps — DeepAgentDeps subclass with AG-UI state sync.

Inherits from DeepAgentDeps so all CLI toolsets work unchanged.
Adds a ``state`` field implementing pydantic-ai's StateHandler protocol,
enabling bidirectional state sync between the Python agent and the
CopilotKit frontend via the AG-UI protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_deep.deps import DeepAgentDeps

from models import PotpieState


@dataclass
class WebDeepDeps(DeepAgentDeps):
    """CLI's DeepAgentDeps + AG-UI state sync for CopilotKit.

    Satisfies pydantic-ai's StateHandler protocol:
    - Is a dataclass (__dataclass_fields__)
    - Has a ``state`` field (get/set)

    All CLI toolsets see this as DeepAgentDeps (inheritance).
    ``to_ag_ui()`` / ``handle_ag_ui_request()`` see it as StateHandler
    and sync ``state`` with the CopilotKit frontend.
    """

    state: PotpieState = field(default_factory=PotpieState)

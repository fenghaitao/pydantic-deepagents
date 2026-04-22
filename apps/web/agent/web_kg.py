"""WebPotpieCapability — per-request KG context from frontend state.

Subclasses PotpieCapability to read ``project_id`` from the
AG-UI state (``deps.state.project_id``) instead of a fixed value,
so each web request automatically uses the correct project.

CLI's PotpieCapability is NOT modified.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext

from pydantic_deep.capabilities.code_graph import PotpieCapability
from pydantic_deep.toolsets.code_graph.potpie.context import PotpieContext


_DEFAULT_USER = os.getenv("POTPIE_USER_ID", "defaultuser")


@dataclass
class WebPotpieCapability(PotpieCapability):
    """PotpieCapability that wires kg_context from frontend state.

    On each agent run, ``before_run()`` reads ``deps.state.project_id``
    (set by CopilotKit) and creates a fresh PotpieContext, so the
    PotpieToolset's tools automatically query the right project.
    """

    async def before_run(self, ctx: RunContext[Any]) -> None:
        state = getattr(ctx.deps, "state", None)
        project_id = getattr(state, "project_id", None) if state else None

        if project_id:
            ctx.deps.kg_context = PotpieContext(
                project_id=project_id,
                user_id=_DEFAULT_USER,
            )
        elif self.context:
            ctx.deps.kg_context = self.context

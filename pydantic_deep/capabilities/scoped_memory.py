"""Scoped, typed agent memory capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import Model
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai_backends import BackendProtocol

from pydantic_deep.toolsets.scoped_memory.toolset import ScopedMemoryToolset


@dataclass
class ScopedMemoryCapability(AbstractCapability[Any]):
    """Persistent, scoped, typed memory. User scope → dedicated backend; project scope →
    the run's backend. Provides MemorySave/Search/Delete/List and injects both indexes."""

    agent_name: str = "main"
    user_backend: BackendProtocol | None = None
    project_base: str = ".pydantic-deep/memory"
    staleness_days: int = 7
    ai_model: Model | str | None = None
    _toolset: ScopedMemoryToolset | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._toolset = ScopedMemoryToolset(
            agent_name=self.agent_name,
            user_backend=self.user_backend,
            project_base=self.project_base,
            staleness_days=self.staleness_days,
            ai_model=self.ai_model,
        )

    def get_toolset(self) -> AbstractToolset[Any] | None:
        return self._toolset

    def get_instructions(self) -> Any:
        toolset = self._toolset

        async def _instructions(ctx: RunContext[Any]) -> str | None:
            if toolset is None or not hasattr(ctx.deps, "backend"):
                return None
            parts = await toolset.get_instructions(ctx)
            return "\n\n".join(p.content for p in parts) if parts else None

        return _instructions

"""PotpieKGCapability — exposes potpie KG tools via pydantic-ai AbstractCapability.

Instead of passing the KG toolset as a raw toolset, this wraps it as a
capability so it composes cleanly with Agent(capabilities=[...]).

Usage::

    from pydantic_deep.toolsets.code_graph import make_backend
    from apps.potpie.capability import PotpieKGCapability

    backend = make_backend(config)
    cap = await PotpieKGCapability.create(backend, project_id, user_id)
    agent = Agent(model=..., capabilities=[cap])
    # cleanup after run:
    await cap.aclose()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset

if TYPE_CHECKING:
    from pydantic_deep.toolsets.code_graph.backend import PotpieBackend


@dataclass
class PotpieKGCapability(AbstractCapability[Any]):
    """Capability that registers potpie KG tools with a pydantic-ai agent.

    Wraps ``create_potpie_toolset()`` and exposes the resulting
    FunctionToolset via ``get_toolset()``, so it can be passed as a
    capability rather than a raw toolset.

    Construct via ``PotpieKGCapability.create()`` which is async and
    handles tool fetching from the backend.

    Args:
        _toolset: The FunctionToolset produced by create_potpie_toolset().
        _backend: The PotpieBackend used to fetch tools (held for aclose()).
    """

    _toolset: Any = field(default=None, init=False, repr=False)
    _backend: Any = field(default=None, init=False, repr=False)

    @classmethod
    async def create(
        cls,
        backend: PotpieBackend,
        project_id: str,
        user_id: str,
        tool_names: list[str] | None = None,
        toolset_id: str = "potpie-kg",
        exclude_embedding_tools: bool = False,
    ) -> PotpieKGCapability:
        """Async factory: fetch tools from backend and build the capability.

        Args:
            backend: An initialised PotpieBackend (RuntimeBackend for full
                tool registry access; RestBackend raises NotImplementedError).
            project_id: Registered project ID — injected into tool calls via
                ctx.deps.potpie_project_id.
            user_id: User ID forwarded to ToolService for access control.
                Only used by RuntimeBackend; ignored by RestBackend.
            tool_names: Tool names to retrieve. Defaults to KG_TOOL_NAMES.
            toolset_id: FunctionToolset identifier.
            exclude_embedding_tools: Skip embedding-dependent tools (use
                when project is in INFERRING state).

        Returns:
            A ready-to-use PotpieKGCapability instance.
        """
        from apps.potpie.toolset import create_potpie_toolset

        cap = cls()
        cap._backend = backend
        cap._toolset = await create_potpie_toolset(
            backend=backend,
            tool_names=tool_names,
            toolset_id=toolset_id,
            exclude_embedding_tools=exclude_embedding_tools,
        )
        return cap

    def get_toolset(self) -> AbstractToolset[Any] | None:
        return self._toolset

    async def aclose(self) -> None:
        """Close the backend if it supports async cleanup."""
        if self._backend is not None and hasattr(self._backend, "close"):
            await self._backend.close()
            self._backend = None

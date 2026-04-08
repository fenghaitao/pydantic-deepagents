"""PotpieKGCapability — exposes potpie KG tools via pydantic-ai AbstractCapability.

Instead of passing the KG toolset as a raw toolset, this wraps it as a
capability so it composes cleanly with Agent(capabilities=[...]).

Usage::

    from apps.potpie.capability import PotpieKGCapability

    cap = await PotpieKGCapability.create(runtime, project_id, user_id)
    agent = Agent(model=..., capabilities=[cap])
    # cleanup after run:
    cap.close()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset

if TYPE_CHECKING:
    from pydantic_ai.toolsets import FunctionToolset
    from potpie.runtime import PotpieRuntime


@dataclass
class PotpieKGCapability(AbstractCapability[Any]):
    """Capability that registers potpie KG tools with a pydantic-ai agent.

    Wraps ``create_potpie_toolset()`` and exposes the resulting
    FunctionToolset via ``get_toolset()``, so it can be passed as a
    capability rather than a raw toolset.

    Prefer constructing via ``PotpieKGCapability.create()`` which is async
    and handles runtime initialisation.

    Args:
        _toolset: The FunctionToolset produced by create_potpie_toolset().
    """

    _toolset: Any = field(default=None, init=False, repr=False)
    _db_session: Any = field(default=None, init=False, repr=False)

    @classmethod
    async def create(
        cls,
        runtime: PotpieRuntime,
        project_id: str,
        user_id: str,
        toolset_id: str = "potpie-kg",
    ) -> PotpieKGCapability:
        """Async factory: initialise runtime and build the capability.

        Args:
            runtime: An already-initialised PotpieRuntime instance.
            project_id: Registered project ID.
            user_id: User ID for ToolService access control.
            toolset_id: FunctionToolset identifier.

        Returns:
            A ready-to-use PotpieKGCapability instance.
        """
        from apps.potpie.toolset import create_potpie_toolset

        cap = cls()
        toolset = create_potpie_toolset(runtime, project_id, user_id, toolset_id)
        cap._toolset = toolset
        cap._db_session = getattr(toolset, "_db_session", None)
        return cap

    def get_toolset(self) -> AbstractToolset[Any] | None:
        return self._toolset

    def close(self) -> None:
        """Release the DB session opened by create_potpie_toolset."""
        from apps.potpie.toolset import _close_session

        if self._toolset is not None:
            _close_session(self._toolset)
            self._db_session = None

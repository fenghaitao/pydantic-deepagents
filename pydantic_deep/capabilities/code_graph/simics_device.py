"""SimicsDeviceCapability — pydantic-ai capability for Simics DML device analysis.

Encapsulates the Simics-specific register, capability and interface analysis tools
(``analyze_register_side_effect``, ``analyze_capability``, ``list_capability``,
``analyze_interface``, ``list_simics_device_feature``) behind the standard
AbstractCapability interface.

Can be used standalone (without a full PotpieCapability) when only Simics
device analysis is needed, or alongside PotpieCapability for full code-graph
support.

Usage::

    from pydantic_deep.capabilities.code_graph.simics_device import SimicsDeviceCapability
    from pydantic_deep.toolsets.code_graph.potpie.context import PotpieContext
    from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

    runtime = PotpieRuntime(user_id="user1")
    context = PotpieContext(project_id="abc-123", user_id="user1")
    cap = SimicsDeviceCapability(runtime=runtime, project_id="abc-123", context=context)

    # Eagerly build toolset (required before create_deep_agent):
    from pydantic_deep.toolsets.code_graph.potpie.toolset import PotpieToolset, SIMICS_TOOL_NAMES
    ts = await PotpieToolset.from_runtime(runtime=runtime, tool_names=SIMICS_TOOL_NAMES, toolset_id="simics-device")
    object.__setattr__(cap, "_toolset", ts)

    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        extra_capabilities=[cap],
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from pydantic_deep.toolsets.code_graph.potpie.context import PotpieContext
from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime


@dataclass
class SimicsDeviceCapability(AbstractCapability[Any]):
    """Capability exposing Simics DML device register and capability analysis tools.

    Wraps the Simics-specific tools from SIMICS_TOOL_NAMES:
      - ``analyze_register_side_effect``
      - ``analyze_capability``
      - ``list_capability``
      - ``analyze_interface``
      - ``list_simics_device_feature``

    Injects ``kg_context`` into deps via ``before_run()`` so that the
    underlying PotpieToolset functions can read the project_id without
    the agent needing to supply it.

    Args:
        runtime: Initialised PotpieRuntime.
        project_id: Default project UUID (optional).
        context: PotpieContext for the current session (optional).
    """

    runtime: PotpieRuntime
    project_id: str | None = None
    context: PotpieContext | None = None
    _toolset: FunctionToolset[Any] | None = field(default=None, init=False, repr=False)

    async def before_run(self, ctx: RunContext[Any]) -> None:
        """Inject kg_context into deps before each run.

        Sets ``ctx.deps.kg_context`` to ``self.context`` so that
        the underlying tool functions can read the project_id.

        Args:
            ctx: The current run context.
        """
        ctx.deps.kg_context = self.context

    def get_toolset(self) -> AbstractToolset[Any] | None:
        """Return the built toolset, or None if not yet constructed."""
        return self._toolset

    def get_instructions(self) -> Callable[[RunContext[Any]], Any]:
        """Return an async callable that produces Simics device analysis guidance.

        Returns:
            An async callable accepting RunContext and returning a str or None.
        """
        context = self.context

        async def _instructions(ctx: RunContext[Any]) -> str | None:
            kg_context = getattr(ctx.deps, "kg_context", None) or context
            project_id = getattr(kg_context, "project_id", None) if kg_context else None

            if project_id:
                return (
                    "## Simics Device Analysis\n\n"
                    f"Default project ID: `{project_id}`\n\n"
                    "You have access to Simics DML device analysis tools:\n"
                    "- `analyze_register_side_effect`: analyze the simulated hardware behaviour "
                    "of every register in a DML device (write_effect, read_effect, keywords).\n"
                    "- `list_simics_device_feature`: list analysis results for a device by feature "
                    "type: \"register\", \"event\", \"fsm\", \"interface\", \"keyword\", or \"all\" "
                    "(triggers the relevant analysis pipeline automatically if needed).\n"
                    "- `analyze_capability`: generate structured hardware capability descriptions "
                    "from register keyword analysis.\n"
                    "- `list_capability`: list capability descriptions for a device "
                    "(generates them automatically if not yet stored).\n"
                    "- `analyze_interface`: analyze all PORT (input) and CONNECT (output) interfaces "
                    "of a DML device, producing feature descriptions and hardware keywords for each.\n\n"
                    "Workflow: run `analyze_register_side_effect` first, then "
                    "`analyze_capability` / `list_capability` for high-level hardware summaries. "
                    "Use `list_simics_device_feature` to retrieve register, FSM, event, or interface results."
                )
            return (
                "## Simics Device Analysis\n\n"
                "You have access to Simics DML device analysis tools "
                "(`analyze_register_side_effect`, `list_simics_device_feature`, "
                "`analyze_capability`, `list_capability`, `analyze_interface`). "
                "Use `list_code_projects` to discover available project IDs first."
            )

        return _instructions


__all__ = ["SimicsDeviceCapability"]

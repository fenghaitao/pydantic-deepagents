"""GraphifyCapability — pydantic-ai capability for Graphify integration.

Encapsulates all Graphify code-graph concerns (toolset, runtime context)
behind the standard AbstractCapability interface, following the same pattern
as :class:`CGCCapability` and :class:`PotpieCapability`.

Usage::

    from pydantic_deep.capabilities.code_graph.graphify import GraphifyCapability
    from pydantic_deep.toolsets.code_graph.graphify.context import GraphifyContext
    from pydantic_deep.toolsets.code_graph.graphify.runtime import GraphifyRuntime
    from pydantic_deep.toolsets.code_graph.graphify.toolset import GraphifyToolset

    runtime = GraphifyRuntime(repo_path="/path/to/repo")
    context = GraphifyContext(repo_path="/path/to/repo")
    cap = GraphifyCapability(runtime=runtime, context=context)

    # Eager toolset construction (required before create_deep_agent):
    toolset = GraphifyToolset(runtime=runtime, repo_path="/path/to/repo")
    object.__setattr__(cap, "_toolset", toolset)

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

from pydantic_deep.toolsets.code_graph.graphify.context import GraphifyContext
from pydantic_deep.toolsets.code_graph.graphify.runtime import GraphifyRuntime
from pydantic_deep.toolsets.code_graph.graphify.toolset import _format_instructions


@dataclass
class GraphifyCapability(AbstractCapability[Any]):
    """Capability encapsulating Graphify code-graph concerns.

    Builds the GraphifyToolset eagerly (via
    ``apps.cli.code_graph.graphify_setup.build_graphify_capability``), injects
    ``graphify_context`` into deps via ``before_run()``, and exposes the
    toolset via ``get_toolset()``.

    Args:
        runtime: Initialised GraphifyRuntime.
        context: GraphifyContext for the current session (optional).
    """

    runtime: GraphifyRuntime
    context: GraphifyContext | None = None
    _toolset: FunctionToolset[Any] | None = field(default=None, init=False, repr=False)

    async def before_run(self, ctx: RunContext[Any]) -> None:
        """Inject graphify_context into deps before each run.

        Args:
            ctx: The current run context.
        """
        ctx.deps.graphify_context = self.context

    def get_toolset(self) -> AbstractToolset[Any] | None:
        """Return the built toolset, or None if not yet constructed."""
        return self._toolset

    def get_instructions(self) -> Callable[[RunContext[Any]], Any]:
        """Return an async callable that produces Graphify usage guidance.

        Reads ``ctx.deps.graphify_context`` to include repository-specific
        information in the guidance string.
        """
        context = self.context

        async def _instructions(ctx: RunContext[Any]) -> str | None:
            graphify_context = getattr(ctx.deps, "graphify_context", None) or context
            repo_path = (
                getattr(graphify_context, "repo_path", None)
                if graphify_context
                else None
            )
            return _format_instructions(repo_path)

        return _instructions


__all__ = ["GraphifyCapability"]

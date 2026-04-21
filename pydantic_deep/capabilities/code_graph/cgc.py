"""CGCCapability — pydantic-ai capability for CodeGraphContext integration.

Encapsulates all CGC code-graph concerns (toolset, runtime context)
behind the standard AbstractCapability interface, following the same pattern
as PotpieCapability.

Usage::

    from pydantic_deep.capabilities.code_graph.cgc import CGCCapability
    from pydantic_deep.toolsets.code_graph.cgc.context import CGCContext
    from pydantic_deep.toolsets.code_graph.cgc.runtime import CGCRuntime
    from pydantic_deep.toolsets.code_graph.cgc.toolset import CGCToolset

    runtime = CGCRuntime(repo_path="/path/to/repo")
    context = CGCContext(repo_path="/path/to/repo")
    cap = CGCCapability(runtime=runtime, context=context)

    # Eager toolset construction (required before create_deep_agent):
    toolset = CGCToolset(runtime=runtime, repo_path="/path/to/repo")
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

from pydantic_deep.toolsets.code_graph.cgc.context import CGCContext
from pydantic_deep.toolsets.code_graph.cgc.runtime import CGCRuntime


@dataclass
class CGCCapability(AbstractCapability[Any]):
    """Capability encapsulating CodeGraphContext (CGC) code-graph concerns.

    Builds the CGCToolset eagerly (via ``apps.cli.cgc_setup.build_cgc_capability``),
    injects ``cgc_context`` into deps via ``before_run()``, and exposes the
    toolset via ``get_toolset()``.

    Args:
        runtime: Initialised CGCRuntime.
        context: CGCContext for the current session (optional).
    """

    runtime: CGCRuntime
    context: CGCContext | None = None
    _toolset: FunctionToolset[Any] | None = field(default=None, init=False, repr=False)

    async def before_run(self, ctx: RunContext[Any]) -> None:
        """Inject cgc_context into deps before each run.

        Sets ``ctx.deps.cgc_context`` to ``self.context`` so that
        CGCToolset tool functions can read the repository path.

        Args:
            ctx: The current run context.
        """
        ctx.deps.cgc_context = self.context

    def get_toolset(self) -> AbstractToolset[Any] | None:
        """Return the built toolset, or None if not yet constructed."""
        return self._toolset

    def get_instructions(self) -> Callable[[RunContext[Any]], Any]:
        """Return an async callable that produces CGC usage guidance.

        Reads ``ctx.deps.cgc_context`` to include repository-specific
        information in the guidance string.

        Returns:
            An async callable accepting RunContext and returning a str or None.
        """
        context = self.context

        async def _instructions(ctx: RunContext[Any]) -> str | None:
            cgc_context = getattr(ctx.deps, "cgc_context", None) or context
            repo_path = getattr(cgc_context, "repo_path", None) if cgc_context else None

            if repo_path:
                return (
                    f"## Code Graph (CGC)\n\n"
                    f"Default repository: `{repo_path}`\n\n"
                    "You have access to code-graph tools (`find_code`, "
                    "`analyze_code_relationships`, `execute_cypher_query`, "
                    "`list_code_projects`) to explore and understand the indexed codebase.\n"
                    "Use `find_code` for keyword searches. "
                    "Use `analyze_code_relationships` for structural queries "
                    "(call graphs, imports, class hierarchy). "
                    "Use `execute_cypher_query` for advanced graph queries."
                )
            return (
                "## Code Graph (CGC)\n\n"
                "You have access to code-graph tools. Use `list_code_projects` "
                "to discover indexed repositories, then use `find_code` and "
                "`analyze_code_relationships` to explore the codebase."
            )

        return _instructions


__all__ = ["CGCCapability"]

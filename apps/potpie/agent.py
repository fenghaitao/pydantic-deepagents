"""Potpie agent factory for pydantic-deep agents.

Composes create_potpie_toolset with create_deep_agent, injecting the KG
toolset into both the main agent and all spawned subagents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai_backends import StateBackend

from pydantic_deep.agent import DEFAULT_MODEL, create_deep_agent
from pydantic_deep.deps import DeepAgentDeps

from apps.potpie.toolset import create_potpie_toolset

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from potpie.runtime import PotpieRuntime


def create_potpie_agent(
    runtime: PotpieRuntime,
    project_id: str,
    user_id: str,
    model: str | None = None,
    **kwargs: Any,
) -> tuple[Agent[DeepAgentDeps, str], DeepAgentDeps]:
    """Create a fully-configured pydantic-deep agent with potpie KG tools.

    The KG toolset is injected into both the main agent and all spawned
    subagents so that every delegation step has access to the knowledge graph.

    Args:
        runtime: Initialised PotpieRuntime instance.
        project_id: Registered project ID passed to the KG toolset.
        user_id: User ID forwarded to ToolService for access control.
        model: Model string (e.g. "anthropic:claude-opus-4-6"). Falls back
            to DEFAULT_MODEL when None.
        **kwargs: Additional keyword arguments forwarded to create_deep_agent,
            allowing callers to override instructions, model_settings, etc.

    Returns:
        Tuple of (agent, deps) ready for agent.run() or interactive use.
    """
    kg_toolset = create_potpie_toolset(runtime, project_id, user_id)

    # Resolve litellm: prefix the same way the CLI does
    effective_model = model or DEFAULT_MODEL
    if isinstance(effective_model, str) and effective_model.startswith("litellm:"):
        from pydantic_deep.litellm import infer_litellm_model
        effective_model = infer_litellm_model(effective_model)

    # WebSearchTool only works with OpenAIResponsesModel, not LiteLLM
    _is_litellm = hasattr(effective_model, "system") and getattr(effective_model, "system", None) == "litellm"

    agent = create_deep_agent(
        model=effective_model,
        toolsets=[kg_toolset],
        subagent_extra_toolsets=[kg_toolset],
        include_subagents=True,
        include_teams=True,
        include_memory=True,
        context_manager=True,
        eviction_token_limit=20_000,
        web_search=False if _is_litellm else kwargs.pop("web_search", True),
        web_fetch=False if _is_litellm else kwargs.pop("web_fetch", True),
        **kwargs,
    )

    deps = DeepAgentDeps(backend=StateBackend())

    return agent, deps


__all__ = ["create_potpie_agent"]

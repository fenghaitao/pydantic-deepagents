"""Tests for pydantic_deep.litellm helpers.

Offline tests exercise wiring without HTTP. A live round-trip runs when you opt in:

- ``LITELLM_API_BASE`` is set (typical self-hosted LiteLLM proxy), **or**
- ``PYDANTIC_DEEP_LITELLM_LIVE=1`` (e.g. GitHub Copilot via LiteLLM **OAuth2** with no custom base).

Configure auth per `LiteLLM’s provider docs <https://docs.litellm.ai/>`_ (OAuth env vars, etc.).

Optional:

- ``PYDANTIC_DEEP_TEST_LITELLM_MODEL``: full pydantic-ai model id, default
  ``litellm:github_copilot/gpt-4o``.
- ``LITELLM_API_KEY``: forwarded to the OpenAI-compatible client when set.
"""

from __future__ import annotations

import os

import pytest
from pydantic_ai.models.test import TestModel

from pydantic_deep import create_deep_agent, create_default_deps
from pydantic_deep.litellm import (
    DEFAULT_GITHUB_COPILOT_LITELLM_MODEL,
    LiteLLMModel,
    github_copilot_litellm_model,
    infer_litellm_model,
)


def _litellm_live_enabled() -> bool:
    return bool(os.environ.get("LITELLM_API_BASE")) or os.environ.get(
        "PYDANTIC_DEEP_LITELLM_LIVE",
        "",
    ) == "1"


def test_infer_litellm_model_from_prefixed_name() -> None:
    m = infer_litellm_model(
        "litellm:github_copilot/gpt-4o",
    )
    assert isinstance(m, LiteLLMModel)
    assert m.model_name == "github_copilot/gpt-4o"


def test_infer_litellm_model_from_plain_name() -> None:
    m = infer_litellm_model("github_copilot/gpt-4o")
    assert isinstance(m, LiteLLMModel)
    assert m.model_name == "github_copilot/gpt-4o"


def test_infer_litellm_model_adds_copilot_headers() -> None:
    m = infer_litellm_model("github_copilot/gpt-4o")
    assert isinstance(m, LiteLLMModel)
    assert m._extra_headers["Editor-Version"] == "vscode/1.85.1"  # pyright: ignore[reportPrivateUsage]
    assert m._extra_headers["Copilot-Integration-Id"] == "vscode-chat"  # pyright: ignore[reportPrivateUsage]


def test_infer_litellm_model_passes_through_model_instance() -> None:
    inner = TestModel()
    assert infer_litellm_model(inner) is inner


def test_github_copilot_litellm_model() -> None:
    assert github_copilot_litellm_model("gpt-4o") == "github_copilot/gpt-4o"


def test_default_github_copilot_constant() -> None:
    assert DEFAULT_GITHUB_COPILOT_LITELLM_MODEL.startswith("github_copilot/")


@pytest.mark.skipif(
    not _litellm_live_enabled(),
    reason="Set LITELLM_API_BASE or PYDANTIC_DEEP_LITELLM_LIVE=1 for live LiteLLM test",
)
async def test_litellm_live_agent_roundtrip() -> None:
    """One real completion via LiteLLM (proxy URL and/or OAuth2 per your LiteLLM config)."""
    model_spec = os.environ.get(
        "PYDANTIC_DEEP_TEST_LITELLM_MODEL",
        f"litellm:{DEFAULT_GITHUB_COPILOT_LITELLM_MODEL}",
    )
    agent = create_deep_agent(
        model=infer_litellm_model(model_spec),
        include_todo=False,
        include_filesystem=False,
        include_subagents=False,
        include_skills=False,
        include_plan=False,
        cost_tracking=False,
        context_manager=False,
        include_history_archive=False,
    )
    deps = create_default_deps()
    result = await agent.run(
        "Reply with the single word OK and nothing else.",
        deps=deps,
    )
    assert "ok" in result.output.lower()

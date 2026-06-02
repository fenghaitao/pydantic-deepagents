"""Moonshot AI provider integration for pydantic-ai.

Moonshot uses an OpenAI-compatible API (https://api.moonshot.ai/v1).
Set MOONSHOT_API_KEY in the environment before use.
"""

from __future__ import annotations

import os

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

MOONSHOT_BASE_URL = "https://api.moonshot.ai/v1"

# kimi-k2.x only accepts temperature=1 — callers should not set temperature.
_FIXED_TEMP_PREFIXES = ("kimi-k2",)


def infer_moonshot_model(model: str) -> OpenAIChatModel:
    """Create an OpenAIChatModel targeting Moonshot AI.

    Accepts ``moonshot:<model-name>`` or bare ``<model-name>``.
    Reads MOONSHOT_API_KEY from the environment.
    """
    model_name = model.removeprefix("moonshot:")
    provider = OpenAIProvider(
        base_url=MOONSHOT_BASE_URL,
        api_key=os.environ.get("MOONSHOT_API_KEY", ""),
    )
    return OpenAIChatModel(model_name, provider=provider)


def moonshot_model_fixes_temperature(model: str) -> bool:
    """Return True if the model only accepts a fixed temperature (must not be set)."""
    name = model.removeprefix("moonshot:")
    return any(name.startswith(p) for p in _FIXED_TEMP_PREFIXES)

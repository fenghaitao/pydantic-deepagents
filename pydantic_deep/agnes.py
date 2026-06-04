"""Agnes AI provider integration for pydantic-ai.

Agnes uses an OpenAI-compatible API (https://apihub.agnes-ai.com/v1).
Set AGNES_API_KEY in the environment before use.
"""

from __future__ import annotations

import os

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"


def infer_agnes_model(model: str) -> OpenAIChatModel:
    """Create an OpenAIChatModel targeting Agnes AI.

    Accepts ``agnes:<model-name>`` or bare ``<model-name>``.
    Reads AGNES_API_KEY from the environment.
    """
    model_name = model.removeprefix("agnes:")
    provider = OpenAIProvider(
        base_url=AGNES_BASE_URL,
        api_key=os.environ.get("AGNES_API_KEY", ""),
    )
    return OpenAIChatModel(model_name, provider=provider)

"""Tests for apps/deepresearch model resolution."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEEPRESEARCH_SRC = _REPO_ROOT / "apps" / "deepresearch" / "src"
if _DEEPRESEARCH_SRC.is_dir() and str(_DEEPRESEARCH_SRC) not in sys.path:
    sys.path.insert(0, str(_DEEPRESEARCH_SRC))

pytest.importorskip("deepresearch")


def _reload_deepresearch_config(**env: str) -> Any:
    """Reload ``deepresearch.config`` with patched environment."""
    to_drop = [m for m in sys.modules if m == "deepresearch" or m.startswith("deepresearch.")]
    for m in to_drop:
        del sys.modules[m]
    new_env = dict(os.environ)
    new_env.pop("MODEL_NAME", None)
    new_env.update(env)
    with patch.dict(os.environ, new_env, clear=True):
        return importlib.import_module("deepresearch.config")


def test_explicit_model_name_string() -> None:
    cfg = _reload_deepresearch_config(MODEL_NAME="openai:gpt-4.1")
    assert cfg.MODEL_NAME == "openai:gpt-4.1"


def test_litellm_prefix_returns_litellm_model() -> None:
    from pydantic_deep.litellm import LiteLLMModel

    cfg = _reload_deepresearch_config(MODEL_NAME="litellm:github_copilot/gpt-4o")
    assert isinstance(cfg.MODEL_NAME, LiteLLMModel)


def test_unset_model_falls_back_to_agnes_without_keys() -> None:
    cfg = _reload_deepresearch_config(
        OPENAI_API_KEY="",
        OPENROUTER_API_KEY="",
        ANTHROPIC_API_KEY="",
        GOOGLE_API_KEY="",
        MOONSHOT_API_KEY="",
        AGNES_API_KEY="",
    )
    assert "MODEL_NAME" not in os.environ
    # No managed-provider key set → config default "agnes:agnes-2.0-flash" is returned
    # as a string. The deepresearch config layer only wraps litellm: prefixes;
    # agnes: strings are resolved by the CLI agent layer when the model is used.
    assert cfg.MODEL_NAME == "agnes:agnes-2.0-flash"

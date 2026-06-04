"""Tests for DeepApp._pick_available_model provider auto-selection."""
# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import patch

from apps.cli.app import DeepApp

pick = DeepApp._pick_available_model


def _env(**keys: str) -> dict[str, str]:
    return keys


def test_moonshot_kept_when_its_key_present() -> None:
    with patch.dict("os.environ", _env(MOONSHOT_API_KEY="x"), clear=True):
        assert pick("moonshot:kimi-k2.6") == "moonshot:kimi-k2.6"


def test_moonshot_not_swapped_by_stray_openai_key() -> None:
    # Regression: an OpenAI key must not hijack a configured moonshot model.
    with patch.dict("os.environ", _env(MOONSHOT_API_KEY="x", OPENAI_API_KEY="y"), clear=True):
        assert pick("moonshot:kimi-k2.6") == "moonshot:kimi-k2.6"


def test_unmanaged_provider_trusted_as_configured() -> None:
    # litellm / ollama / custom endpoints are returned unchanged even when a
    # managed provider key is present.
    with patch.dict("os.environ", _env(OPENAI_API_KEY="y"), clear=True):
        assert pick("litellm:github_copilot/gpt-4o") == "litellm:github_copilot/gpt-4o"
        assert pick("ollama:llama3.3") == "ollama:llama3.3"


def test_managed_provider_falls_back_when_key_missing() -> None:
    # openai configured but no openai key; anthropic key present → fall back.
    with patch.dict("os.environ", _env(ANTHROPIC_API_KEY="a"), clear=True):
        assert pick("openai:gpt-4.1") == "anthropic:claude-sonnet-4-6"


def test_agnes_kept_when_its_key_present() -> None:
    with patch.dict("os.environ", _env(AGNES_API_KEY="x"), clear=True):
        assert pick("agnes:agnes-2.0-flash") == "agnes:agnes-2.0-flash"


def test_agnes_falls_back_when_key_missing() -> None:
    with patch.dict("os.environ", _env(ANTHROPIC_API_KEY="a"), clear=True):
        assert pick("agnes:agnes-2.0-flash") == "anthropic:claude-sonnet-4-6"


def test_no_keys_returns_current() -> None:
    with patch.dict("os.environ", {}, clear=True):
        assert pick("openai:gpt-4.1") == "openai:gpt-4.1"

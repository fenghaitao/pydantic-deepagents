"""Tests for apps/potpie/agent.py.

Validates:
- create_potpie_agent calls create_deep_agent with kg_toolset in both
  toolsets and subagent_extra_toolsets
- deps.backend is a StateBackend instance
- Defaults: include_subagents=True, include_teams=True, include_memory=True,
  context_manager=True, eviction_token_limit=20_000
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from pydantic_ai_backends import StateBackend

# ---------------------------------------------------------------------------
# Stub out heavy backend imports before any app.* module is loaded.
# ---------------------------------------------------------------------------

_STUB_MODULES = [
    "app",
    "app.modules",
    "app.modules.intelligence",
    "app.modules.intelligence.tools",
    "app.modules.intelligence.tools.tool_service",
    "app.modules.intelligence.agents",
    "app.modules.intelligence.agents.chat_agents",
    "app.modules.intelligence.agents.chat_agents.multi_agent",
    "app.modules.intelligence.agents.chat_agents.multi_agent.utils",
    "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils",
]


def _install_stubs() -> None:
    for mod_name in _STUB_MODULES:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = ModuleType(mod_name)

    tool_utils_mod = sys.modules[
        "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils"
    ]
    tool_utils_mod.wrap_structured_tools = MagicMock(name="wrap_structured_tools")  # type: ignore[attr-defined]
    tool_utils_mod.sanitize_tool_name_for_api = MagicMock(name="sanitize_tool_name_for_api")  # type: ignore[attr-defined]

    tool_service_mod = sys.modules["app.modules.intelligence.tools.tool_service"]
    tool_service_mod.ToolService = MagicMock(name="ToolService")  # type: ignore[attr-defined]


_install_stubs()

from apps.potpie.agent import create_potpie_agent  # noqa: E402


def _make_runtime_mock() -> MagicMock:
    runtime = MagicMock()
    runtime.db.get_session.return_value = MagicMock()
    return runtime


class TestCreatePotpieAgent:
    """Tests for create_potpie_agent factory."""

    def test_create_deep_agent_receives_kg_toolset_in_toolsets(self) -> None:
        """create_deep_agent is called with kg_toolset in toolsets."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch("apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset),
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent) as mock_cda,
        ):
            create_potpie_agent(runtime, "proj-1", "user-1")

        _, kwargs = mock_cda.call_args
        assert mock_toolset in kwargs["toolsets"], (
            "kg_toolset must be in toolsets passed to create_deep_agent"
        )

    def test_create_deep_agent_receives_kg_toolset_in_subagent_extra_toolsets(self) -> None:
        """create_deep_agent is called with kg_toolset in subagent_extra_toolsets."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch("apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset),
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent) as mock_cda,
        ):
            create_potpie_agent(runtime, "proj-1", "user-1")

        _, kwargs = mock_cda.call_args
        assert mock_toolset in kwargs["subagent_extra_toolsets"], (
            "kg_toolset must be in subagent_extra_toolsets passed to create_deep_agent"
        )

    def test_deps_backend_is_state_backend(self) -> None:
        """deps.backend is a StateBackend instance (in-memory, not filesystem)."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch("apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset),
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent),
        ):
            _, deps = create_potpie_agent(runtime, "proj-1", "user-1")

        assert isinstance(deps.backend, StateBackend), (
            f"deps.backend should be StateBackend, got {type(deps.backend)}"
        )

    def test_returns_agent_and_deps_tuple(self) -> None:
        """create_potpie_agent returns a (agent, deps) tuple."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch("apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset),
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent),
        ):
            result = create_potpie_agent(runtime, "proj-1", "user-1")

        assert len(result) == 2
        agent, deps = result
        assert agent is mock_agent

    def test_create_potpie_toolset_called_with_runtime_project_user(self) -> None:
        """create_potpie_toolset is called with the correct runtime, project_id, user_id."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch(
                "apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset
            ) as mock_cts,
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent),
        ):
            create_potpie_agent(runtime, "proj-abc", "user-xyz")

        mock_cts.assert_called_once_with(runtime, "proj-abc", "user-xyz")

    def test_defaults_include_subagents_true(self) -> None:
        """create_deep_agent is called with include_subagents=True."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch("apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset),
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent) as mock_cda,
        ):
            create_potpie_agent(runtime, "proj-1", "user-1")

        _, kwargs = mock_cda.call_args
        assert kwargs.get("include_subagents") is True

    def test_defaults_include_teams_true(self) -> None:
        """create_deep_agent is called with include_teams=True."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch("apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset),
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent) as mock_cda,
        ):
            create_potpie_agent(runtime, "proj-1", "user-1")

        _, kwargs = mock_cda.call_args
        assert kwargs.get("include_teams") is True

    def test_defaults_include_memory_true(self) -> None:
        """create_deep_agent is called with include_memory=True."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch("apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset),
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent) as mock_cda,
        ):
            create_potpie_agent(runtime, "proj-1", "user-1")

        _, kwargs = mock_cda.call_args
        assert kwargs.get("include_memory") is True

    def test_defaults_context_manager_true(self) -> None:
        """create_deep_agent is called with context_manager=True."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch("apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset),
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent) as mock_cda,
        ):
            create_potpie_agent(runtime, "proj-1", "user-1")

        _, kwargs = mock_cda.call_args
        assert kwargs.get("context_manager") is True

    def test_defaults_eviction_token_limit_20000(self) -> None:
        """create_deep_agent is called with eviction_token_limit=20_000."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch("apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset),
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent) as mock_cda,
        ):
            create_potpie_agent(runtime, "proj-1", "user-1")

        _, kwargs = mock_cda.call_args
        assert kwargs.get("eviction_token_limit") == 20_000

    def test_kwargs_forwarded_to_create_deep_agent(self) -> None:
        """Extra kwargs are forwarded to create_deep_agent."""
        runtime = _make_runtime_mock()
        mock_toolset = MagicMock()
        mock_agent = MagicMock()

        with (
            patch("apps.potpie.agent.create_potpie_toolset", return_value=mock_toolset),
            patch("apps.potpie.agent.create_deep_agent", return_value=mock_agent) as mock_cda,
        ):
            create_potpie_agent(runtime, "proj-1", "user-1", instructions="custom instructions")

        _, kwargs = mock_cda.call_args
        assert kwargs.get("instructions") == "custom instructions"

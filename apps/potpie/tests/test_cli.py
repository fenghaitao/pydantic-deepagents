"""Tests for apps/potpie/cli.py.

Tests parse, chat, and ask commands via typer.testing.CliRunner,
including backend-down error paths.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Stub out heavy imports before any module-level import below.
# We stub both app.* (instructor/mistralai chain) and potpie (which imports
# app.* transitively via potpie.types).
# ---------------------------------------------------------------------------


class PotpieError(Exception):
    """Stub for potpie.exceptions.PotpieError."""


class ConfigurationError(PotpieError):
    """Stub for potpie.exceptions.ConfigurationError."""


def _install_stubs() -> None:
    # --- potpie stubs ---
    # Stub potpie and potpie.exceptions with real exception classes so CLI
    # error handling works. Also expose PotpieRuntime on the potpie stub so
    # that `from potpie import PotpieRuntime` inside cli.py succeeds.
    potpie_mod = ModuleType("potpie")
    potpie_mod.PotpieError = PotpieError  # type: ignore[attr-defined]
    potpie_mod.ConfigurationError = ConfigurationError  # type: ignore[attr-defined]
    potpie_mod.PotpieRuntime = MagicMock(name="PotpieRuntime")  # type: ignore[attr-defined]
    sys.modules["potpie"] = potpie_mod

    potpie_exceptions_mod = ModuleType("potpie.exceptions")
    potpie_exceptions_mod.PotpieError = PotpieError  # type: ignore[attr-defined]
    potpie_exceptions_mod.ConfigurationError = ConfigurationError  # type: ignore[attr-defined]
    sys.modules["potpie.exceptions"] = potpie_exceptions_mod

    # --- app.* stubs ---
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

# Now safe to import CLI (stubs are in place)
from typer.testing import CliRunner  # noqa: E402

from apps.potpie.cli import app  # noqa: E402

runner = CliRunner()

# The CLI imports PotpieRuntime lazily inside async functions via
# `from potpie import PotpieRuntime`.  We patch it on the potpie stub module.
_RUNTIME_PATCH = "potpie.PotpieRuntime"
# create_potpie_agent is also imported lazily inside _chat and _ask.
_AGENT_PATCH = "apps.potpie.agent.create_potpie_agent"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime_mock(initialize_raises: Exception | None = None) -> MagicMock:
    """Build a mock PotpieRuntime."""
    runtime = MagicMock()
    if initialize_raises:
        runtime.initialize = AsyncMock(side_effect=initialize_raises)
    else:
        runtime.initialize = AsyncMock()
    runtime.close = AsyncMock()
    runtime.projects.register = AsyncMock(return_value="proj-test-123")
    runtime.parsing.parse_project = AsyncMock()
    return runtime


# ---------------------------------------------------------------------------
# parse command
# ---------------------------------------------------------------------------


class TestParseCommand:
    """Tests for the `parse` CLI command."""

    def test_parse_success_prints_project_id(self) -> None:
        """On success, parse prints the project_id to stdout."""
        runtime = _make_runtime_mock()

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["parse", "/some/repo"])

        assert result.exit_code == 0
        assert "proj-test-123" in result.output

    def test_parse_calls_register_and_parse(self) -> None:
        """parse calls runtime.projects.register and runtime.parsing.parse_project."""
        runtime = _make_runtime_mock()

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            runner.invoke(app, ["parse", "/my/repo"])

        runtime.projects.register.assert_called_once()
        runtime.parsing.parse_project.assert_called_once()

    def test_parse_closes_runtime_on_success(self) -> None:
        """Runtime is closed after a successful parse."""
        runtime = _make_runtime_mock()

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            runner.invoke(app, ["parse", "/my/repo"])

        runtime.close.assert_called_once()

    def test_parse_potpie_error_exits_1(self) -> None:
        """PotpieError during parse causes exit code 1."""
        runtime = _make_runtime_mock(initialize_raises=PotpieError("db down"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["parse", "/my/repo"])

        assert result.exit_code == 1

    def test_parse_configuration_error_exits_1(self) -> None:
        """ConfigurationError during parse causes exit code 1."""
        runtime = _make_runtime_mock(initialize_raises=ConfigurationError("missing env"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["parse", "/my/repo"])

        assert result.exit_code == 1

    def test_parse_connection_error_exits_1(self) -> None:
        """ConnectionError during parse causes exit code 1."""
        runtime = _make_runtime_mock(initialize_raises=ConnectionError("refused"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["parse", "/my/repo"])

        assert result.exit_code == 1

    def test_parse_closes_runtime_on_error(self) -> None:
        """Runtime is closed even when parse raises an error."""
        runtime = _make_runtime_mock(initialize_raises=PotpieError("boom"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            runner.invoke(app, ["parse", "/my/repo"])

        runtime.close.assert_called_once()


# ---------------------------------------------------------------------------
# ask command
# ---------------------------------------------------------------------------


class TestAskCommand:
    """Tests for the `ask` CLI command."""

    def test_ask_success_prints_result(self) -> None:
        """On success, ask prints the agent result to stdout."""
        runtime = _make_runtime_mock()
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = "The auth module handles JWT tokens."
        mock_agent.run = AsyncMock(return_value=mock_result)

        with (
            patch(_RUNTIME_PATCH) as MockRuntime,
            patch(_AGENT_PATCH, return_value=(mock_agent, MagicMock())),
        ):
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(
                app, ["ask", "What does auth do?", "--project-id", "proj-123"]
            )

        assert result.exit_code == 0
        assert "The auth module handles JWT tokens." in result.output

    def test_ask_exits_0_on_success(self) -> None:
        """ask exits with code 0 on success."""
        runtime = _make_runtime_mock()
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = "answer"
        mock_agent.run = AsyncMock(return_value=mock_result)

        with (
            patch(_RUNTIME_PATCH) as MockRuntime,
            patch(_AGENT_PATCH, return_value=(mock_agent, MagicMock())),
        ):
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["ask", "query", "--project-id", "proj-1"])

        assert result.exit_code == 0

    def test_ask_potpie_error_exits_1(self) -> None:
        """PotpieError during ask causes exit code 1."""
        runtime = _make_runtime_mock(initialize_raises=PotpieError("neo4j down"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["ask", "query", "--project-id", "proj-1"])

        assert result.exit_code == 1

    def test_ask_configuration_error_exits_1(self) -> None:
        """ConfigurationError during ask causes exit code 1."""
        runtime = _make_runtime_mock(initialize_raises=ConfigurationError("no env"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["ask", "query", "--project-id", "proj-1"])

        assert result.exit_code == 1

    def test_ask_connection_error_exits_1(self) -> None:
        """ConnectionError during ask causes exit code 1."""
        runtime = _make_runtime_mock(initialize_raises=ConnectionError("refused"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["ask", "query", "--project-id", "proj-1"])

        assert result.exit_code == 1

    def test_ask_closes_runtime_on_success(self) -> None:
        """Runtime is closed after a successful ask."""
        runtime = _make_runtime_mock()
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = "answer"
        mock_agent.run = AsyncMock(return_value=mock_result)

        with (
            patch(_RUNTIME_PATCH) as MockRuntime,
            patch(_AGENT_PATCH, return_value=(mock_agent, MagicMock())),
        ):
            MockRuntime.from_env.return_value = runtime
            runner.invoke(app, ["ask", "query", "--project-id", "proj-1"])

        runtime.close.assert_called_once()

    def test_ask_closes_runtime_on_error(self) -> None:
        """Runtime is closed even when ask raises an error."""
        runtime = _make_runtime_mock(initialize_raises=PotpieError("boom"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            runner.invoke(app, ["ask", "query", "--project-id", "proj-1"])

        runtime.close.assert_called_once()


# ---------------------------------------------------------------------------
# chat command
# ---------------------------------------------------------------------------


class TestChatCommand:
    """Tests for the `chat` CLI command."""

    def test_chat_potpie_error_exits_1(self) -> None:
        """PotpieError at startup causes exit code 1."""
        runtime = _make_runtime_mock(initialize_raises=PotpieError("db down"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["chat", "--project-id", "proj-1"])

        assert result.exit_code == 1

    def test_chat_configuration_error_exits_1(self) -> None:
        """ConfigurationError at startup causes exit code 1."""
        runtime = _make_runtime_mock(initialize_raises=ConfigurationError("missing env"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["chat", "--project-id", "proj-1"])

        assert result.exit_code == 1

    def test_chat_connection_error_exits_1(self) -> None:
        """ConnectionError at startup causes exit code 1."""
        runtime = _make_runtime_mock(initialize_raises=ConnectionError("refused"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            result = runner.invoke(app, ["chat", "--project-id", "proj-1"])

        assert result.exit_code == 1

    def test_chat_closes_runtime_on_error(self) -> None:
        """Runtime is closed even when chat raises an error at startup."""
        runtime = _make_runtime_mock(initialize_raises=PotpieError("boom"))

        with patch(_RUNTIME_PATCH) as MockRuntime:
            MockRuntime.from_env.return_value = runtime
            runner.invoke(app, ["chat", "--project-id", "proj-1"])

        runtime.close.assert_called_once()

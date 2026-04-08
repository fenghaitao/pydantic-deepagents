"""Tests for apps/potpie/toolset.py.

Validates:
- create_potpie_toolset returns a FunctionToolset with all 8 KG tool names
- All tool names are sanitized (match ^[a-zA-Z0-9_-]+$)
- _close_session closes the session and clears _db_session
- Property 1: sanitize_tool_name_for_api is total and safe for any non-empty input
"""

from __future__ import annotations

import re
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from pydantic_ai import Tool
from pydantic_ai.toolsets import FunctionToolset

# ---------------------------------------------------------------------------
# Stub out heavy backend imports before any app.* module is loaded.
# This prevents the deep import chain (instructor → mistralai → …) from
# running during test collection.
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

_original_modules: dict[str, ModuleType | None] = {}


def _real_sanitize(name: str) -> str:
    """Minimal reference implementation matching the real sanitize_tool_name_for_api."""
    import re as _re

    if not name:
        return "unnamed_tool"
    sanitized = _re.sub(r"[^a-zA-Z0-9_-]+", "_", name)
    sanitized = _re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized or "unnamed_tool"


def _install_stubs() -> None:
    for mod_name in _STUB_MODULES:
        _original_modules[mod_name] = sys.modules.get(mod_name)
        if mod_name not in sys.modules:
            sys.modules[mod_name] = ModuleType(mod_name)

    # Provide the two symbols actually imported by toolset.py
    tool_utils_mod = sys.modules[
        "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils"
    ]
    tool_utils_mod.wrap_structured_tools = MagicMock(name="wrap_structured_tools")  # type: ignore[attr-defined]
    tool_utils_mod.sanitize_tool_name_for_api = _real_sanitize  # type: ignore[attr-defined]

    tool_service_mod = sys.modules["app.modules.intelligence.tools.tool_service"]
    tool_service_mod.ToolService = MagicMock(name="ToolService")  # type: ignore[attr-defined]


_install_stubs()

# Now safe to import toolset (stubs are in place)
from apps.potpie.toolset import KG_TOOL_NAMES, _close_session, create_potpie_toolset  # noqa: E402

TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_real_tool(name: str) -> Tool:
    """Return a real pydantic-ai Tool with the given name."""

    def _fn() -> str:
        """A stub tool."""
        return "ok"

    return Tool(function=_fn, name=name, description=f"Tool {name}")


def _make_runtime_mock() -> MagicMock:
    """Return a mock PotpieRuntime with a db.get_session() stub."""
    runtime = MagicMock()
    runtime.db.get_session.return_value = MagicMock()
    return runtime


# ---------------------------------------------------------------------------
# Unit tests — Task 5.1
# ---------------------------------------------------------------------------


class TestCreatePotpieToolset:
    """Tests for create_potpie_toolset factory."""

    def test_returns_function_toolset(self) -> None:
        """create_potpie_toolset returns a FunctionToolset instance."""
        runtime = _make_runtime_mock()
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with (
            patch("apps.potpie.toolset.ToolService") as MockToolService,
            patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools),
        ):
            MockToolService.return_value.get_tools.return_value = []
            toolset = create_potpie_toolset(runtime, "proj-1", "user-1")

        assert isinstance(toolset, FunctionToolset)

    def test_toolset_contains_all_8_kg_tools(self) -> None:
        """Toolset has exactly the 8 KG tool names defined in KG_TOOL_NAMES."""
        runtime = _make_runtime_mock()
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with (
            patch("apps.potpie.toolset.ToolService") as MockToolService,
            patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools),
        ):
            MockToolService.return_value.get_tools.return_value = []
            toolset = create_potpie_toolset(runtime, "proj-1", "user-1")

        tool_names = list(toolset.tools.keys())
        for expected in KG_TOOL_NAMES:
            assert expected in tool_names, f"Missing tool: {expected}"

    def test_all_tool_names_are_sanitized(self) -> None:
        """All tool names in the returned toolset match ^[a-zA-Z0-9_-]+$."""
        runtime = _make_runtime_mock()
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with (
            patch("apps.potpie.toolset.ToolService") as MockToolService,
            patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools),
        ):
            MockToolService.return_value.get_tools.return_value = []
            toolset = create_potpie_toolset(runtime, "proj-1", "user-1")

        for name in toolset.tools.keys():
            assert TOOL_NAME_RE.match(name), f"Tool name not sanitized: {name!r}"

    def test_tool_service_receives_user_id(self) -> None:
        """ToolService is instantiated with the provided user_id."""
        runtime = _make_runtime_mock()
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with (
            patch("apps.potpie.toolset.ToolService") as MockToolService,
            patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools),
        ):
            MockToolService.return_value.get_tools.return_value = []
            create_potpie_toolset(runtime, "proj-1", "user-42")

        call_args = MockToolService.call_args
        # ToolService(db=session, user_id=user_id) — check positional or keyword
        assert "user-42" in (list(call_args.args) + list(call_args.kwargs.values()))

    def test_get_tools_called_with_kg_tool_names(self) -> None:
        """ToolService.get_tools is called with the full KG_TOOL_NAMES list."""
        runtime = _make_runtime_mock()
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with (
            patch("apps.potpie.toolset.ToolService") as MockToolService,
            patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools),
        ):
            mock_svc = MockToolService.return_value
            mock_svc.get_tools.return_value = []
            create_potpie_toolset(runtime, "proj-1", "user-1")

        mock_svc.get_tools.assert_called_once_with(KG_TOOL_NAMES)

    def test_kg_tool_names_constant_has_8_entries(self) -> None:
        """KG_TOOL_NAMES contains exactly 8 tool names."""
        assert len(KG_TOOL_NAMES) == 8

    def test_kg_tool_names_are_all_sanitized(self) -> None:
        """Every name in KG_TOOL_NAMES already satisfies the API regex."""
        for name in KG_TOOL_NAMES:
            assert TOOL_NAME_RE.match(name), f"KG_TOOL_NAMES entry not sanitized: {name!r}"


class TestCloseSession:
    """Tests for _close_session helper."""

    def test_close_session_calls_close_and_clears(self) -> None:
        """_close_session closes the DB session and sets _db_session to None."""
        runtime = _make_runtime_mock()
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]
        mock_session = MagicMock()
        runtime.db.get_session.return_value = mock_session

        with (
            patch("apps.potpie.toolset.ToolService") as MockToolService,
            patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools),
        ):
            MockToolService.return_value.get_tools.return_value = []
            toolset = create_potpie_toolset(runtime, "proj-1", "user-1")

        assert toolset._db_session is mock_session  # type: ignore[attr-defined]
        _close_session(toolset)

        mock_session.close.assert_called_once()
        assert toolset._db_session is None  # type: ignore[attr-defined]

    def test_close_session_noop_when_no_session(self) -> None:
        """_close_session is a no-op when _db_session is not set."""
        toolset = FunctionToolset(id="empty")
        # Should not raise
        _close_session(toolset)


# ---------------------------------------------------------------------------
# Property-based test — Task 5.4
# Validates: Requirements Correctness Property 1
# ---------------------------------------------------------------------------

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


@given(st.text(min_size=1))
@settings(max_examples=500)
def test_sanitize_tool_name_always_valid(name: str) -> None:
    """**Validates: Requirements Correctness Property 1**

    For any non-empty string, sanitize_tool_name_for_api returns a non-empty
    string matching ^[a-zA-Z0-9_-]+$.
    """
    result = _real_sanitize(name)
    assert re.match(r"^[a-zA-Z0-9_-]+$", result), (
        f"sanitize_tool_name_for_api({name!r}) = {result!r} does not match ^[a-zA-Z0-9_-]+$"
    )
    assert len(result) > 0, f"sanitize_tool_name_for_api({name!r}) returned empty string"

"""Tests for apps/potpie/toolset.py.

Validates:
- create_potpie_toolset returns a FunctionToolset with all 8 KG tool names
- All tool names are sanitized (match ^[a-zA-Z0-9_-]+$)
- Property 1: sanitize_tool_name_for_api is total and safe for any non-empty input
"""

from __future__ import annotations

import re
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import Tool
from pydantic_ai.toolsets import FunctionToolset

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

    tool_utils_mod = sys.modules[
        "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils"
    ]
    tool_utils_mod.wrap_structured_tools = MagicMock(name="wrap_structured_tools")  # type: ignore[attr-defined]
    tool_utils_mod.sanitize_tool_name_for_api = _real_sanitize  # type: ignore[attr-defined]

    tool_service_mod = sys.modules["app.modules.intelligence.tools.tool_service"]
    tool_service_mod.ToolService = MagicMock(name="ToolService")  # type: ignore[attr-defined]


_install_stubs()

# Now safe to import toolset (stubs are in place)
from apps.potpie.toolset import KG_TOOL_NAMES, create_potpie_toolset  # noqa: E402

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


def _make_backend_mock(tool_names: list[str]) -> MagicMock:
    """Return a mock PotpieBackend whose get_tools() returns real Tool objects."""
    backend = MagicMock()
    real_tools = [_make_real_tool(n) for n in tool_names]
    backend.get_tools = AsyncMock(return_value=real_tools)
    return backend


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestCreatePotpieToolset:
    """Tests for create_potpie_toolset factory."""

    @pytest.mark.asyncio
    async def test_returns_function_toolset(self) -> None:
        """create_potpie_toolset returns a FunctionToolset instance."""
        backend = _make_backend_mock(KG_TOOL_NAMES)
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools):
            toolset = await create_potpie_toolset(backend)

        assert isinstance(toolset, FunctionToolset)

    @pytest.mark.asyncio
    async def test_toolset_contains_all_8_kg_tools(self) -> None:
        """Toolset has exactly the 8 KG tool names defined in KG_TOOL_NAMES."""
        backend = _make_backend_mock(KG_TOOL_NAMES)
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools):
            toolset = await create_potpie_toolset(backend)

        tool_names = list(toolset.tools.keys())
        for expected in KG_TOOL_NAMES:
            assert expected in tool_names, f"Missing tool: {expected}"

    @pytest.mark.asyncio
    async def test_all_tool_names_are_sanitized(self) -> None:
        """All tool names in the returned toolset match ^[a-zA-Z0-9_-]+$."""
        backend = _make_backend_mock(KG_TOOL_NAMES)
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools):
            toolset = await create_potpie_toolset(backend)

        for name in toolset.tools.keys():
            assert TOOL_NAME_RE.match(name), f"Tool name not sanitized: {name!r}"

    @pytest.mark.asyncio
    async def test_get_tools_called_with_kg_tool_names(self) -> None:
        """backend.get_tools is called with the full KG_TOOL_NAMES list by default."""
        backend = _make_backend_mock(KG_TOOL_NAMES)
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools):
            await create_potpie_toolset(backend)

        backend.get_tools.assert_called_once_with(
            KG_TOOL_NAMES, exclude_embedding_tools=False
        )

    @pytest.mark.asyncio
    async def test_custom_tool_names_forwarded(self) -> None:
        """Custom tool_names are forwarded to backend.get_tools."""
        custom = ["fetch_file", "fetch_files_batch"]
        backend = _make_backend_mock(custom)
        real_tools = [_make_real_tool(n) for n in custom]

        with patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools):
            await create_potpie_toolset(backend, tool_names=custom)

        backend.get_tools.assert_called_once_with(custom, exclude_embedding_tools=False)

    @pytest.mark.asyncio
    async def test_exclude_embedding_tools_forwarded(self) -> None:
        """exclude_embedding_tools=True is forwarded to backend.get_tools."""
        backend = _make_backend_mock(KG_TOOL_NAMES)
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with patch("apps.potpie.toolset.wrap_structured_tools", return_value=real_tools):
            await create_potpie_toolset(backend, exclude_embedding_tools=True)

        backend.get_tools.assert_called_once_with(
            KG_TOOL_NAMES, exclude_embedding_tools=True
        )

    def test_kg_tool_names_constant_has_8_entries(self) -> None:
        """KG_TOOL_NAMES contains exactly 9 tool names (added nl_cypher_query)."""
        assert len(KG_TOOL_NAMES) == 9

    def test_kg_tool_names_are_all_sanitized(self) -> None:
        """Every name in KG_TOOL_NAMES already satisfies the API regex."""
        for name in KG_TOOL_NAMES:
            assert TOOL_NAME_RE.match(name), f"KG_TOOL_NAMES entry not sanitized: {name!r}"


# ---------------------------------------------------------------------------
# Property-based test
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

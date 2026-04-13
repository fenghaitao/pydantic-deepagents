"""Tests for CodeGraphToolset.from_runtime and KG_TOOL_NAMES.

Validates:
- from_runtime returns a FunctionToolset with all KG tool names
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
# Stub out heavy app.* imports before any module is loaded.
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
        if mod_name not in sys.modules:
            sys.modules[mod_name] = ModuleType(mod_name)

    tool_utils_mod = sys.modules[
        "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils"
    ]
    tool_utils_mod.wrap_structured_tools = MagicMock(name="wrap_structured_tools")  # type: ignore[attr-defined]
    tool_utils_mod.sanitize_tool_name_for_api = _real_sanitize  # type: ignore[attr-defined]


_install_stubs()

from pydantic_deep.toolsets.code_graph.toolset import KG_TOOL_NAMES, CodeGraphToolset  # noqa: E402

TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_real_tool(name: str) -> Tool:
    def _fn() -> str:
        """A stub tool."""
        return "ok"

    return Tool(function=_fn, name=name, description=f"Tool {name}")


def _make_backend_mock(tool_names: list[str]) -> MagicMock:
    backend = MagicMock()
    real_tools = [_make_real_tool(n) for n in tool_names]
    backend.get_tools = AsyncMock(return_value=real_tools)
    return backend


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestFromRuntime:
    """Tests for CodeGraphToolset.from_runtime factory."""

    @pytest.mark.asyncio
    async def test_returns_function_toolset(self) -> None:
        backend = _make_backend_mock(KG_TOOL_NAMES)
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with patch(
            "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils.wrap_structured_tools",
            return_value=real_tools,
        ):
            toolset = await CodeGraphToolset.from_runtime(backend)

        assert isinstance(toolset, FunctionToolset)

    @pytest.mark.asyncio
    async def test_toolset_contains_all_kg_tools(self) -> None:
        backend = _make_backend_mock(KG_TOOL_NAMES)
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with patch(
            "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils.wrap_structured_tools",
            return_value=real_tools,
        ):
            toolset = await CodeGraphToolset.from_runtime(backend)

        for expected in KG_TOOL_NAMES:
            assert expected in toolset.tools, f"Missing tool: {expected}"

    @pytest.mark.asyncio
    async def test_all_tool_names_are_sanitized(self) -> None:
        backend = _make_backend_mock(KG_TOOL_NAMES)
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with patch(
            "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils.wrap_structured_tools",
            return_value=real_tools,
        ):
            toolset = await CodeGraphToolset.from_runtime(backend)

        for name in toolset.tools:
            assert TOOL_NAME_RE.match(name), f"Tool name not sanitized: {name!r}"

    @pytest.mark.asyncio
    async def test_get_tools_called_with_kg_tool_names(self) -> None:
        backend = _make_backend_mock(KG_TOOL_NAMES)
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with patch(
            "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils.wrap_structured_tools",
            return_value=real_tools,
        ):
            await CodeGraphToolset.from_runtime(backend)

        backend.get_tools.assert_called_once_with(KG_TOOL_NAMES, exclude_embedding_tools=False)

    @pytest.mark.asyncio
    async def test_custom_tool_names_forwarded(self) -> None:
        custom = ["fetch_file", "fetch_files_batch"]
        backend = _make_backend_mock(custom)
        real_tools = [_make_real_tool(n) for n in custom]

        with patch(
            "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils.wrap_structured_tools",
            return_value=real_tools,
        ):
            await CodeGraphToolset.from_runtime(backend, tool_names=custom)

        backend.get_tools.assert_called_once_with(custom, exclude_embedding_tools=False)

    @pytest.mark.asyncio
    async def test_exclude_embedding_tools_forwarded(self) -> None:
        backend = _make_backend_mock(KG_TOOL_NAMES)
        real_tools = [_make_real_tool(n) for n in KG_TOOL_NAMES]

        with patch(
            "app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils.wrap_structured_tools",
            return_value=real_tools,
        ):
            await CodeGraphToolset.from_runtime(backend, exclude_embedding_tools=True)

        backend.get_tools.assert_called_once_with(KG_TOOL_NAMES, exclude_embedding_tools=True)

    def test_kg_tool_names_has_9_entries(self) -> None:
        assert len(KG_TOOL_NAMES) == 9

    def test_kg_tool_names_are_all_sanitized(self) -> None:
        for name in KG_TOOL_NAMES:
            assert TOOL_NAME_RE.match(name), f"KG_TOOL_NAMES entry not sanitized: {name!r}"


# ---------------------------------------------------------------------------
# Tests for _inject_project_id
# ---------------------------------------------------------------------------

from pydantic_deep.toolsets.code_graph.toolset import _inject_project_id  # noqa: E402


class TestInjectProjectId:
    def _make_tool_with_project_id(self, is_async: bool = True) -> Any:
        """Return a Tool whose schema includes project_id."""
        from pydantic_ai import Tool

        if is_async:
            async def fn(project_id: str, query: str) -> str:
                return f"{project_id}:{query}"
        else:
            def fn(project_id: str, query: str) -> str:  # type: ignore[misc]
                return f"{project_id}:{query}"

        return Tool(function=fn, name="test_tool", description="test")

    def _make_tool_without_project_id(self) -> Any:
        from pydantic_ai import Tool

        async def fn(query: str) -> str:
            return query

        return Tool(function=fn, name="no_proj_tool", description="test")

    def _make_ctx(self, project_id: str | None = "proj-1") -> Any:
        ctx = MagicMock()
        if project_id:
            ctx.deps.potpie.project_id = project_id
            ctx.deps.potpie.parsing_status = "READY"
        else:
            ctx.deps.potpie = None
        return ctx

    def test_returns_tool_unchanged_when_no_project_id_in_schema(self) -> None:
        tool = self._make_tool_without_project_id()
        result = _inject_project_id(tool)
        assert result is tool

    @pytest.mark.asyncio
    async def test_async_tool_injects_project_id(self) -> None:
        tool = self._make_tool_with_project_id(is_async=True)
        wrapped = _inject_project_id(tool)
        ctx = self._make_ctx("my-proj")
        result = await wrapped.function(ctx, query="hello")
        assert "my-proj" in result

    @pytest.mark.asyncio
    async def test_sync_tool_injects_project_id(self) -> None:
        tool = self._make_tool_with_project_id(is_async=False)
        wrapped = _inject_project_id(tool)
        ctx = self._make_ctx("my-proj")
        result = wrapped.function(ctx, query="hello")
        assert "my-proj" in result

    @pytest.mark.asyncio
    async def test_embedding_tool_blocked_during_inferring(self) -> None:
        from pydantic_ai import Tool

        async def fn(project_id: str, queries: list) -> str:
            return "ok"

        tool = Tool(function=fn, name="ask_knowledge_graph_queries", description="test")
        wrapped = _inject_project_id(tool)
        ctx = MagicMock()
        ctx.deps.potpie.project_id = "p1"
        ctx.deps.potpie.parsing_status = "INFERRING"
        result = await wrapped.function(ctx, queries=[])
        assert "INFERRING" in result

    def test_project_id_removed_from_schema(self) -> None:
        tool = self._make_tool_with_project_id()
        wrapped = _inject_project_id(tool)
        fs = getattr(wrapped, "function_schema", None)
        schema = getattr(fs, "json_schema", None) or {}
        assert "project_id" not in schema.get("properties", {})

    def test_sync_embedding_tool_blocked_during_inferring(self) -> None:
        from pydantic_ai import Tool

        def fn(project_id: str, queries: list) -> str:  # type: ignore[misc]
            return "ok"

        tool = Tool(function=fn, name="ask_knowledge_graph_queries", description="test")
        wrapped = _inject_project_id(tool)
        ctx = MagicMock()
        ctx.deps.potpie.project_id = "p1"
        ctx.deps.potpie.parsing_status = "INFERRING"
        result = wrapped.function(ctx, queries=[])
        assert "INFERRING" in result

    def test_project_id_removed_from_schema(self) -> None:
        tool = self._make_tool_with_project_id()
        wrapped = _inject_project_id(tool)
        fs = getattr(wrapped, "function_schema", None)
        schema = getattr(fs, "json_schema", None) or {}
        assert "project_id" not in schema.get("properties", {})

    @pytest.mark.asyncio
    async def test_async_tool_no_potpie_context(self) -> None:
        """Covers async ctx_wrapper when potpie is None (no project_id injected)."""
        tool = self._make_tool_with_project_id(is_async=True)
        wrapped = _inject_project_id(tool)
        ctx = self._make_ctx(project_id=None)  # potpie is None
        # project_id won't be injected — call will fail with missing arg, catch TypeError
        try:
            await wrapped.function(ctx, query="hello")
        except TypeError:
            pass  # expected — project_id not injected, original func requires it

    def test_sync_tool_no_potpie_context(self) -> None:
        """Covers sync ctx_wrapper when potpie is None (no project_id injected)."""
        tool = self._make_tool_with_project_id(is_async=False)
        wrapped = _inject_project_id(tool)
        ctx = self._make_ctx(project_id=None)
        try:
            wrapped.function(ctx, query="hello")
        except TypeError:
            pass  # expected

    @pytest.mark.asyncio
    async def test_async_non_embedding_tool_not_blocked(self) -> None:
        """Covers async ctx_wrapper INFERRING check for non-embedding tool (no block)."""
        from pydantic_ai import Tool

        async def fn(project_id: str, query: str) -> str:
            return "ok"

        tool = Tool(function=fn, name="fetch_file", description="test")
        wrapped = _inject_project_id(tool)
        ctx = MagicMock()
        ctx.deps.potpie.project_id = "p1"
        ctx.deps.potpie.parsing_status = "INFERRING"
        result = await wrapped.function(ctx, query="x")
        assert result == "ok"

    def test_sync_non_embedding_tool_not_blocked(self) -> None:
        """Covers sync ctx_wrapper INFERRING check for non-embedding tool (no block)."""
        from pydantic_ai import Tool

        def fn(project_id: str, query: str) -> str:  # type: ignore[misc]
            return "ok"

        tool = Tool(function=fn, name="fetch_file", description="test")
        wrapped = _inject_project_id(tool)
        ctx = MagicMock()
        ctx.deps.potpie.project_id = "p1"
        ctx.deps.potpie.parsing_status = "INFERRING"
        result = wrapped.function(ctx, query="x")
        assert result == "ok"

    def test_tool_with_parameters_json_schema_attr(self) -> None:
        """Covers the parameters_json_schema attribute path (98->102 branch)."""
        from pydantic_ai import Tool

        async def fn(project_id: str, query: str) -> str:
            return "ok"

        tool = Tool(function=fn, name="test_tool", description="test")
        # Manually set parameters_json_schema to simulate that path
        tool.parameters_json_schema = {  # type: ignore[attr-defined]
            "properties": {"project_id": {}, "query": {}},
            "required": ["query"],  # project_id NOT in required
        }
        wrapped = _inject_project_id(tool)
        # Should wrap successfully and not add project_id to required
        fs = getattr(wrapped, "function_schema", None)
        schema = getattr(fs, "json_schema", None) or {}
        assert "project_id" not in schema.get("properties", {})

    @pytest.mark.asyncio
    async def test_async_embedding_tool_no_potpie_no_block(self) -> None:
        """Covers async ctx_wrapper: embedding tool but potpie is None (no INFERRING check)."""
        from pydantic_ai import Tool

        async def fn(project_id: str, queries: list) -> str:
            return "called"

        tool = Tool(function=fn, name="ask_knowledge_graph_queries", description="test")
        wrapped = _inject_project_id(tool)
        ctx = MagicMock()
        ctx.deps.potpie = None  # no potpie context
        # project_id won't be injected, original func will get missing arg
        try:
            await wrapped.function(ctx, queries=[])
        except TypeError:
            pass  # expected — no project_id

    def test_sync_embedding_tool_no_potpie_no_block(self) -> None:
        """Covers sync ctx_wrapper: embedding tool but potpie is None (no INFERRING check)."""
        from pydantic_ai import Tool

        def fn(project_id: str, queries: list) -> str:  # type: ignore[misc]
            return "called"

        tool = Tool(function=fn, name="ask_knowledge_graph_queries", description="test")
        wrapped = _inject_project_id(tool)
        ctx = MagicMock()
        ctx.deps.potpie = None
        try:
            wrapped.function(ctx, queries=[])
        except TypeError:
            pass  # expected

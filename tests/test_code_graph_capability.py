"""Tests for PotpieCapability.

Validates:
- Construction with backend, project_id, context
- get_toolset() returns None before for_run()
- subagents property returns None before for_run()
- before_run() sets ctx.deps.kg_context = self.context
- for_run() returns new instance with _toolset and _subagents set, original unchanged

**Validates: Requirements 1.3, 1.4, 1.5**
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pydantic_deep.capabilities.code_graph.potpie import PotpieCapability
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.code_graph.potpie.context import PotpieContext
from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime


def _make_runtime() -> MagicMock:
    b = MagicMock(spec=PotpieRuntime)
    b.get_tools = AsyncMock(return_value=[])
    return b


def _make_context(project_id: str = "proj-1") -> PotpieContext:
    return PotpieContext(project_id=project_id, user_id="user-1")


def _make_run_ctx(deps: DeepAgentDeps | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = deps if deps is not None else DeepAgentDeps()
    return ctx


class TestPotpieCapabilityConstruction:
    """Tests for PotpieCapability construction."""

    def test_basic_construction(self) -> None:
        backend = _make_runtime()
        cap = PotpieCapability(runtime=backend)
        assert cap.runtime is backend
        assert cap.project_id is None
        assert cap.context is None

    def test_construction_with_all_fields(self) -> None:
        backend = _make_runtime()
        context = _make_context()
        cap = PotpieCapability(runtime=backend, project_id="proj-1", context=context)
        assert cap.project_id == "proj-1"
        assert cap.context is context

    def test_toolset_none_on_construction(self) -> None:
        cap = PotpieCapability(runtime=_make_runtime())
        assert cap.get_toolset() is None

    def test_subagents_none_on_construction(self) -> None:
        cap = PotpieCapability(runtime=_make_runtime())
        assert cap.subagents is None


class TestPotpieCapabilityGetToolset:
    """Tests for get_toolset() — always None until set externally by build_kg_capability."""

    def test_get_toolset_returns_none_before_external_setup(self) -> None:
        cap = PotpieCapability(runtime=_make_runtime())
        assert cap.get_toolset() is None

    def test_get_toolset_returns_toolset_after_external_set(self) -> None:
        cap = PotpieCapability(runtime=_make_runtime(), project_id="proj-1")
        mock_toolset = MagicMock()
        object.__setattr__(cap, "_toolset", mock_toolset)
        assert cap.get_toolset() is mock_toolset


class TestPotpieCapabilitySubagents:
    """Tests for subagents property — set externally by build_kg_capability."""

    def test_subagents_none_before_external_setup(self) -> None:
        cap = PotpieCapability(runtime=_make_runtime())
        assert cap.subagents is None

    def test_subagents_returned_after_external_set(self) -> None:
        cap = PotpieCapability(runtime=_make_runtime(), project_id="proj-1")
        subagents = [{"name": "codebase_qna"}, {"name": "blast_radius"}]
        object.__setattr__(cap, "_subagents", subagents)
        assert cap.subagents is not None
        assert len(cap.subagents) == 2
        names = [s["name"] for s in cap.subagents]
        assert "codebase_qna" in names
        assert "blast_radius" in names


class TestPotpieCapabilityBeforeRun:
    """Tests for before_run() setting ctx.deps.kg_context."""

    @pytest.mark.asyncio
    async def test_before_run_sets_kg_context(self) -> None:
        backend = _make_runtime()
        context = _make_context("proj-42")
        cap = PotpieCapability(runtime=backend, context=context)

        deps = DeepAgentDeps()
        ctx = _make_run_ctx(deps)

        await cap.before_run(ctx)
        assert ctx.deps.kg_context is context

    @pytest.mark.asyncio
    async def test_before_run_sets_none_context(self) -> None:
        cap = PotpieCapability(runtime=_make_runtime(), context=None)
        deps = DeepAgentDeps()
        ctx = _make_run_ctx(deps)

        await cap.before_run(ctx)
        assert ctx.deps.kg_context is None

    @pytest.mark.asyncio
    async def test_before_run_overwrites_existing_kg_context(self) -> None:
        old_context = _make_context("old-proj")
        new_context = _make_context("new-proj")

        cap = PotpieCapability(runtime=_make_runtime(), context=new_context)
        deps = DeepAgentDeps()
        deps.kg_context = old_context
        ctx = _make_run_ctx(deps)

        await cap.before_run(ctx)
        assert ctx.deps.kg_context is new_context


class TestPotpieCapabilityGetInstructions:
    """Tests for get_instructions() callable."""

    @pytest.mark.asyncio
    async def test_instructions_with_project_id(self) -> None:
        context = _make_context("proj-42")
        cap = PotpieCapability(runtime=_make_runtime(), context=context)
        fn = cap.get_instructions()
        ctx = _make_run_ctx()
        ctx.deps.kg_context = context
        result = await fn(ctx)
        assert result is not None
        assert "proj-42" in result

    @pytest.mark.asyncio
    async def test_instructions_without_project_id(self) -> None:
        cap = PotpieCapability(runtime=_make_runtime(), context=None)
        fn = cap.get_instructions()
        ctx = _make_run_ctx()
        ctx.deps.kg_context = None
        result = await fn(ctx)
        assert result is not None
        assert "list_code_projects" in result

    @pytest.mark.asyncio
    async def test_instructions_inferring_status(self) -> None:
        from unittest.mock import MagicMock
        context = _make_context("proj-1")
        cap = PotpieCapability(runtime=_make_runtime(), context=context)
        fn = cap.get_instructions()
        ctx = _make_run_ctx()
        kg_ctx = MagicMock()
        kg_ctx.project_id = "proj-1"
        kg_ctx.parsing_status = "INFERRING"
        ctx.deps.kg_context = kg_ctx
        result = await fn(ctx)
        assert result is not None
        assert "INFERRING" in result

    @pytest.mark.asyncio
    async def test_instructions_parsing_status(self) -> None:
        from unittest.mock import MagicMock
        context = _make_context("proj-1")
        cap = PotpieCapability(runtime=_make_runtime(), context=context)
        fn = cap.get_instructions()
        ctx = _make_run_ctx()
        kg_ctx = MagicMock()
        kg_ctx.project_id = "proj-1"
        kg_ctx.parsing_status = "PARSING"
        ctx.deps.kg_context = kg_ctx
        result = await fn(ctx)
        assert result is not None
        assert "PARSING" in result


class TestPotpieCapabilityExternalSetup:
    """Tests that toolset and subagents are set externally (by build_kg_capability)
    and that the original capability is not mutated by before_run."""

    def test_toolset_and_subagents_set_via_object_setattr(self) -> None:
        cap = PotpieCapability(runtime=_make_runtime(), project_id="proj-1")
        mock_toolset = MagicMock()
        subagents = [{"name": "codebase_qna"}, {"name": "blast_radius"}]
        object.__setattr__(cap, "_toolset", mock_toolset)
        object.__setattr__(cap, "_subagents", subagents)
        assert cap.get_toolset() is mock_toolset
        assert cap.subagents == subagents

    @pytest.mark.asyncio
    async def test_before_run_does_not_clear_toolset(self) -> None:
        cap = PotpieCapability(runtime=_make_runtime(), project_id="proj-1")
        mock_toolset = MagicMock()
        object.__setattr__(cap, "_toolset", mock_toolset)
        ctx = _make_run_ctx()
        await cap.before_run(ctx)
        assert cap.get_toolset() is mock_toolset


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------


class TestBeforeRunProperty:
    """Property-based test for before_run() always setting kg_context.

    **Validates: Requirements 1.4, 3.1**
    """

    @given(
        context=st.one_of(
            st.none(),
            st.builds(
                PotpieContext,
                project_id=st.text(min_size=1, max_size=50),
                user_id=st.text(min_size=1, max_size=50),
                parsing_status=st.one_of(st.none(), st.just("READY"), st.just("INFERRING")),
            ),
        )
    )
    @settings(max_examples=30)
    def test_before_run_always_sets_kg_context(self, context: PotpieContext | None) -> None:
        """before_run() always sets ctx.deps.kg_context to self.context.

        **Validates: Requirements 1.4, 3.1**
        """
        import asyncio

        backend = _make_runtime()
        cap = PotpieCapability(runtime=backend, context=context)
        deps = DeepAgentDeps()
        ctx = _make_run_ctx(deps)

        asyncio.run(cap.before_run(ctx))
        assert ctx.deps.kg_context is context

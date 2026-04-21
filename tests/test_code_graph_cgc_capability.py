"""Tests for CGCCapability and apps.cli.cgc_setup.build_cgc_capability."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext

from pydantic_deep.capabilities.code_graph.cgc import CGCCapability
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.code_graph.cgc.context import CGCContext
from pydantic_deep.toolsets.code_graph.cgc.runtime import CGCRuntime


def _make_runtime() -> MagicMock:
    rt = MagicMock(spec=CGCRuntime)
    return rt


def _make_context(repo_path: str = "/my/repo") -> CGCContext:
    return CGCContext(repo_path=repo_path)


def _make_ctx(cgc_context: CGCContext | None = None) -> RunContext:
    ctx = MagicMock(spec=RunContext)
    ctx.deps = MagicMock(spec=DeepAgentDeps)
    ctx.deps.cgc_context = cgc_context
    return ctx


# ── CGCCapability unit tests ───────────────────────────────────────────────────


class TestCGCCapabilityConstruction:
    def test_construction_with_runtime_only(self) -> None:
        rt = _make_runtime()
        cap = CGCCapability(runtime=rt)
        assert cap.runtime is rt
        assert cap.context is None
        assert cap._toolset is None  # pyright: ignore[reportPrivateUsage]

    def test_construction_with_context(self) -> None:
        rt = _make_runtime()
        ctx = _make_context()
        cap = CGCCapability(runtime=rt, context=ctx)
        assert cap.context is ctx

    def test_get_toolset_returns_none_before_set(self) -> None:
        cap = CGCCapability(runtime=_make_runtime())
        assert cap.get_toolset() is None

    def test_get_toolset_returns_toolset_after_set(self) -> None:
        cap = CGCCapability(runtime=_make_runtime())
        mock_ts = MagicMock()
        object.__setattr__(cap, "_toolset", mock_ts)
        assert cap.get_toolset() is mock_ts


class TestCGCCapabilityBeforeRun:
    async def test_before_run_injects_context(self) -> None:
        rt = _make_runtime()
        cgc_ctx = _make_context("/repo")
        cap = CGCCapability(runtime=rt, context=cgc_ctx)
        run_ctx = _make_ctx()
        await cap.before_run(run_ctx)
        assert run_ctx.deps.cgc_context is cgc_ctx

    async def test_before_run_injects_none_when_no_context(self) -> None:
        cap = CGCCapability(runtime=_make_runtime())
        run_ctx = _make_ctx()
        await cap.before_run(run_ctx)
        assert run_ctx.deps.cgc_context is None


class TestCGCCapabilityGetInstructions:
    async def test_with_context_repo_path(self) -> None:
        rt = _make_runtime()
        cgc_ctx = _make_context("/my/repo")
        cap = CGCCapability(runtime=rt, context=cgc_ctx)
        fn = cap.get_instructions()
        run_ctx = _make_ctx(cgc_context=cgc_ctx)
        result = await fn(run_ctx)
        assert result is not None
        assert "/my/repo" in result
        assert "find_code" in result

    async def test_without_context(self) -> None:
        cap = CGCCapability(runtime=_make_runtime())
        fn = cap.get_instructions()
        run_ctx = _make_ctx()
        result = await fn(run_ctx)
        assert result is not None
        assert "list_code_projects" in result

    async def test_falls_back_to_cap_context_when_deps_has_none(self) -> None:
        rt = _make_runtime()
        cgc_ctx = _make_context("/fallback/repo")
        cap = CGCCapability(runtime=rt, context=cgc_ctx)
        fn = cap.get_instructions()
        # deps.cgc_context is None → should fall back to capability's context
        run_ctx = _make_ctx(cgc_context=None)
        result = await fn(run_ctx)
        assert result is not None
        assert "/fallback/repo" in result

    async def test_deps_context_takes_precedence(self) -> None:
        rt = _make_runtime()
        cap_ctx = _make_context("/cap/repo")
        cap = CGCCapability(runtime=rt, context=cap_ctx)
        fn = cap.get_instructions()
        deps_ctx = _make_context("/deps/repo")
        run_ctx = _make_ctx(cgc_context=deps_ctx)
        result = await fn(run_ctx)
        assert result is not None
        assert "/deps/repo" in result


# ── build_cgc_capability tests ────────────────────────────────────────────────


class TestBuildCGCCapability:
    async def test_success_with_explicit_repo_path(self) -> None:
        from apps.cli.code_graph.cgc_setup import build_cgc_capability

        with patch(
            "pydantic_deep.toolsets.code_graph.cgc.runtime.CGCRuntime"
        ) as mock_rt_cls:
            mock_rt_cls.return_value = MagicMock(spec=CGCRuntime)
            cap = await build_cgc_capability(repo_path="/explicit/repo")

        assert cap is not None
        assert isinstance(cap, CGCCapability)
        assert cap.context is not None
        assert cap.context.repo_path == "/explicit/repo"
        assert cap.get_toolset() is not None

    async def test_success_with_root_fallback(self) -> None:
        from apps.cli.code_graph.cgc_setup import build_cgc_capability

        root = Path("/from/root")
        with patch(
            "pydantic_deep.toolsets.code_graph.cgc.runtime.CGCRuntime"
        ) as mock_rt_cls:
            mock_rt_cls.return_value = MagicMock(spec=CGCRuntime)
            cap = await build_cgc_capability(repo_path=None, root=root)

        assert cap is not None
        assert cap.context is not None
        assert cap.context.repo_path == str(root.resolve())

    async def test_returns_none_when_no_path(self) -> None:
        from apps.cli.code_graph.cgc_setup import build_cgc_capability

        cap = await build_cgc_capability(repo_path=None, root=None)
        assert cap is None

    async def test_on_status_callback(self) -> None:
        from apps.cli.code_graph.cgc_setup import build_cgc_capability

        messages: list[str] = []
        with patch(
            "pydantic_deep.toolsets.code_graph.cgc.runtime.CGCRuntime"
        ) as mock_rt_cls:
            mock_rt_cls.return_value = MagicMock(spec=CGCRuntime)
            await build_cgc_capability(
                repo_path="/r", on_status=messages.append
            )

        assert len(messages) == 1
        assert "/r" in messages[0]

    async def test_returns_none_on_import_error(self, capsys) -> None:
        from apps.cli.code_graph.cgc_setup import build_cgc_capability

        # Patch CGCRuntime in its source module so the local import in
        # build_cgc_capability (from ... import CGCRuntime) gets the mock.
        with patch(
            "pydantic_deep.toolsets.code_graph.cgc.runtime.CGCRuntime",
            side_effect=ImportError("codegraphcontext not installed"),
        ):
            cap = await build_cgc_capability(repo_path="/r")

        assert cap is None
        captured = capsys.readouterr()
        assert "[cgc]" in captured.err

    async def test_returns_none_on_exception(self, capsys) -> None:
        from apps.cli.code_graph.cgc_setup import build_cgc_capability

        with patch(
            "pydantic_deep.toolsets.code_graph.cgc.runtime.CGCRuntime",
            side_effect=RuntimeError("unexpected"),
        ):
            cap = await build_cgc_capability(repo_path="/r")

        assert cap is None
        captured = capsys.readouterr()
        assert "[cgc]" in captured.err


# ── DeepAgentDeps.cgc_context integration ─────────────────────────────────────


class TestDeepAgentDepsCGCContext:
    def test_cgc_context_defaults_to_none(self) -> None:
        from pydantic_deep.deps import DeepAgentDeps

        deps = DeepAgentDeps()
        assert deps.cgc_context is None

    def test_cgc_context_clone_propagates(self) -> None:
        from pydantic_deep.deps import DeepAgentDeps

        cgc_ctx = CGCContext(repo_path="/r")
        deps = DeepAgentDeps(cgc_context=cgc_ctx)
        clone = deps.clone_for_subagent()
        assert clone.cgc_context is cgc_ctx

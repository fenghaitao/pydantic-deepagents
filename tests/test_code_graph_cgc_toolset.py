"""Tests for pydantic_deep.toolsets.code_graph.cgc_toolset.CGCToolset."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext

from pydantic_deep.toolsets.code_graph.cgc_context import CGCContext
from pydantic_deep.toolsets.code_graph.cgc_toolset import CGCToolset


def _make_runtime(
    repos: dict | None = None,
    find_result: dict | None = None,
    analyze_result: dict | None = None,
    cypher_result: dict | None = None,
) -> MagicMock:
    rt = MagicMock()
    rt.list_repositories = AsyncMock(return_value=repos or {"repositories": []})
    rt.find_code = AsyncMock(return_value=find_result or {"results": []})
    rt.analyze_relationships = AsyncMock(
        return_value=analyze_result or {"results": []}
    )
    rt.execute_cypher = AsyncMock(return_value=cypher_result or {"results": []})
    return rt


def _make_ctx(cgc_context: CGCContext | None = None) -> RunContext:
    ctx = MagicMock(spec=RunContext)
    ctx.deps = MagicMock()
    ctx.deps.cgc_context = cgc_context
    return ctx


class TestCGCToolsetInit:
    def test_creates_expected_tools(self) -> None:
        rt = _make_runtime()
        ts = CGCToolset(runtime=rt)
        assert "list_code_projects" in ts.tools
        assert "find_code" in ts.tools
        assert "analyze_code_relationships" in ts.tools
        assert "execute_cypher_query" in ts.tools

    def test_default_repo_path_none(self) -> None:
        rt = _make_runtime()
        ts = CGCToolset(runtime=rt)
        assert ts._repo_path is None  # pyright: ignore[reportPrivateUsage]

    def test_custom_repo_path(self) -> None:
        rt = _make_runtime()
        ts = CGCToolset(runtime=rt, repo_path="/my/repo")
        assert ts._repo_path == "/my/repo"  # pyright: ignore[reportPrivateUsage]


class TestListCodeProjects:
    async def test_returns_json(self) -> None:
        repos = {"repositories": [{"path": "/r", "files": 10}]}
        rt = _make_runtime(repos=repos)
        ts = CGCToolset(runtime=rt)
        result = await ts.tools["list_code_projects"].function(_make_ctx())
        assert json.loads(result) == repos

    async def test_returns_empty_repos(self) -> None:
        rt = _make_runtime(repos={"repositories": []})
        ts = CGCToolset(runtime=rt)
        result = await ts.tools["list_code_projects"].function(_make_ctx())
        data = json.loads(result)
        assert data["repositories"] == []


class TestFindCode:
    async def test_returns_json(self) -> None:
        rt = _make_runtime(find_result={"results": [{"file": "foo.py", "line": 1}]})
        ts = CGCToolset(runtime=rt, repo_path="/r")
        ctx = _make_ctx()
        result = await ts.tools["find_code"].function(ctx, query="foo")
        data = json.loads(result)
        assert data["results"][0]["file"] == "foo.py"
        rt.find_code.assert_called_once_with(
            query="foo", repo_path="/r", fuzzy_search=False
        )

    async def test_passes_fuzzy_search(self) -> None:
        rt = _make_runtime()
        ts = CGCToolset(runtime=rt, repo_path="/r")
        ctx = _make_ctx()
        await ts.tools["find_code"].function(ctx, query="bar", fuzzy_search=True)
        rt.find_code.assert_called_once_with(
            query="bar", repo_path="/r", fuzzy_search=True
        )

    async def test_no_repo_path(self) -> None:
        rt = _make_runtime()
        ts = CGCToolset(runtime=rt)
        ctx = _make_ctx()
        await ts.tools["find_code"].function(ctx, query="baz")
        rt.find_code.assert_called_once_with(
            query="baz", repo_path=None, fuzzy_search=False
        )


class TestAnalyzeCodeRelationships:
    async def test_returns_json(self) -> None:
        rt = _make_runtime(analyze_result={"callers": ["f1", "f2"]})
        ts = CGCToolset(runtime=rt, repo_path="/r")
        ctx = _make_ctx()
        result = await ts.tools["analyze_code_relationships"].function(
            ctx, query_type="find_callers", target="my_func"
        )
        data = json.loads(result)
        assert data["callers"] == ["f1", "f2"]
        rt.analyze_relationships.assert_called_once_with(
            query_type="find_callers",
            target="my_func",
            context=None,
            repo_path="/r",
        )

    async def test_passes_context(self) -> None:
        rt = _make_runtime()
        ts = CGCToolset(runtime=rt, repo_path="/r")
        ctx = _make_ctx()
        await ts.tools["analyze_code_relationships"].function(
            ctx, query_type="find_callers", target="f", context="src/foo.py"
        )
        rt.analyze_relationships.assert_called_once_with(
            query_type="find_callers",
            target="f",
            context="src/foo.py",
            repo_path="/r",
        )


class TestExecuteCypherQuery:
    async def test_returns_json(self) -> None:
        rt = _make_runtime(cypher_result={"results": [{"n": "node1"}]})
        ts = CGCToolset(runtime=rt)
        ctx = _make_ctx()
        result = await ts.tools["execute_cypher_query"].function(
            ctx, cypher_query="MATCH (n) RETURN n"
        )
        data = json.loads(result)
        assert data["results"][0]["n"] == "node1"
        rt.execute_cypher.assert_called_once_with("MATCH (n) RETURN n")


class TestGetInstructions:
    async def test_instructions_with_repo_path(self) -> None:
        rt = _make_runtime()
        ts = CGCToolset(runtime=rt, repo_path="/my/repo")
        ctx = _make_ctx()
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert len(parts) == 1
        assert "/my/repo" in parts[0]
        assert "find_code" in parts[0]

    async def test_instructions_without_repo_path(self) -> None:
        rt = _make_runtime()
        ts = CGCToolset(runtime=rt)
        ctx = _make_ctx()
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "list_code_projects" in parts[0]

    async def test_instructions_uses_cgc_context(self) -> None:
        rt = _make_runtime()
        ts = CGCToolset(runtime=rt)  # no repo_path on toolset
        cgc_ctx = CGCContext(repo_path="/from/context")
        ctx = _make_ctx(cgc_context=cgc_ctx)
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "/from/context" in parts[0]

    async def test_instructions_toolset_path_overridden_by_context(self) -> None:
        # When both context and toolset repo_path are set, context wins
        rt = _make_runtime()
        ts = CGCToolset(runtime=rt, repo_path="/toolset/repo")
        cgc_ctx = CGCContext(repo_path="/context/repo")
        ctx = _make_ctx(cgc_context=cgc_ctx)
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "/context/repo" in parts[0]

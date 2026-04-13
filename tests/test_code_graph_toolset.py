"""Tests for pydantic_deep.toolsets.code_graph.toolset.CodeGraphToolset."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext

from pydantic_deep.toolsets.code_graph.toolset import CodeGraphToolset


def _make_backend(
    projects: list | None = None,
    search_result: list | None = None,
    nl_result: dict | None = None,
    kg_result: list | None = None,
) -> MagicMock:
    b = AsyncMock()
    b.list_projects = AsyncMock(return_value=projects or [])
    b.search = AsyncMock(return_value=search_result or [])
    b.nl_query = AsyncMock(return_value=nl_result or {})
    b.kg_search = AsyncMock(return_value=kg_result or [])
    return b


def _make_ctx(potpie=None) -> RunContext:
    ctx = MagicMock(spec=RunContext)
    ctx.deps = MagicMock()
    ctx.deps.potpie = potpie
    return ctx


class TestCodeGraphToolsetInit:
    def test_creates_with_backend(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b)
        assert "list_code_projects" in ts.tools
        assert "search_codebase" in ts.tools
        assert "query_code_graph" in ts.tools
        assert "ask_knowledge_graph" in ts.tools

    def test_default_project_id_none(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b)
        assert ts._project_id is None  # pyright: ignore[reportPrivateUsage]

    def test_custom_project_id(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b, project_id="proj-1")
        assert ts._project_id == "proj-1"  # pyright: ignore[reportPrivateUsage]


class TestListCodeProjects:
    async def test_returns_json_when_projects_exist(self) -> None:
        projects = [{"id": "p1", "repo_name": "myrepo"}]
        b = _make_backend(projects=projects)
        ts = CodeGraphToolset(backend=b)
        ctx = _make_ctx()
        result = await ts.tools["list_code_projects"].function(ctx)
        data = json.loads(result)
        assert data[0]["id"] == "p1"

    async def test_returns_message_when_no_projects(self) -> None:
        b = _make_backend(projects=[])
        ts = CodeGraphToolset(backend=b)
        ctx = _make_ctx()
        result = await ts.tools["list_code_projects"].function(ctx)
        assert "No projects" in result


class TestSearchCodebase:
    async def test_returns_results(self) -> None:
        b = _make_backend(search_result=[{"file": "foo.py"}])
        ts = CodeGraphToolset(backend=b, project_id="p1")
        ctx = _make_ctx()
        result = await ts.tools["search_codebase"].function(ctx, query="foo")
        data = json.loads(result)
        assert data[0]["file"] == "foo.py"

    async def test_returns_no_results_message(self) -> None:
        b = _make_backend(search_result=[])
        ts = CodeGraphToolset(backend=b, project_id="p1")
        ctx = _make_ctx()
        result = await ts.tools["search_codebase"].function(ctx, query="xyz")
        assert "No results" in result

    async def test_no_project_id_returns_error(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b)
        ctx = _make_ctx()
        result = await ts.tools["search_codebase"].function(ctx, query="foo")
        assert "no project_id" in result


class TestQueryCodeGraph:
    async def test_returns_json(self) -> None:
        b = _make_backend(nl_result={"cypher_used": "MATCH...", "results": [], "count": 0})
        ts = CodeGraphToolset(backend=b, project_id="p1")
        ctx = _make_ctx()
        result = await ts.tools["query_code_graph"].function(ctx, question="what calls foo?")
        data = json.loads(result)
        assert "cypher_used" in data

    async def test_no_project_id_returns_error(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b)
        ctx = _make_ctx()
        result = await ts.tools["query_code_graph"].function(ctx, question="foo?")
        assert "no project_id" in result


class TestAskKnowledgeGraph:
    async def test_returns_results(self) -> None:
        b = _make_backend(kg_result=[{"node": "A", "score": 0.9}])
        ts = CodeGraphToolset(backend=b, project_id="p1")
        ctx = _make_ctx()
        result = await ts.tools["ask_knowledge_graph"].function(
            ctx, questions=["find auth"]
        )
        data = json.loads(result)
        assert data[0]["node"] == "A"

    async def test_returns_no_results_message(self) -> None:
        b = _make_backend(kg_result=[])
        ts = CodeGraphToolset(backend=b, project_id="p1")
        ctx = _make_ctx()
        result = await ts.tools["ask_knowledge_graph"].function(
            ctx, questions=["find auth"]
        )
        assert "No results" in result

    async def test_no_project_id_returns_error(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b)
        ctx = _make_ctx()
        result = await ts.tools["ask_knowledge_graph"].function(ctx, questions=["foo"])
        assert "no project_id" in result

    async def test_blocked_during_inferring(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b, project_id="p1")
        potpie = MagicMock()
        potpie.parsing_status = "INFERRING"
        potpie.project_id = "p1"
        ctx = _make_ctx(potpie=potpie)
        result = await ts.tools["ask_knowledge_graph"].function(
            ctx, questions=["find auth"]
        )
        assert "INFERRING" in result
        b.kg_search.assert_not_called()

    async def test_passes_node_ids(self) -> None:
        b = _make_backend(kg_result=[{"node": "B"}])
        ts = CodeGraphToolset(backend=b, project_id="p1")
        ctx = _make_ctx()
        await ts.tools["ask_knowledge_graph"].function(
            ctx, questions=["q"], node_ids=["n1"]
        )
        b.kg_search.assert_called_once_with("p1", ["q"], ["n1"])


class TestGetInstructions:
    async def test_with_project_id(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b, project_id="proj-1")
        ctx = _make_ctx()
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "proj-1" in parts[0]

    async def test_without_project_id(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b)
        ctx = _make_ctx()
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "list_code_projects" in parts[0]

    async def test_inferring_status_note(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b, project_id="proj-1")
        potpie = MagicMock()
        potpie.parsing_status = "INFERRING"
        ctx = _make_ctx(potpie=potpie)
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "INFERRING" in parts[0]

    async def test_parsing_status_note(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b, project_id="proj-1")
        potpie = MagicMock()
        potpie.parsing_status = "PARSING"
        ctx = _make_ctx(potpie=potpie)
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "PARSING" in parts[0]

    async def test_no_potpie_context(self) -> None:
        b = _make_backend()
        ts = CodeGraphToolset(backend=b, project_id="proj-1")
        ctx = _make_ctx(potpie=None)
        parts = await ts.get_instructions(ctx)
        assert parts is not None

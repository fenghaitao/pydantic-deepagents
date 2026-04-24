"""Tests for pydantic_deep.toolsets.code_graph.toolset.PotpieToolset."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext

from pydantic_deep.toolsets.code_graph.potpie.toolset import PotpieToolset


def _make_backend(
    projects: list | None = None,
    search_result: list | None = None,
    nl_result: dict | None = None,
    kg_result: list | None = None,
    analyze_reg_result: dict | None = None,
    list_reg_result: dict | None = None,
    list_cap_result: dict | None = None,
    analyze_cap_result: dict | None = None,
) -> MagicMock:
    b = AsyncMock()
    b.list_projects = AsyncMock(return_value=projects or [])
    b.search = AsyncMock(return_value=search_result or [])
    b.nl_query = AsyncMock(return_value=nl_result or {})
    b.kg_search = AsyncMock(return_value=kg_result or [])
    b.analyze_register_side_effect = AsyncMock(return_value=analyze_reg_result or {})
    b.list_register_side_effect = AsyncMock(return_value=list_reg_result or {})
    b.list_capability = AsyncMock(return_value=list_cap_result or {})
    b.analyze_capability = AsyncMock(return_value=analyze_cap_result or {})
    return b


def _make_ctx(kg_context=None) -> RunContext:
    ctx = MagicMock(spec=RunContext)
    ctx.deps = MagicMock()
    ctx.deps.kg_context = kg_context
    return ctx


class TestPotpieToolsetInit:
    def test_creates_with_backend(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b)
        assert "list_code_projects" in ts.tools
        assert "search_codebase" in ts.tools
        assert "nl_query" in ts.tools
        assert "ask_knowledge_graph" in ts.tools

    def test_default_project_id_none(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b)
        assert ts._project_id is None  # pyright: ignore[reportPrivateUsage]

    def test_custom_project_id(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b, project_id="proj-1")
        assert ts._project_id == "proj-1"  # pyright: ignore[reportPrivateUsage]


class TestListCodeProjects:
    async def test_returns_json_when_projects_exist(self) -> None:
        projects = [{"id": "p1", "repo_name": "myrepo"}]
        b = _make_backend(projects=projects)
        ts = PotpieToolset(runtime=b)
        ctx = _make_ctx()
        result = await ts.tools["list_code_projects"].function(ctx)
        data = json.loads(result)
        assert data[0]["id"] == "p1"

    async def test_returns_message_when_no_projects(self) -> None:
        b = _make_backend(projects=[])
        ts = PotpieToolset(runtime=b)
        ctx = _make_ctx()
        result = await ts.tools["list_code_projects"].function(ctx)
        assert "No projects" in result


class TestSearchCodebase:
    async def test_returns_results(self) -> None:
        b = _make_backend(search_result=[{"file": "foo.py"}])
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        result = await ts.tools["search_codebase"].function(ctx, query="foo")
        data = json.loads(result)
        assert data[0]["file"] == "foo.py"

    async def test_returns_no_results_message(self) -> None:
        b = _make_backend(search_result=[])
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        result = await ts.tools["search_codebase"].function(ctx, query="xyz")
        assert "No results" in result

    async def test_no_project_id_returns_error(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b)
        ctx = _make_ctx()
        result = await ts.tools["search_codebase"].function(ctx, query="foo")
        assert "no project_id" in result


class TestQueryCodeGraph:
    async def test_returns_json(self) -> None:
        b = _make_backend(nl_result={"cypher_used": "MATCH...", "results": [], "count": 0})
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        result = await ts.tools["nl_query"].function(ctx, question="what calls foo?")
        data = json.loads(result)
        assert "cypher_used" in data

    async def test_no_project_id_returns_error(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b)
        ctx = _make_ctx()
        result = await ts.tools["nl_query"].function(ctx, question="foo?")
        assert "no project_id" in result


class TestAskKnowledgeGraph:
    async def test_returns_results(self) -> None:
        b = _make_backend(kg_result=[{"node": "A", "score": 0.9}])
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        result = await ts.tools["ask_knowledge_graph"].function(
            ctx, questions=["find auth"]
        )
        data = json.loads(result)
        assert data[0]["node"] == "A"

    async def test_returns_no_results_message(self) -> None:
        b = _make_backend(kg_result=[])
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        result = await ts.tools["ask_knowledge_graph"].function(
            ctx, questions=["find auth"]
        )
        assert "No results" in result

    async def test_no_project_id_returns_error(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b)
        ctx = _make_ctx()
        result = await ts.tools["ask_knowledge_graph"].function(ctx, questions=["foo"])
        assert "no project_id" in result

    async def test_blocked_during_inferring(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b, project_id="p1")
        kg_context = MagicMock()
        kg_context.parsing_status = "INFERRING"
        kg_context.project_id = "p1"
        ctx = _make_ctx(kg_context=kg_context)
        result = await ts.tools["ask_knowledge_graph"].function(
            ctx, questions=["find auth"]
        )
        assert "INFERRING" in result
        b.kg_search.assert_not_called()

    async def test_passes_node_ids(self) -> None:
        b = _make_backend(kg_result=[{"node": "B"}])
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        await ts.tools["ask_knowledge_graph"].function(
            ctx, questions=["q"], node_ids=["n1"]
        )
        b.kg_search.assert_called_once_with("p1", ["q"], ["n1"])


class TestGetInstructions:
    async def test_with_project_id(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b, project_id="proj-1")
        ctx = _make_ctx()
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "proj-1" in parts[0]

    async def test_without_project_id(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b)
        ctx = _make_ctx()
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "list_code_projects" in parts[0]

    async def test_inferring_status_note(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b, project_id="proj-1")
        kg_context = MagicMock()
        kg_context.parsing_status = "INFERRING"
        ctx = _make_ctx(kg_context=kg_context)
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "INFERRING" in parts[0]

    async def test_parsing_status_note(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b, project_id="proj-1")
        kg_context = MagicMock()
        kg_context.parsing_status = "PARSING"
        ctx = _make_ctx(kg_context=kg_context)
        parts = await ts.get_instructions(ctx)
        assert parts is not None
        assert "PARSING" in parts[0]

    async def test_no_potpie_context(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b, project_id="proj-1")
        ctx = _make_ctx(kg_context=None)
        parts = await ts.get_instructions(ctx)
        assert parts is not None


class TestAnalyzeRegisterSideEffect:
    async def test_returns_json(self) -> None:
        result = {"device_name": "my_dev", "done": 5, "total_registers": 5}
        b = _make_backend(analyze_reg_result=result)
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        out = await ts.tools["analyze_register_side_effect"].function(
            ctx, device_name="my_dev"
        )
        data = json.loads(out)
        assert data["device_name"] == "my_dev"
        assert data["done"] == 5

    async def test_no_project_id_returns_error(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b)
        ctx = _make_ctx()
        out = await ts.tools["analyze_register_side_effect"].function(
            ctx, device_name="dev"
        )
        assert "no project_id" in out

    async def test_passes_refresh_and_batch(self) -> None:
        b = _make_backend(analyze_reg_result={"done": 0})
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        await ts.tools["analyze_register_side_effect"].function(
            ctx, device_name="dev", refresh=True, batch_size=10, chunk_tokens=5000
        )
        b.analyze_register_side_effect.assert_called_once_with(
            project_id="p1",
            device_name="dev",
            refresh=True,
            batch_size=10,
            chunk_tokens=5000,
        )

    async def test_project_id_from_kg_context(self) -> None:
        b = _make_backend(analyze_reg_result={"done": 1})
        ts = PotpieToolset(runtime=b)
        kg_context = MagicMock()
        kg_context.project_id = "ctx-proj"
        ctx = _make_ctx(kg_context=kg_context)
        await ts.tools["analyze_register_side_effect"].function(ctx, device_name="dev")
        b.analyze_register_side_effect.assert_called_once()
        call_kwargs = b.analyze_register_side_effect.call_args[1]
        assert call_kwargs["project_id"] == "ctx-proj"


class TestListRegisterSideEffect:
    async def test_returns_json(self) -> None:
        result = {
            "device_name": "my_dev",
            "banks": {"bank0": {"REG_A": {"write_side_effect": "sets flag"}}},
            "summary": {"total_banks": 1, "total_registers": 1},
        }
        b = _make_backend(list_reg_result=result)
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        out = await ts.tools["list_register_side_effect"].function(ctx, device_name="my_dev")
        data = json.loads(out)
        assert data["device_name"] == "my_dev"
        assert "bank0" in data["banks"]

    async def test_no_project_id_returns_error(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b)
        ctx = _make_ctx()
        out = await ts.tools["list_register_side_effect"].function(ctx, device_name="dev")
        assert "no project_id" in out

    async def test_passes_device_name(self) -> None:
        b = _make_backend(list_reg_result={"banks": {}})
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        await ts.tools["list_register_side_effect"].function(ctx, device_name="timer_dev")
        b.list_register_side_effect.assert_called_once_with(
            project_id="p1", device_name="timer_dev"
        )

    async def test_project_id_from_kg_context(self) -> None:
        b = _make_backend(list_reg_result={"banks": {}})
        ts = PotpieToolset(runtime=b)
        kg_context = MagicMock()
        kg_context.project_id = "ctx-proj"
        ctx = _make_ctx(kg_context=kg_context)
        await ts.tools["list_register_side_effect"].function(ctx, device_name="dev")
        call_kwargs = b.list_register_side_effect.call_args[1]
        assert call_kwargs["project_id"] == "ctx-proj"


class TestListCapability:
    async def test_returns_json(self) -> None:
        result = {
            "device_name": "my_dev",
            "cached": True,
            "generated": False,
            "capabilities": {"DMA": {"overview": "DMA engine"}},
        }
        b = _make_backend(list_cap_result=result)
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        out = await ts.tools["list_capability"].function(ctx, device_name="my_dev")
        data = json.loads(out)
        assert data["device_name"] == "my_dev"
        assert data["cached"] is True
        assert "DMA" in data["capabilities"]

    async def test_no_project_id_returns_error(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b)
        ctx = _make_ctx()
        out = await ts.tools["list_capability"].function(ctx, device_name="dev")
        assert "no project_id" in out

    async def test_passes_device_name(self) -> None:
        b = _make_backend(list_cap_result={"capabilities": {}})
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        await ts.tools["list_capability"].function(ctx, device_name="uart_dev")
        b.list_capability.assert_called_once_with(project_id="p1", device_name="uart_dev")

    async def test_project_id_from_kg_context(self) -> None:
        b = _make_backend(list_cap_result={"capabilities": {}})
        ts = PotpieToolset(runtime=b)
        kg_context = MagicMock()
        kg_context.project_id = "ctx-proj"
        ctx = _make_ctx(kg_context=kg_context)
        await ts.tools["list_capability"].function(ctx, device_name="dev")
        call_kwargs = b.list_capability.call_args[1]
        assert call_kwargs["project_id"] == "ctx-proj"


class TestAnalyzeCapability:
    async def test_returns_json(self) -> None:
        result = {
            "device_name": "my_dev",
            "project_id": "p1",
            "cached": False,
            "capabilities": [{"DMA": {"spec": "..."}}],
        }
        b = _make_backend(analyze_cap_result=result)
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        out = await ts.tools["analyze_capability"].function(ctx, device_name="my_dev")
        data = json.loads(out)
        assert data["device_name"] == "my_dev"
        assert data["cached"] is False

    async def test_no_project_id_returns_error(self) -> None:
        b = _make_backend()
        ts = PotpieToolset(runtime=b)
        ctx = _make_ctx()
        out = await ts.tools["analyze_capability"].function(ctx, device_name="dev")
        assert "no project_id" in out

    async def test_passes_refresh_and_chunk_tokens(self) -> None:
        b = _make_backend(analyze_cap_result={"capabilities": []})
        ts = PotpieToolset(runtime=b, project_id="p1")
        ctx = _make_ctx()
        await ts.tools["analyze_capability"].function(
            ctx, device_name="dev", refresh=True, chunk_tokens=8000
        )
        b.analyze_capability.assert_called_once_with(
            project_id="p1",
            device_name="dev",
            refresh=True,
            chunk_tokens=8000,
        )

    async def test_project_id_from_kg_context(self) -> None:
        b = _make_backend(analyze_cap_result={"capabilities": []})
        ts = PotpieToolset(runtime=b)
        kg_context = MagicMock()
        kg_context.project_id = "ctx-proj"
        ctx = _make_ctx(kg_context=kg_context)
        await ts.tools["analyze_capability"].function(ctx, device_name="dev")
        call_kwargs = b.analyze_capability.call_args[1]
        assert call_kwargs["project_id"] == "ctx-proj"

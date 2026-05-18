"""Tests for CodeGraphMCPCapability (prefix + project_id injection)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.capabilities.abstract import AbstractCapability, RawToolArgs
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.usage import RunUsage

from pydantic_deep.capabilities.code_graph_mcp import CodeGraphMCPCapability

TEST_MODEL = TestModel()


def _ctx() -> RunContext[Any]:
    return RunContext(deps=None, model=TEST_MODEL, usage=RunUsage())


def _td(
    name: str,
    *,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> ToolDefinition:
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = required
    return ToolDefinition(name=name, description="test", parameters_json_schema=schema)


def _call(name: str = "potpie_foo", call_id: str = "c1") -> ToolCallPart:
    return ToolCallPart(tool_name=name, args={}, tool_call_id=call_id)


def _make_cap(
    prefix: str = "potpie",
    project_id: str | None = "test-project",
) -> CodeGraphMCPCapability[Any]:
    """Build a CodeGraphMCPCapability with a mock wrapped capability."""
    mock_wrapped = AsyncMock(spec=AbstractCapability)
    # before_tool_validate just returns args as-is
    mock_wrapped.before_tool_validate = AsyncMock(side_effect=lambda ctx, *, call, tool_def, args: args)
    cap = CodeGraphMCPCapability(wrapped=mock_wrapped, prefix=prefix, project_id=project_id)
    return cap


class TestPrepareTools:
    """Tests for prepare_tools (schema stripping)."""

    async def test_no_project_id_returns_tools_unchanged(self):
        cap = _make_cap(project_id=None)
        td = _td("potpie_query", properties={"project_id": {"type": "string"}})
        result = await cap.prepare_tools(_ctx(), [td])
        assert result == [td]

    async def test_strips_project_id_from_prefixed_tool(self):
        cap = _make_cap(project_id="proj-123")
        td = _td(
            "potpie_query",
            properties={"project_id": {"type": "string"}, "query": {"type": "string"}},
            required=["project_id", "query"],
        )
        result = await cap.prepare_tools(_ctx(), [td])
        assert len(result) == 1
        props = result[0].parameters_json_schema["properties"]
        assert "project_id" not in props
        assert "query" in props
        assert "project_id" not in result[0].parameters_json_schema.get("required", [])

    async def test_does_not_strip_from_non_prefixed_tool(self):
        cap = _make_cap(prefix="potpie", project_id="proj-123")
        td = _td(
            "other_query",
            properties={"project_id": {"type": "string"}},
            required=["project_id"],
        )
        result = await cap.prepare_tools(_ctx(), [td])
        assert "project_id" in result[0].parameters_json_schema["properties"]

    async def test_does_not_strip_when_no_project_id_property(self):
        cap = _make_cap(project_id="proj-123")
        td = _td("potpie_list", properties={"limit": {"type": "integer"}})
        result = await cap.prepare_tools(_ctx(), [td])
        assert result[0].parameters_json_schema == td.parameters_json_schema

    async def test_handles_multiple_tools(self):
        cap = _make_cap(project_id="proj-123")
        tds = [
            _td("potpie_a", properties={"project_id": {"type": "string"}}),
            _td("potpie_b", properties={"name": {"type": "string"}}),
            _td("other_c", properties={"project_id": {"type": "string"}}),
        ]
        result = await cap.prepare_tools(_ctx(), tds)
        assert len(result) == 3
        # potpie_a: stripped
        assert "project_id" not in result[0].parameters_json_schema["properties"]
        # potpie_b: no project_id to strip
        assert "name" in result[1].parameters_json_schema["properties"]
        # other_c: wrong prefix, not stripped
        assert "project_id" in result[2].parameters_json_schema["properties"]


class TestBeforeToolValidate:
    """Tests for before_tool_validate (project_id injection)."""

    async def test_injects_project_id_dict_args(self):
        cap = _make_cap(project_id="proj-123")
        td = _td("potpie_query")
        args: RawToolArgs = {"query": "hello"}
        result = await cap.before_tool_validate(
            _ctx(), call=_call("potpie_query"), tool_def=td, args=args
        )
        assert isinstance(result, dict)
        assert result["project_id"] == "proj-123"
        assert result["query"] == "hello"

    async def test_injects_project_id_string_args(self):
        cap = _make_cap(project_id="proj-123")
        td = _td("potpie_query")
        args: RawToolArgs = json.dumps({"query": "hello"})
        result = await cap.before_tool_validate(
            _ctx(), call=_call("potpie_query"), tool_def=td, args=args
        )
        parsed = json.loads(result)  # type: ignore[arg-type]
        assert parsed["project_id"] == "proj-123"
        assert parsed["query"] == "hello"

    async def test_does_not_overwrite_existing_project_id(self):
        cap = _make_cap(project_id="proj-123")
        td = _td("potpie_query")
        args: RawToolArgs = {"project_id": "user-provided", "query": "hello"}
        result = await cap.before_tool_validate(
            _ctx(), call=_call("potpie_query"), tool_def=td, args=args
        )
        assert isinstance(result, dict)
        assert result["project_id"] == "user-provided"

    async def test_no_injection_without_project_id(self):
        cap = _make_cap(project_id=None)
        td = _td("potpie_query")
        args: RawToolArgs = {"query": "hello"}
        result = await cap.before_tool_validate(
            _ctx(), call=_call("potpie_query"), tool_def=td, args=args
        )
        assert isinstance(result, dict)
        assert "project_id" not in result

    async def test_no_injection_for_non_prefixed_tool(self):
        cap = _make_cap(prefix="potpie", project_id="proj-123")
        td = _td("other_query")
        args: RawToolArgs = {"query": "hello"}
        result = await cap.before_tool_validate(
            _ctx(), call=_call("other_query"), tool_def=td, args=args
        )
        assert isinstance(result, dict)
        assert "project_id" not in result


class TestBackwardCompat:
    """Test backward compatibility alias."""

    def test_potpie_mcp_capability_alias(self):
        from pydantic_deep.capabilities.code_graph_mcp import PotpieMCPCapability

        assert PotpieMCPCapability is CodeGraphMCPCapability

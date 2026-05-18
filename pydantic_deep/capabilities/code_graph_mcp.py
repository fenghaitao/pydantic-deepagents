"""CodeGraphMCPCapability — PrefixTools + auto-inject project_id for code-graph MCP servers."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities.abstract import RawToolArgs
from pydantic_ai.capabilities.prefix_tools import PrefixTools
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import AgentDepsT, RunContext, ToolDefinition


@dataclass
class CodeGraphMCPCapability(PrefixTools[AgentDepsT]):
    """Wraps an MCP capability with tool-name prefixing and automatic project_id injection.

    Combines:
    - PrefixTools: prefixes all wrapped tool names (e.g. ``list_projects`` → ``potpie_list_projects``)
    - project_id injection: for any tool whose schema declares a ``project_id`` property,
      automatically fills it from ``self.project_id`` if the caller didn't provide one.
    - Schema stripping: removes ``project_id`` from tool schemas visible to the LLM so
      the model doesn't ask the user for it or hallucinate a value.

    Usage::

        from pydantic_ai.capabilities import MCP
        from pydantic_deep.capabilities.code_graph_mcp import CodeGraphMCPCapability

        cap = CodeGraphMCPCapability(
            wrapped=MCP(url="http://127.0.0.1:13100/sse"),
            prefix="potpie",
            project_id="my-project-uuid",
        )
        agent = create_deep_agent(capabilities=[cap])
    """

    project_id: str | None = field(default=None)

    async def prepare_tools(
        self,
        ctx: RunContext[AgentDepsT],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """Strip project_id from tool schemas so the LLM doesn't need to provide it."""
        if not self.project_id:
            return tool_defs

        result: list[ToolDefinition] = []
        for td in tool_defs:
            if (
                td.name.startswith(f"{self.prefix}_")
                and "project_id" in td.parameters_json_schema.get("properties", {})
            ):
                # Deep-copy and remove project_id from the schema
                new_schema = copy.deepcopy(td.parameters_json_schema)
                new_schema.get("properties", {}).pop("project_id", None)
                required = new_schema.get("required", [])
                if "project_id" in required:
                    required.remove("project_id")
                # Create a modified ToolDefinition
                td = ToolDefinition(
                    name=td.name,
                    description=td.description,
                    parameters_json_schema=new_schema,
                    outer_typed_dict_key=td.outer_typed_dict_key,
                    strict=td.strict,
                    sequential=td.sequential,
                    kind=td.kind,
                )
            result.append(td)
        return result

    async def before_tool_validate(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: RawToolArgs,
    ) -> RawToolArgs:
        """Inject project_id into tool args if the tool accepts it and it's not already set."""
        if (
            self.project_id
            and tool_def.name.startswith(f"{self.prefix}_")
        ):
            # Always inject since we stripped it from the schema — the tool still requires it
            if isinstance(args, str):
                parsed = json.loads(args)
                parsed.setdefault("project_id", self.project_id)
                args = json.dumps(parsed)
            else:
                args = dict(args)
                args.setdefault("project_id", self.project_id)

        return await self.wrapped.before_tool_validate(
            ctx, call=call, tool_def=tool_def, args=args
        )


__all__ = ["CodeGraphMCPCapability"]

# Backward compatibility
PotpieMCPCapability = CodeGraphMCPCapability

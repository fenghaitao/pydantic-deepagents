"""CodeGraphCapability — pydantic-ai capability for code-graph/potpie integration.

Encapsulates all code-graph concerns (toolset, subagents, runtime context)
behind the standard AbstractCapability interface, following the same pattern
as MemoryCapability and other pydantic-deep capabilities.

Usage::

    from pydantic_deep.capabilities.code_graph import CodeGraphCapability
    from pydantic_deep.toolsets.code_graph.context import PotpieContext
    from pydantic_deep.toolsets.code_graph.runtime import CodeGraphRuntime

    runtime = CodeGraphRuntime()
    context = PotpieContext(project_id="abc-123", user_id="user1")
    cap = CodeGraphCapability(runtime=runtime, project_id="abc-123", context=context)

    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        extra_capabilities=[cap],
        subagents=cap.subagents,  # None until for_run() is called
    )
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset

from pydantic_deep.toolsets.code_graph import CodeGraphToolset, KG_TOOL_NAMES
from pydantic_deep.toolsets.code_graph.context import PotpieContext
from pydantic_deep.toolsets.code_graph.runtime import CodeGraphRuntime

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constants moved from subagents_potpie.py
# ---------------------------------------------------------------------------

_QNA_TOOL_NAMES: list[str] = [
    "get_code_from_multiple_node_ids",
    "get_node_neighbours_from_node_id",
    "get_code_from_probable_node_name",
    "ask_knowledge_graph_queries",
    "get_nodes_from_tags",
    "get_code_file_structure",
    "fetch_file",
    "fetch_files_batch",
]

_BLAST_RADIUS_TOOL_NAMES: list[str] = [
    "get_nodes_from_tags",
    "ask_knowledge_graph_queries",
    "get_code_from_multiple_node_ids",
    "change_detection",
    "fetch_file",
    "fetch_files_batch",
    "analyze_code_structure",
    "nl_cypher_query",
]

_CODEBASE_NAV_GUIDE = """\
## How to explore the codebase

1. Use `Ask_Knowledge_Graph_Queries` to locate where functionality resides (semantic search).
2. Use `Get_Code_and_docstring_From_Probable_Node_Name` for specific classes/functions.
3. Use `Get_Code_and_docstring_From_Multiple_Node_IDs` to fetch code from multiple nodes.
4. Use `Get_Node_Neighbours_From_Node_ID` to trace callers and callees.
5. Use `get_code_file_structure` to understand directory layout.
6. Use `fetch_file` / `fetch_files_batch` to read complete files.
7. Use `analyze_code_structure` to list all classes/functions in a file.
"""

_QNA_INSTRUCTIONS = f"""\
You are a Codebase Q&A Specialist. Provide comprehensive, well-structured answers
to questions about the codebase by systematically exploring code, understanding
context, and delivering thorough explanations grounded in actual code.

{_CODEBASE_NAV_GUIDE}
## Response format

- Use markdown with clear headings.
- Always cite file paths and line numbers.
- Include code snippets with language tags.
- Strip project-specific path prefixes — show only the relative path.
- Be thorough: explore before answering, verify completeness.
"""

_BLAST_RADIUS_INSTRUCTIONS = """\
You are a Blast Radius Analyzer. Analyse the impact of code changes on the rest
of the codebase and answer questions about those changes.

## How to analyse changes

1. Use `change_detection` to fetch the current code changes (diff).
2. Use `Ask_Knowledge_Graph_Queries` or `Query_Code_Graph_with_Natural_Language`
   to understand where changed code is used.
3. Use `Get_Code_and_docstring_From_Multiple_Node_IDs` to fetch changed code.
4. Use `Get_Node_Neighbours_From_Node_ID` to find all callers/consumers.
5. Use `fetch_file` / `fetch_files_batch` for full file context.
6. Use `analyze_code_structure` to list all nodes in affected files.

## Response format

Provide a structured impact analysis:
1. **Direct changes** — which functions/classes were modified.
2. **Indirect effects** — downstream callers, consumers, APIs affected.
3. **Critical areas** — components requiring careful testing.
4. **Recommendations** — refactoring or additional changes to mitigate risk.

Be specific: name the affected files, functions, and APIs.
"""


# ---------------------------------------------------------------------------
# CodeGraphCapability
# ---------------------------------------------------------------------------


@dataclass
class CodeGraphCapability(AbstractCapability[Any]):
    """Capability encapsulating all code-graph/potpie concerns.

    Builds the CodeGraphToolset and subagent configs lazily in ``for_run()``,
    injects ``kg_context`` into deps via ``before_run()``, and exposes a
    ``subagents`` property for wiring into ``create_cli_agent()``.

    Args:
        runtime: Initialised CodeGraphRuntime.
        project_id: Default project UUID (optional).
        context: PotpieContext for the current session (optional).
    """

    runtime: CodeGraphRuntime
    project_id: str | None = None
    context: PotpieContext | None = None
    _toolset: FunctionToolset[Any] | None = field(default=None, init=False, repr=False)
    _subagents: list[Any] | None = field(default=None, init=False, repr=False)

    async def before_run(self, ctx: RunContext[Any]) -> None:
        """Inject kg_context into deps before each run.

        Sets ``ctx.deps.kg_context`` to ``self.context`` so that
        CodeGraphToolset tool functions can read the project_id.

        Args:
            ctx: The current run context.
        """
        ctx.deps.kg_context = self.context

    def get_toolset(self) -> AbstractToolset[Any] | None:
        """Return the built toolset, or None if for_run() has not been called."""
        return self._toolset

    def get_instructions(self) -> Callable[[RunContext[Any]], Any]:
        """Return an async callable that produces KG usage guidance.

        The callable reads ``ctx.deps.kg_context`` to include project-specific
        status information in the guidance string.

        Returns:
            An async callable accepting RunContext and returning a str or None.
        """
        context = self.context

        async def _instructions(ctx: RunContext[Any]) -> str | None:
            kg_context = getattr(ctx.deps, "kg_context", None) or context
            project_id = getattr(kg_context, "project_id", None) if kg_context else None
            parsing_status = getattr(kg_context, "parsing_status", None) if kg_context else None

            is_inferring = parsing_status == "INFERRING"
            is_parsing = parsing_status in ("PARSING", "SUBMITTED")

            if project_id:
                status_note = ""
                if is_inferring:
                    status_note = (
                        "\n\n> **Note:** Project is in INFERRING state — embeddings are being built. "
                        "`ask_knowledge_graph` is unavailable. Use `nl_query` instead."
                    )
                elif is_parsing:
                    status_note = (
                        f"\n\n> **Note:** Project is still being parsed (status: "
                        f"{parsing_status}). Graph queries may return incomplete results."
                    )
                return (
                    f"## Code Graph\n\n"
                    f"Default project ID: `{project_id}`\n\n"
                    "You have access to code-graph tools (`nl_query`, "
                    "`ask_knowledge_graph`, `search_codebase`, `list_code_projects`) "
                    "to answer questions about the indexed codebase.\n"
                    "Use `nl_query` for structural/relational questions "
                    "(call graphs, imports, inheritance). "
                    "Use `ask_knowledge_graph` for semantic/behaviour questions."
                    + status_note
                )
            return (
                "## Code Graph\n\n"
                "You have access to code-graph tools. Use `list_code_projects` "
                "to discover available project IDs, then pass the relevant ID "
                "to `nl_query`, `ask_knowledge_graph`, or `search_codebase`."
            )

        return _instructions

    @property
    def subagents(self) -> list[Any] | None:
        """Return the list of SubAgentConfig dicts, or None before for_run()."""
        return self._subagents


__all__ = ["CodeGraphCapability"]

"""Potpie system agents expressed as pydantic-deep SubAgentConfig entries.

Each agent wraps a potpie system agent's role/goal/backstory/task prompt and
tool list into a SubAgentConfig that can be passed to create_deep_agent() or
create_cli_agent() via the subagents= parameter.

Usage::

    from pydantic_deep.subagents_potpie import make_potpie_subagents
    from pydantic_deep.toolsets.code_graph.backend import PotpieBackend

    subagents = await make_potpie_subagents(backend, project_id, user_id)
    agent = create_deep_agent(subagents=subagents, ...)

Agents included:
    - codebase_qna    — answers questions about the codebase using the KG
    - blast_radius    — analyses impact of code changes (isolated mode)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_deep.toolsets.code_graph.backend import PotpieBackend

# ---------------------------------------------------------------------------
# Tool name lists (sourced from agent_factory.py / system agent files)
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
    "analyze_code_structure",
    "nl_cypher_query",
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

# ---------------------------------------------------------------------------
# Instructions (condensed from the original task prompts)
# ---------------------------------------------------------------------------

_QNA_INSTRUCTIONS = """\
You are a Codebase Q&A Specialist. Your goal is to provide comprehensive,
well-structured answers to questions about the codebase by systematically
exploring code, understanding context, and delivering thorough explanations
grounded in actual code.

## How to explore the codebase

1. Use `Ask_Knowledge_Graph_Queries` or `Query_Code_Graph_with_Natural_Language`
   to locate where functionality resides.
2. Use `Get_Code_and_docstring_From_Probable_Node_Name` for specific classes/functions.
3. Use `Get_Code_and_docstring_From_Multiple_Node_IDs` to fetch code from multiple nodes.
4. Use `Get_Node_Neighbours_From_Node_ID` to trace callers and callees.
5. Use `get_code_file_structure` to understand directory layout.
6. Use `fetch_file` / `fetch_files_batch` to read complete files.
7. Use `analyze_code_structure` to list all classes/functions in a file.

## Response format

- Use markdown with clear headings.
- Always cite file paths and line numbers.
- Include code snippets with language tags.
- Strip project-specific path prefixes — show only the relative path.
- Be thorough: explore before answering, verify completeness.
"""

_BLAST_RADIUS_INSTRUCTIONS = """\
You are a Blast Radius Analyzer. Your goal is to analyse the impact of code
changes on the rest of the codebase and answer questions about those changes.

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
# Factory
# ---------------------------------------------------------------------------


async def make_potpie_subagents(
    backend: PotpieBackend,
    project_id: str,
    user_id: str,
    exclude_embedding_tools: bool = False,
) -> list[Any]:
    """Build SubAgentConfig entries for the QnA and Blast Radius agents.

    Fetches the required StructuredTools from the backend, wraps them as
    pydantic-ai FunctionToolsets, and returns SubAgentConfig dicts ready
    to pass to create_deep_agent(subagents=...).

    Args:
        backend: Initialised PotpieBackend (RuntimeBackend required for
            get_tools(); RestBackend raises NotImplementedError).
        project_id: Active project UUID — injected into tool calls.
        user_id: User ID for ToolService access control.
        exclude_embedding_tools: Skip embedding-dependent tools (use when
            project is in INFERRING state).

    Returns:
        List of two SubAgentConfig dicts: [codebase_qna, blast_radius].
    """
    from apps.potpie.toolset import create_potpie_toolset

    qna_toolset = await create_potpie_toolset(
        backend=backend,
        tool_names=_QNA_TOOL_NAMES,
        toolset_id="potpie-qna",
        exclude_embedding_tools=exclude_embedding_tools,
    )

    blast_toolset = await create_potpie_toolset(
        backend=backend,
        tool_names=_BLAST_RADIUS_TOOL_NAMES,
        toolset_id="potpie-blast-radius",
        exclude_embedding_tools=exclude_embedding_tools,
    )

    codebase_qna: dict[str, Any] = {
        "name": "codebase_qna",
        "description": (
            "Answer questions about the codebase using the knowledge graph. "
            "Use for: 'What does X do?', 'How is Y implemented?', "
            "'Where is Z defined?', 'Which files import A?'"
        ),
        "instructions": _QNA_INSTRUCTIONS,
        "toolsets": [qna_toolset],
        # Shared context — benefits from full conversation history
        "include_filesystem": True,
    }

    blast_radius: dict[str, Any] = {
        "name": "blast_radius",
        "description": (
            "Analyse the blast radius of code changes — which functions, APIs, "
            "and consumers are affected by changes in the current branch. "
            "Use for: 'What is the impact of my changes?', "
            "'Which tests might break?', 'What depends on X?'"
        ),
        "instructions": _BLAST_RADIUS_INSTRUCTIONS,
        "toolsets": [blast_toolset],
        # Isolated — focused single-task analysis, no filesystem needed
        "include_filesystem": False,
    }

    return [codebase_qna, blast_radius]


__all__ = ["make_potpie_subagents"]

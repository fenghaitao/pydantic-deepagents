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
    - codebase_qna      — answers questions about the codebase using the KG
    - debugging         — systematic root-cause debugging
    - code_generation   — generates precise, copy-paste ready code changes
    - lld               — low-level design plans for new features
    - unit_test         — unit test plans and test code
    - integration_test  — integration test suites
    - blast_radius      — analyses impact of code changes (isolated mode)
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
]

_DEBUG_TOOL_NAMES: list[str] = [
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

_CODE_GEN_TOOL_NAMES: list[str] = [
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

_LLD_TOOL_NAMES: list[str] = [
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

_UNIT_TEST_TOOL_NAMES: list[str] = [
    "get_code_from_node_id",
    "get_code_from_probable_node_name",
    "fetch_file",
    "fetch_files_batch",
    "analyze_code_structure",
]

_INTEGRATION_TEST_TOOL_NAMES: list[str] = [
    "get_code_from_multiple_node_ids",
    "get_code_from_probable_node_name",
    "fetch_file",
    "fetch_files_batch",
    "analyze_code_structure",
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
# Instructions
# ---------------------------------------------------------------------------

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

_DEBUG_INSTRUCTIONS = f"""\
You are a Debugging and Code Analysis Specialist. Identify root causes, trace
code flows, and deliver precise fixes. For general queries, maintain a
conversational approach while grounding responses in code context.

{_CODEBASE_NAV_GUIDE}
## Debugging methodology

1. **Separate problem from suggested fix** — extract the symptom, find the real cause.
2. **Trace the complete flow** — upstream (origin) and downstream (consumers).
3. **Identify root cause** — state it explicitly before proposing a fix.
4. **Generalize** — fix the pattern, not just the symptom.
5. **Fix at source** — prevent bad state rather than handle it downstream.
6. **Verify** — confirm the fix covers all affected components.

## Response format

- Use markdown with clear headings.
- Cite file paths and line numbers.
- Show code snippets with language tags.
"""

_CODE_GEN_INSTRUCTIONS = f"""\
You are a Code Generation Specialist. Generate precise, copy-paste ready code
modifications that maintain project consistency and handle all dependencies.

{_CODEBASE_NAV_GUIDE}
## Code generation process

1. **Understand the task** — classify as new feature / modification / refactor / bug fix.
2. **Explore before writing** — collect naming conventions, indentation, import order,
   error handling patterns from existing code.
3. **Analyse dependencies** — identify all files impacted by the change.
4. **Plan, then implement** — order edits so dependencies are resolved first.
5. **Verify** — confirm the generated code matches existing patterns exactly.

## Rules

- Never create hypothetical files — only modify files confirmed to exist.
- Never skip dependent files — if a function signature changes, update all callers.
- Match existing formatting exactly; don't improve style unless asked.
- Provide required new imports in a separate code block.
- Output only the specific functions/classes being modified.
"""

_LLD_INSTRUCTIONS = f"""\
You are a Design Planner (Low-Level Design Specialist). Create detailed,
actionable design plans for implementing new features.

{_CODEBASE_NAV_GUIDE}
## Design plan format

Your plan must include:
1. **High-level overview** of the implementation approach.
2. **Detailed steps** for each file to be modified or created:
   - Specific files and proposed code changes.
   - New classes, methods, or functions needed.
3. **Potential challenges** and considerations.
4. **Consistency notes** — how to align with existing codebase patterns.

Use the KG tools to understand existing patterns before proposing changes.
"""

_UNIT_TEST_INSTRUCTIONS = """\
You are a Unit Test Expert. Create test plans and write unit tests based on
user requirements.

## How to explore the codebase

1. Use `Get_Code_and_docstring_From_Probable_Node_Name` for specific classes/functions.
2. Use `fetch_file` / `fetch_files_batch` to read complete files.
3. Use `analyze_code_structure` to list all classes/functions in a file.

## Process

1. **Analyse** the fetched code to understand functionality, inputs, outputs, side effects.
2. **Generate a test plan** covering:
   - Happy path scenarios
   - Edge cases (empty inputs, max values, type mismatches)
   - Error handling
3. **Write unit tests** using appropriate frameworks and best practices.
4. Include clear, descriptive test names and explanatory comments.

## Response format

- Format the test plan in two sections: "Happy Path" and "Edge Cases".
- Write complete, runnable test code.
"""

_INTEGRATION_TEST_INSTRUCTIONS = """\
You are an Integration Test Writer. Create comprehensive integration test suites
for the provided codebase.

## How to explore the codebase

1. Use `Get_Code_and_docstring_From_Multiple_Node_IDs` to fetch code from multiple nodes.
2. Use `Get_Code_and_docstring_From_Probable_Node_Name` for specific classes/functions.
3. Use `fetch_file` / `fetch_files_batch` to read complete files.
4. Use `analyze_code_structure` to list all classes/functions in a file.

## Process

1. **Analyse components** — understand purpose, inputs, outputs, interactions.
2. **Resolve imports** — determine correct import statements from the code graph.
3. **Generate a test plan** covering:
   - Happy path scenarios
   - Edge cases
   - Error handling
   - Major integration points between components
4. **Write integration tests** including:
   - Setup and teardown procedures
   - Mocking of external dependencies
   - Accurate imports
   - Descriptive test names and assertions

## Response format

- Format the test plan in two sections: "Happy Path" and "Edge Cases".
- Write complete, runnable test code.
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
# Factory
# ---------------------------------------------------------------------------


async def make_potpie_subagents(
    backend: PotpieBackend,
    user_id: str,
    exclude_embedding_tools: bool = False,
) -> list[Any]:
    """Build SubAgentConfig entries for all potpie system agents.

    Fetches the required StructuredTools from the backend, wraps them as
    pydantic-ai FunctionToolsets, and returns SubAgentConfig dicts ready
    to pass to create_deep_agent(subagents=...).

    Args:
        backend: Initialised PotpieBackend (RuntimeBackend required for
            get_tools(); RestBackend raises NotImplementedError).
        user_id: User ID for ToolService access control.
        exclude_embedding_tools: Skip embedding-dependent tools (use when
            project is in INFERRING state).

    Returns:
        List of SubAgentConfig dicts for all seven agents.
    """
    from pydantic_deep.toolsets.code_graph import CodeGraphToolset

    qna_ts = await CodeGraphToolset.from_runtime(
        backend=backend,
        tool_names=_QNA_TOOL_NAMES,
        toolset_id="potpie-qna",
        exclude_embedding_tools=exclude_embedding_tools,
    )
    # debug_ts = await CodeGraphToolset.from_runtime(
    #     backend=backend,
    #     tool_names=_DEBUG_TOOL_NAMES,
    #     toolset_id="potpie-debug",
    #     exclude_embedding_tools=exclude_embedding_tools,
    # )
    # codegen_ts = await CodeGraphToolset.from_runtime(
    #     backend=backend,
    #     tool_names=_CODE_GEN_TOOL_NAMES,
    #     toolset_id="potpie-codegen",
    #     exclude_embedding_tools=exclude_embedding_tools,
    # )
    # lld_ts = await CodeGraphToolset.from_runtime(
    #     backend=backend,
    #     tool_names=_LLD_TOOL_NAMES,
    #     toolset_id="potpie-lld",
    #     exclude_embedding_tools=exclude_embedding_tools,
    # )
    # unit_ts = await CodeGraphToolset.from_runtime(
    #     backend=backend,
    #     tool_names=_UNIT_TEST_TOOL_NAMES,
    #     toolset_id="potpie-unit-test",
    #     exclude_embedding_tools=exclude_embedding_tools,
    # )
    # integ_ts = await CodeGraphToolset.from_runtime(
    #     backend=backend,
    #     tool_names=_INTEGRATION_TEST_TOOL_NAMES,
    #     toolset_id="potpie-integ-test",
    #     exclude_embedding_tools=exclude_embedding_tools,
    # )
    blast_ts = await CodeGraphToolset.from_runtime(
        backend=backend,
        tool_names=_BLAST_RADIUS_TOOL_NAMES,
        toolset_id="potpie-blast-radius",
        exclude_embedding_tools=exclude_embedding_tools,
    )

    return [
        {
            "name": "codebase_qna",
            "description": (
                "Answer questions about the codebase using the knowledge graph. "
                "Use for: 'What does X do?', 'How is Y implemented?', "
                "'Where is Z defined?', 'Which files import A?'"
            ),
            "instructions": _QNA_INSTRUCTIONS,
            "toolsets": [qna_ts],
            "include_filesystem": True,
            "preferred_mode": "async",
        },
        # {
        #     "name": "debugging",
        #     "description": (
        #         "Systematic root-cause debugging using the knowledge graph. "
        #         "Use for: 'Why does X crash?', 'Fix the bug in Y', "
        #         "'Trace why Z returns wrong value'"
        #     ),
        #     "instructions": _DEBUG_INSTRUCTIONS,
        #     "toolsets": [debug_ts],
        #     "include_filesystem": True,
        #     "preferred_mode": "async",
        # },
        # {
        #     "name": "code_generation",
        #     "description": (
        #         "Generate precise, copy-paste ready code changes. "
        #         "Use for: 'Add feature X', 'Implement Y', 'Modify Z to support A'"
        #     ),
        #     "instructions": _CODE_GEN_INSTRUCTIONS,
        #     "toolsets": [codegen_ts],
        #     "include_filesystem": True,
        #     "preferred_mode": "async",
        # },
        # {
        #     "name": "lld",
        #     "description": (
        #         "Create a low-level design plan for implementing a new feature. "
        #         "Use for: 'Design how to add X', 'Plan the implementation of Y'"
        #     ),
        #     "instructions": _LLD_INSTRUCTIONS,
        #     "toolsets": [lld_ts],
        #     "include_filesystem": True,
        #     "preferred_mode": "async",
        # },
        # {
        #     "name": "unit_test",
        #     "description": (
        #         "Write unit tests for specific functions or classes. "
        #         "Use for: 'Write tests for X', 'Generate unit tests for Y function'"
        #     ),
        #     "instructions": _UNIT_TEST_INSTRUCTIONS,
        #     "toolsets": [unit_ts],
        #     "include_filesystem": True,
        #     "preferred_mode": "async",
        # },
        # {
        #     "name": "integration_test",
        #     "description": (
        #         "Write integration tests covering component interactions. "
        #         "Use for: 'Write integration tests for X', "
        #         "'Test the interaction between A and B'"
        #     ),
        #     "instructions": _INTEGRATION_TEST_INSTRUCTIONS,
        #     "toolsets": [integ_ts],
        #     "include_filesystem": True,
        #     "preferred_mode": "async",
        # },
        {
            "name": "blast_radius",
            "description": (
                "Analyse the blast radius of code changes — which functions, APIs, "
                "and consumers are affected by changes in the current branch. "
                "Use for: 'What is the impact of my changes?', "
                "'Which tests might break?', 'What depends on X?'"
            ),
            "instructions": _BLAST_RADIUS_INSTRUCTIONS,
            "toolsets": [blast_ts],
            "include_filesystem": True,
            "preferred_mode": "async",
        },
    ]


__all__ = ["make_potpie_subagents"]

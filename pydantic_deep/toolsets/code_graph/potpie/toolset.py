"""PotpieToolset — pydantic-ai FunctionToolset that exposes potpie code-graph tools.

The toolset is backend-agnostic: it accepts a PotpieRuntime instance
and exposes four agent-callable tools:

  list_code_projects   — enumerate indexed repositories
  search_codebase      — fast keyword search (SQL index)
  nl_query             — structural NL→Cypher query (call graphs, imports, etc.)
  ask_knowledge_graph  — semantic / docstring similarity search

For subagent use, ``PotpieToolset.from_runtime()`` fetches the full set of
low-level KG tools from a PotpieRuntime and wraps them with project_id injection.

``get_instructions()`` injects the list of available project IDs into the
system prompt so the agent can reference them without a round-trip.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from pydantic_ai import RunContext, Tool
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.toolsets.code_graph.potpie.runtime import PotpieRuntime

# ── Tool descriptions ─────────────────────────────────────────────────────────

_LIST_PROJECTS_DESC = """\
List all code repositories that have been indexed in the potpie code graph.

Returns a list of projects with their IDs, names, branch names, and status.
Use this to discover which project_id values are available before running
other code-graph tools."""

_SEARCH_DESC = """\
Fast keyword search over the indexed code base (SQL-backed).

Use this when you know the name of a function, class, or file and want to find
it quickly. Returns matching nodes with file paths and brief metadata.

:param query: Search term — function name, class name, file path fragment, etc."""

_NL_QUERY_DESC = """\
Query the code knowledge graph using a natural language structural question.

Translates the question to a Cypher query and runs it against the Neo4j graph.
Use this for STRUCTURAL / RELATIONAL questions:
  - "What functions does UserService call?"
  - "Which files import auth.py?"
  - "List all classes in the payments module."
  - "What are the call-graph neighbours of parse_directory?"

Returns: {"cypher_used": str, "results": list[dict], "count": int}

:param question: Natural language question about code structure."""

_KG_SEARCH_DESC = """\
Semantic search over code docstrings and summaries using embedding similarity.

Use this for MEANING / BEHAVIOUR questions:
  - "What does authentication look like in this codebase?"
  - "Find code that handles retry logic."
  - "Which functions validate user input?"

Returns a ranked list of nodes with docstrings, file paths, and similarity scores.

:param questions: One or more natural-language questions (list of strings).
:param node_ids: Optional list of node IDs to narrow the search scope."""

_ANALYZE_REG_DESC = """\
Analyze the simulated hardware behaviour of every register in a Simics DML device.

For each register the tool:
  - Queries the Neo4j code graph for DML callback methods and templates.
  - Uses an LLM to produce a detailed write_effect, read_effect, and keywords
    for each register (parallel map-reduce for large registers).
  - Persists results to device storage so subsequent calls are incremental.
  - Merges all register keywords into a device-level capability_keywords list.

Registers whose status is already 'done' are skipped — safe to re-run after
a partial failure. Set refresh=True to force full re-analysis from scratch.

Returns a summary dict:
  {"device_name", "project_id", "total_registers", "done", "failed",
   "skipped_passive", "capability_keywords": [...], "status_counts": {...}}

:param device_name: DML device name (case-insensitive partial match).
:param refresh: When true, reset all registers to pending before analysis.
:param batch_size: Max concurrent register analyses per batch (default 30).
:param chunk_tokens: Token budget per LLM call before chunking (default 15000)."""

_LIST_SIMICS_DEVICE_FEATURE_DESC = """\
List hardware analysis results for a Simics DML device.

Use the ``feature`` parameter to choose what to return:
  - "register"  — per-register write/read side-effects and capability keywords,
                  grouped by bank
  - "event"     — per-event feature descriptions and capability keywords
  - "fsm"       — per-FSM state diagrams (Mermaid stateDiagram-v2), feature
                  descriptions, states, and capability keywords
  - "interface" — per-interface (PORT/CONNECT) feature descriptions and
                  capability keywords
  - "keyword"   — device-level capability keyword map derived from register
                  side-effect analysis
  - Combine with "+" e.g. "register+event+fsm" or use "all" for all five.

If the requested analysis pipeline has not been run yet for the device,
the tool triggers it automatically before returning results.

Returns a dict with device_name, project_id, and either flat top-level fields
(single feature) or a "features" dict (multiple features).

:param device_name: DML device name (case-insensitive partial match).
:param feature: Which feature(s) to return (see above)."""

_LIST_CAP_DESC = """\
List all hardware capability descriptions for a Simics DML device.

Looks up previously generated capability descriptions from device storage.
If none exist yet, automatically runs the full capability-analysis pipeline
(requires register side-effect analysis to have been completed first) and
returns the newly generated list.

Returns a dict with: device_name, project_id, cached (bool), generated (bool),
capability_status (str), capabilities (dict). Each capability is keyed by its
domain name and contains:
  - overview:        concise programmer-facing summary of the hardware feature
  - features:        ### FEATURE blocks with spec + simulation details per behaviour
  - signal_behavior: per-signal assert/deassert conditions and persistence
  - code_map:        source files with Defines / Uses sub-sections
  - code_snippets:   list of DML code snippet strings extracted from the features

When output is provided and is a writable directory path, one <capability>-spec.md
file is written per capability containing the overview, feature details, output
signal behavior, and code map. The list of written paths is returned under
files_written in the response.

Prerequisite: analyze_register_side_effect must have been run first.

:param device_name: DML device name (case-insensitive partial match).
:param output: Optional path to an output directory for writing spec files."""

_ANALYZE_CAP_DESC = """\
Generate structured hardware capability descriptions for a Simics DML device.

Reads register side-effect keyword analysis from device storage, groups keywords
into capability domains using an LLM, then for each domain fetches related source
nodes (registers, templates, functions) from the Neo4j code graph and generates a
comprehensive capability description containing:
  1. Feature overview
  2. Hardware-software interaction (registers, FSM, working flows)
  3. Code-map (source file → role in implementing the capability)

Prerequisite: analyze_register_side_effect must have been run first so that
capability_keywords are populated in device storage.

Returns a dict with: device_name, project_id, capabilities (list), cached (bool).
Each capability entry: {capability_name: {spec: "...", nodes: [node_id, ...]}}

:param device_name: DML device name (case-insensitive partial match).
:param refresh: When true, re-generate even if capabilities are already stored.
:param chunk_tokens: Token budget per LLM call before splitting into chunks (default 15000).
:param batch_size: Max parallel MAP chunk calls per gather() batch (default 5)."""

_ANALYZE_INTERFACE_DESC = """\
Analyze all PORT (input) and CONNECT (output) interfaces of a Simics DML device.

For each PORT/CONNECT node discovered via the Neo4j code graph the tool:
  - Collects DML context: templates, interfaces, and functions with call chains.
  - Sends the context to an LLM to produce a multi-paragraph feature description
    and 2-5 short hardware concept keywords (e.g. "interrupt-signal", "AXI-master").
  - Persists results to device storage; already-done records are skipped.

Set refresh=True to force full re-analysis from scratch.

Returns a summary dict:
  {"device_name", "project_id", "total_ports", "total_connects",
   "done", "failed", "status_counts", "interfaces": [...]}

Each entry in ``interfaces``: {node_id, name, kind ("port"|"connect"),
feature, keywords}.

:param device_name: DML device name (case-insensitive partial match).
:param refresh: When true, reset all interface records and re-analyse.
:param batch_size: Max concurrent interface analyses per batch (default 30).
:param chunk_tokens: Token budget per LLM call before chunking (default 15000)."""

_ANALYZE_FSM_DESC = """\
Analyze the finite-state machines (FSMs) in a Simics DML device and produce a
flowchart, hardware feature description, and capability keywords for each FSM.

For each FSM (a DML bank implementing the fsm template) the tool:
  - Queries the Neo4j code graph for FSM-level functions, event declarations,
    state groups, per-state event handlers, unconditional handlers, and call chains.
  - Finds external entry points — call sites that trigger FSM events via
    ``<fsm>.events.<event>.run_now`` / ``run_delayed``.
  - Sends the assembled context to an LLM (with map-reduce for large FSMs) to
    produce a Mermaid stateDiagram-v2 flowchart, a multi-paragraph hardware
    feature description, and 2-5 kebab-case capability keywords.
  - Merges FSM keywords into the device-level capability_keywords in storage.

FSMs already at DONE status are skipped — safe to re-run after a partial failure.
Set refresh=True to force full re-analysis from scratch.

Returns a dict:
  {"device_name", "project_id", "total_fsms",
   "fsm_analyses": [{"node_id", "name", "docstring",
                      "flowchart", "feature", "keywords",
                      "event_names", "init_states", "states", "entry_points"}, ...]}

:param device_name: DML device name (case-insensitive partial match).
:param refresh: When true, reset all FSMs to pending and re-analyse.
:param chunk_limit: Max state nodes per LLM map chunk (default 10).
:param batch_size: Max concurrent FSM analyses per gather() batch (default 3)."""



_ANALYZE_EVENT_DESC = """\
Analyse all EVENT nodes in a Simics DML device and produce per-event hardware
feature descriptions and capability keywords.

For each event node the tool collects DML context (implemented templates,
contained functions with call chains, and call sites for post/remove/posted/next),
then sends the context to an LLM to produce a multi-paragraph hardware feature
description and 2-5 kebab-case capability keywords.

Events already at DONE status are skipped — safe to re-run after partial failure.
Set refresh=True to force full re-analysis from scratch.

Returns a dict:
  {"device_name", "project_id", "total_events", "done", "failed",
   "total_keywords", "status"}

:param device_name: DML device name (case-insensitive partial match).
:param refresh: When true, reset all events to pending and re-analyse.
:param batch_size: Max concurrent event analyses per gather() batch (default 5)."""

_EXPLORE_SIMICS_DEVICE_DESC = """
Explore the full structural inventory of a Simics DML device.

Traverses the code graph and returns all banks, registers, fields, FSMs,
events, and interface nodes (PORTs and CONNECTs) for the given device.

Useful as a first step before calling analyse_register_side_effect,
analyse_fsm, analyse_event, or analyse_interface — the returned node_ids
can be fed directly into other potpie tools. Always fetches fresh data.

:param device_name: DML device name (case-insensitive partial match)."""

# ── Low-level KG tool names (PotpieRuntime only) ────────────────────────────

KG_TOOL_NAMES: list[str] = [
    "ask_knowledge_graph_queries",
    "nl_cypher_query",
    "get_code_from_multiple_node_ids",
    "get_code_from_probable_node_name",
    "get_code_file_structure",
    "fetch_file",
    "fetch_files_batch",
    "get_node_neighbours_from_node_id",
    "analyze_code_structure",
]

SIMICS_TOOL_NAMES: list[str] = [
    "explore_simics_device",
    "analyze_register_side_effect",
    "list_simics_device_feature",
    "analyze_capability",
    "list_capability",
    "analyze_interface",
    "analyze_fsm",
    "analyze_event",
]

_EMBEDDING_DEPENDENT_TOOLS: frozenset[str] = frozenset({"ask_knowledge_graph_queries"})


def _inject_project_id(tool: Tool) -> Tool:
    """Wrap a tool to inject project_id from ctx.deps.kg_context, removing it from the schema.

    If the tool's JSON schema has a 'project_id' property, wraps the function
    to accept RunContext as the first argument and fills project_id from
    ctx.deps.kg_context.project_id, so the LLM never needs to supply it.
    """
    schema = getattr(tool, "parameters_json_schema", None)
    if schema is None:
        fs = getattr(tool, "function_schema", None)
        schema = getattr(fs, "json_schema", None) or {}

    if "project_id" not in schema.get("properties", {}):
        return tool

    original_func = tool.function
    import asyncio as _asyncio
    _is_async = _asyncio.iscoroutinefunction(original_func)

    if _is_async:
        async def ctx_wrapper(ctx: RunContext[Any], **kwargs: Any) -> Any:
            kg_context = ctx.deps.kg_context if ctx.deps.kg_context is not None else None
            project_id = getattr(kg_context, "project_id", None) if kg_context else None
            if project_id:
                kwargs["project_id"] = project_id
            if tool.name in _EMBEDDING_DEPENDENT_TOOLS:
                status = getattr(kg_context, "parsing_status", None) if kg_context else None
                if status == "INFERRING":
                    return (
                        f"Tool '{tool.name}' is unavailable while the project is being indexed "
                        "(status: INFERRING). Use 'nl_cypher_query' or 'get_code_file_structure'."
                    )
            return await original_func(**kwargs)
    else:
        def ctx_wrapper(ctx: RunContext[Any], **kwargs: Any) -> Any:  # type: ignore[misc]
            kg_context = ctx.deps.kg_context if ctx.deps.kg_context is not None else None
            project_id = getattr(kg_context, "project_id", None) if kg_context else None
            if project_id:
                kwargs["project_id"] = project_id
            if tool.name in _EMBEDDING_DEPENDENT_TOOLS:
                status = getattr(kg_context, "parsing_status", None) if kg_context else None
                if status == "INFERRING":
                    return (
                        f"Tool '{tool.name}' is unavailable while the project is being indexed "
                        "(status: INFERRING). Use 'nl_cypher_query' or 'get_code_file_structure'."
                    )
            return original_func(**kwargs)

    ctx_wrapper.__name__ = getattr(original_func, "__name__", tool.name)
    ctx_wrapper.__doc__ = tool.description

    new_schema = copy.deepcopy(schema)
    new_schema.get("properties", {}).pop("project_id", None)
    required = new_schema.get("required", [])
    if "project_id" in required:
        required.remove("project_id")

    return Tool.from_schema(
        function=ctx_wrapper,
        name=tool.name,
        description=tool.description,
        json_schema=new_schema,
        takes_ctx=True,
    )


class PotpieToolset(FunctionToolset[Any]):
    """Agent toolset for potpie code-graph operations.

    Constructed with a runtime (PotpieRuntime) and an optional
    default project_id that is injected into the system prompt.

    Tools:
        - ``list_code_projects``: enumerate indexed repos
        - ``search_codebase``: fast keyword search
        - ``nl_query``: structural NL→Cypher query
        - ``ask_knowledge_graph``: semantic/docstring similarity search
        - ``explore_simics_device``: full structural inventory (banks, registers, FSMs, events, interfaces)
        - ``analyze_register_side_effect``: analyze Simics DML device registers
        - ``list_simics_device_feature``: list analysis results for a device by feature type (register/event/fsm/interface/keyword/all); triggers analysis on-demand
        - ``list_capability``: list capability descriptions for a device (generates them if not yet stored)
        - ``analyze_capability``: generate hardware capability descriptions from register analysis
        - ``analyze_interface``: analyze all PORT/CONNECT interfaces of a DML device
        - ``analyze_fsm``: analyze FSMs in a DML device (flowchart, feature, keywords)
        - ``analyze_event``: analyze EVENT nodes in a DML device
    """

    def __init__(
        self,
        *,
        runtime: PotpieRuntime,
        project_id: str | None = None,
    ) -> None:
        super().__init__(id="potpie-code-graph")
        self._runtime = runtime
        self._project_id = project_id

        @self.tool(description=_LIST_PROJECTS_DESC)
        async def list_code_projects(ctx: RunContext[Any]) -> str:
            projects = await self._runtime.list_projects()
            if not projects:
                return (
                    "No projects indexed yet. Use 'pydantic-deep parse repo' to index a repository."
                )
            return json.dumps(projects, default=str)

        @self.tool(description=_SEARCH_DESC)
        async def search_codebase(
            ctx: RunContext[Any],
            query: str,
        ) -> str:
            """Fast keyword search.

            Args:
                query: Search term.
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            results = await self._runtime.search(project_id, query)
            if not results:
                return f"No results for '{query}' in project {project_id}."
            return json.dumps(results, default=str)

        @self.tool(description=_NL_QUERY_DESC)
        async def nl_query(
            ctx: RunContext[Any],
            question: str,
        ) -> str:
            """Structural NL→Cypher query.

            Args:
                question: Natural language structural question.
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            result = await self._runtime.nl_query(project_id, question)
            return json.dumps(result, default=str)

        @self.tool(description=_KG_SEARCH_DESC)
        async def ask_knowledge_graph(
            ctx: RunContext[Any],
            questions: list[str],
            node_ids: list[str] | None = None,
        ) -> str:
            """Semantic knowledge-graph search.

            Args:
                questions: List of natural language questions.
                node_ids: Optional list of node IDs to restrict the search.
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            # Guard: embeddings are not available during INFERRING state
            if kg_context is not None and getattr(kg_context, "parsing_status", None) == "INFERRING":
                return (
                    "Semantic search is unavailable while the project is being indexed "
                    "(status: INFERRING). Embeddings are not ready yet. "
                    "Use `nl_query` for structural questions instead."
                )
            results = await self._runtime.kg_search(project_id, questions, node_ids or [])
            if not results:
                return "No results found for the given questions."
            return json.dumps(results, default=str)

        @self.tool(description=_ANALYZE_REG_DESC)
        async def analyze_register_side_effect(
            ctx: RunContext[Any],
            device_name: str,
            refresh: bool = False,
            batch_size: int = 30,
            chunk_tokens: int = 15000,
        ) -> str:
            """Analyze the simulated hardware behaviour of every register in a Simics DML device.

            Args:
                device_name: DML device name (case-insensitive partial match).
                refresh: When True, reset all registers to pending before analysis.
                batch_size: Max concurrent register analyses per batch (default 30).
                chunk_tokens: Token budget per LLM call before splitting into chunks (default 15000).
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            result = await self._runtime.analyze_register_side_effect(
                project_id=project_id,
                device_name=device_name,
                refresh=refresh,
                batch_size=batch_size,
                chunk_tokens=chunk_tokens,
            )
            return json.dumps(result, default=str)

        @self.tool(description=_LIST_SIMICS_DEVICE_FEATURE_DESC)
        async def list_simics_device_feature(
            ctx: RunContext[Any],
            device_name: str,
            feature: str = "all",
        ) -> str:
            """List hardware analysis results for a Simics DML device.

            Args:
                device_name: DML device name (case-insensitive partial match).
                feature: Which feature(s) to return: "register", "event", "fsm",
                    "interface", "keyword", a "+"-joined combination, or "all".
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            result = await self._runtime.list_simics_device_feature(
                project_id=project_id,
                device_name=device_name,
                feature=feature,
            )
            return json.dumps(result, default=str)

        @self.tool(description=_LIST_CAP_DESC)
        async def list_capability(
            ctx: RunContext[Any],
            device_name: str,
            output: str | None = None,
        ) -> str:
            """List hardware capability descriptions for a Simics DML device.

            Returns cached capabilities if available, otherwise generates them
            by running the full capability-analysis pipeline automatically.

            Args:
                device_name: DML device name (case-insensitive partial match).
                output: Optional path to an output directory.  When provided,
                    one <capability>-spec.md is written per capability.
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            result = await self._runtime.list_capability(
                project_id=project_id,
                device_name=device_name,
                output=output,
            )
            return json.dumps(result, default=str)

        @self.tool(description=_ANALYZE_CAP_DESC)
        async def analyze_capability(
            ctx: RunContext[Any],
            device_name: str,
            refresh: bool = False,
            chunk_tokens: int = 15000,
            batch_size: int = 5,
        ) -> str:
            """Generate structured hardware capability descriptions for a Simics DML device.

            Args:
                device_name: DML device name (case-insensitive partial match).
                refresh: When True, re-generate even if capabilities are already stored.
                chunk_tokens: Token budget per LLM call before splitting into chunks (default 15000).
                batch_size: Max parallel MAP chunk calls per gather() batch (default 5).
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            result = await self._runtime.analyze_capability(
                project_id=project_id,
                device_name=device_name,
                refresh=refresh,
                chunk_tokens=chunk_tokens,
                batch_size=batch_size,
            )
            return json.dumps(result, default=str)

        @self.tool(description=_ANALYZE_INTERFACE_DESC)
        async def analyze_interface(
            ctx: RunContext[Any],
            device_name: str,
            refresh: bool = False,
            batch_size: int = 30,
            chunk_tokens: int = 15000,
        ) -> str:
            """Analyze all PORT/CONNECT interfaces of a Simics DML device.

            Args:
                device_name: DML device name (case-insensitive partial match).
                refresh: When True, reset all interface records and re-analyse.
                batch_size: Max concurrent interface analyses per batch (default 30).
                chunk_tokens: Token budget per LLM call before chunking (default 15000).
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            result = await self._runtime.analyze_interface(
                project_id=project_id,
                device_name=device_name,
                refresh=refresh,
                batch_size=batch_size,
                chunk_tokens=chunk_tokens,
            )
            return json.dumps(result, default=str)

        @self.tool(description=_ANALYZE_FSM_DESC)
        async def analyze_fsm(
            ctx: RunContext[Any],
            device_name: str,
            refresh: bool = False,
            chunk_limit: int = 10,
            batch_size: int = 3,
        ) -> str:
            """Analyze FSMs in a Simics DML device.

            Args:
                device_name: DML device name (case-insensitive partial match).
                refresh: When True, reset all FSMs to pending and re-analyse.
                chunk_limit: Max state nodes per LLM map chunk (default 10).
                batch_size: Max concurrent FSM analyses per gather() batch (default 3).
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            result = await self._runtime.analyze_fsm(
                project_id=project_id,
                device_name=device_name,
                refresh=refresh,
                chunk_limit=chunk_limit,
                batch_size=batch_size,
            )
            return json.dumps(result, default=str)

        @self.tool(description=_ANALYZE_EVENT_DESC)
        async def analyze_event(
            ctx: RunContext[Any],
            device_name: str,
            refresh: bool = False,
            batch_size: int = 5,
        ) -> str:
            """Analyse EVENT nodes in a Simics DML device.

            Args:
                device_name: DML device name (case-insensitive partial match).
                refresh: When True, reset all events to pending and re-analyse.
                batch_size: Max concurrent event analyses per gather() batch (default 5).
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            result = await self._runtime.analyze_event(
                project_id=project_id,
                device_name=device_name,
                refresh=refresh,
                batch_size=batch_size,
            )
            return json.dumps(result, default=str)

        @self.tool(description=_EXPLORE_SIMICS_DEVICE_DESC)
        async def explore_simics_device(
            ctx: RunContext[Any],
            device_name: str,
        ) -> str:
            """Explore the full structure of a Simics DML device.

            Args:
                device_name: DML device name (case-insensitive partial match).
            """
            kg_context = getattr(ctx.deps, "kg_context", None)
            project_id = (getattr(kg_context, "project_id", None) if kg_context else None) or self._project_id
            if not project_id:
                return "Error: no project_id available. Use list_code_projects to find one."
            result = await self._runtime.explore_simics_device(
                project_id=project_id,
                device_name=device_name,
            )
            return json.dumps(result, default=str)

    async def get_instructions(self, ctx: RunContext[Any]) -> list[str] | None:
        """Inject project context into the system prompt."""
        parts: list[str] = []

        # Check parsing status from PotpieContext if available
        kg_context = getattr(ctx.deps, "kg_context", None)
        parsing_status = getattr(kg_context, "parsing_status", None) if kg_context else None
        is_inferring = parsing_status == "INFERRING"
        is_parsing = parsing_status in ("PARSING", "SUBMITTED")

        if self._project_id:
            status_note = ""
            if is_inferring:
                status_note = (
                    "\n\n> **Note:** Project is in INFERRING state — embeddings are being built. "
                    "`ask_knowledge_graph` is unavailable. Use `nl_query` instead."
                )
            elif is_parsing:
                status_note = (
                    "\n\n> **Note:** Project is still being parsed (status: "
                    f"{parsing_status}). Graph queries may return incomplete results."
                )

            parts.append(
                f"## Code Graph\n\n"
                f"Default project ID: `{self._project_id}`\n\n"
                "You have access to code-graph tools (`nl_query`, "
                "`ask_knowledge_graph`, `search_codebase`, `list_code_projects`, "
                "`analyze_register_side_effect`) "
                "to answer questions about the indexed codebase.\n"
                "Use `nl_query` for structural/relational questions "
                "(call graphs, imports, inheritance). "
                "Use `ask_knowledge_graph` for semantic/behaviour questions. "
                "Use `analyze_register_side_effect` to analyze the simulated hardware "
                "behaviour of Simics DML device registers." + status_note
            )
        else:
            parts.append(
                "## Code Graph\n\n"
                "You have access to code-graph tools. Use `list_code_projects` "
                "to discover available project IDs, then pass the relevant ID "
                "to `nl_query`, `ask_knowledge_graph`, `search_codebase`, "
                "or `analyze_register_side_effect`."
            )

        return parts if parts else None

    @classmethod
    async def from_runtime(
        cls,
        runtime: PotpieRuntime,
        tool_names: list[str] | None = None,
        toolset_id: str = "potpie-kg",
        exclude_embedding_tools: bool = False,
    ) -> FunctionToolset[Any]:
        """Create a FunctionToolset of low-level KG tools from a PotpieRuntime.

        Fetches StructuredTool instances via backend.get_tools(), wraps them
        with project_id injection, and returns a FunctionToolset for subagent use.

        Requires PotpieRuntime — only PotpieRuntime supports get_tools().

        Args:
            runtime: An initialised PotpieRuntime.
            tool_names: Tool names to retrieve. Defaults to KG_TOOL_NAMES.
            toolset_id: FunctionToolset identifier.
            exclude_embedding_tools: Skip embedding-dependent tools.

        Returns:
            FunctionToolset with all requested tools wrapped and ready for use.
        """
        # Lazy import — keeps pydantic_deep importable without app.* at module load time.
        from app.modules.intelligence.agents.chat_agents.multi_agent.utils.tool_utils import (
            wrap_structured_tools,
        )

        names = tool_names if tool_names is not None else KG_TOOL_NAMES
        langchain_tools = await runtime.get_tools(
            names, exclude_embedding_tools=exclude_embedding_tools
        )
        pydantic_tools = [_inject_project_id(t) for t in wrap_structured_tools(langchain_tools)]
        return FunctionToolset(tools=pydantic_tools, id=toolset_id)




__all__ = ["PotpieToolset"]

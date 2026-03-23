# Toolset APIs

<cite>
**Referenced Files in This Document**
- [__init__.py](file://pydantic_deep/toolsets/__init__.py)
- [context.py](file://pydantic_deep/toolsets/context.py)
- [memory.py](file://pydantic_deep/toolsets/memory.py)
- [plan/toolset.py](file://pydantic_deep/toolsets/plan/toolset.py)
- [skills/toolset.py](file://pydantic_deep/toolsets/skills/toolset.py)
- [skills/backend.py](file://pydantic_deep/toolsets/skills/backend.py)
- [skills/directory.py](file://pydantic_deep/toolsets/skills/directory.py)
- [web.py](file://pydantic_deep/toolsets/web.py)
- [checkpointing.py](file://pydantic_deep/toolsets/checkpointing.py)
- [agent.py](file://pydantic_deep/agent.py)
- [types.py](file://pydantic_deep/types.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)
10. [Appendices](#appendices)

## Introduction
This document provides comprehensive API documentation for the toolset interfaces and tool implementations in the pydantic-deep agent framework. It covers the planning toolset for task decomposition, the context toolset for automatic context injection, the memory toolset for persistent storage, the skills toolset for capability extensions, and the subagent toolset for multi-agent orchestration. For each toolset, we describe base classes, method signatures, parameter specifications, return value formats, examples, parameter validation, error handling, and integration patterns with the agent framework.

## Project Structure
The toolsets are organized under pydantic_deep/toolsets, with dedicated modules for each toolset family. The main entry point for toolsets is the package initializer, which re-exports commonly used toolsets and factories.

```mermaid
graph TB
A["pydantic_deep/toolsets/__init__.py"] --> B["plan/toolset.py"]
A --> C["skills/toolset.py"]
A --> D["skills/backend.py"]
A --> E["skills/directory.py"]
A --> F["context.py"]
A --> G["memory.py"]
A --> H["web.py"]
A --> I["checkpointing.py"]
J["pydantic_deep/agent.py"] --> A
K["pydantic_deep/types.py"] --> C
```

**Diagram sources**
- [__init__.py:1-25](file://pydantic_deep/toolsets/__init__.py#L1-L25)
- [plan/toolset.py:1-220](file://pydantic_deep/toolsets/plan/toolset.py#L1-L220)
- [skills/toolset.py:1-598](file://pydantic_deep/toolsets/skills/toolset.py#L1-L598)
- [skills/backend.py:1-565](file://pydantic_deep/toolsets/skills/backend.py#L1-L565)
- [skills/directory.py:1-532](file://pydantic_deep/toolsets/skills/directory.py#L1-L532)
- [context.py:1-208](file://pydantic_deep/toolsets/context.py#L1-L208)
- [memory.py:1-231](file://pydantic_deep/toolsets/memory.py#L1-L231)
- [web.py:1-408](file://pydantic_deep/toolsets/web.py#L1-L408)
- [checkpointing.py:1-603](file://pydantic_deep/toolsets/checkpointing.py#L1-L603)
- [agent.py:1-1001](file://pydantic_deep/agent.py#L1-L1001)
- [types.py:1-99](file://pydantic_deep/types.py#L1-L99)

**Section sources**
- [__init__.py:1-25](file://pydantic_deep/toolsets/__init__.py#L1-L25)

## Core Components
- Planning toolset: Provides ask_user and save_plan tools for interactive planning and plan persistence.
- Context toolset: Loads and injects project context files into the system prompt.
- Memory toolset: Manages persistent agent memory with read, write, and update operations.
- Skills toolset: Integrates skill discovery and management with agent capabilities.
- Web toolset: Provides web search, URL fetching, and HTTP request tools.
- Checkpoint toolset: Enables conversation checkpointing, listing, and rewinding.

Integration with the agent framework is handled by the agent factory, which composes toolsets and middleware according to configuration flags and parameters.

**Section sources**
- [plan/toolset.py:139-220](file://pydantic_deep/toolsets/plan/toolset.py#L139-L220)
- [context.py:150-208](file://pydantic_deep/toolsets/context.py#L150-L208)
- [memory.py:130-231](file://pydantic_deep/toolsets/memory.py#L130-L231)
- [skills/toolset.py:112-598](file://pydantic_deep/toolsets/skills/toolset.py#L112-L598)
- [web.py:214-408](file://pydantic_deep/toolsets/web.py#L214-L408)
- [checkpointing.py:448-603](file://pydantic_deep/toolsets/checkpointing.py#L448-L603)
- [agent.py:196-800](file://pydantic_deep/agent.py#L196-L800)

## Architecture Overview
The agent factory constructs a toolset list and passes it to the Agent constructor. Each toolset contributes tools and/or system prompt instructions. Middleware and processors augment behavior (e.g., context management, eviction, history archiving).

```mermaid
sequenceDiagram
participant User as "Caller"
participant Agent as "Agent"
participant Toolset as "Toolset"
participant Backend as "BackendProtocol"
User->>Agent : create_deep_agent(...)
Agent->>Toolset : Compose toolsets (context, memory, skills, plan, web, etc.)
Toolset->>Backend : Access files/resources (read, write, execute)
Agent-->>User : Agent instance with toolsets and middleware
```

**Diagram sources**
- [agent.py:196-800](file://pydantic_deep/agent.py#L196-L800)
- [context.py:150-208](file://pydantic_deep/toolsets/context.py#L150-L208)
- [memory.py:130-231](file://pydantic_deep/toolsets/memory.py#L130-L231)
- [skills/toolset.py:112-598](file://pydantic_deep/toolsets/skills/toolset.py#L112-L598)
- [plan/toolset.py:139-220](file://pydantic_deep/toolsets/plan/toolset.py#L139-L220)
- [web.py:214-408](file://pydantic_deep/toolsets/web.py#L214-L408)
- [checkpointing.py:448-603](file://pydantic_deep/toolsets/checkpointing.py#L448-L603)

## Detailed Component Analysis

### Planning Toolset
The planning toolset enables interactive planning with ask_user and save_plan tools. It is integrated into the agent as a built-in planner subagent when enabled.

- Toolset factory: create_plan_toolset
- Tools:
  - ask_user(question: str, options: list[dict[str, str]]) -> str
  - save_plan(title: str, content: str) -> str

Parameters and validation:
- ask_user requires 2–4 options with label, description, and optional recommended flag. Options list must not be empty.
- save_plan generates a slugified filename from title and appends a UUID segment; writes to plans_dir.

Return values:
- ask_user returns either the selected option label (auto-selected in headless mode) or a callback result.
- save_plan returns a success message with the saved path or an error message.

Error handling:
- Headless mode auto-selects recommended or first option if none provided.
- Backend write errors are surfaced as error messages.

Integration:
- The agent factory conditionally adds the planner subagent with predefined description and instructions.

```mermaid
sequenceDiagram
participant Agent as "Agent"
participant Planner as "PlanToolset"
participant User as "User"
participant Backend as "Backend"
Agent->>Planner : ask_user(question, options)
alt Interactive mode
Planner->>User : Present options
User-->>Planner : Selection
else Headless mode
Planner-->>Planner : Auto-select recommended/first
end
Planner-->>Agent : Selected option
Agent->>Planner : save_plan(title, content)
Planner->>Backend : write(path, content)
Backend-->>Planner : Write result
Planner-->>Agent : Success/failure message
```

**Diagram sources**
- [plan/toolset.py:139-220](file://pydantic_deep/toolsets/plan/toolset.py#L139-L220)

**Section sources**
- [plan/toolset.py:139-220](file://pydantic_deep/toolsets/plan/toolset.py#L139-L220)
- [agent.py:477-495](file://pydantic_deep/agent.py#L477-L495)

### Context Toolset
The context toolset loads project context files and injects them into the system prompt. It supports explicit file lists, auto-discovery, subagent filtering, and content truncation.

Key functions and classes:
- load_context_files(backend, paths) -> list[ContextFile]
- discover_context_files(backend, search_path, filenames) -> list[str]
- format_context_prompt(files, is_subagent, subagent_allowlist, max_chars) -> str
- ContextToolset.__init__(context_files=None, context_discovery=False, is_subagent=False, max_chars=DEFAULT_MAX_CONTEXT_CHARS)
- ContextToolset.get_instructions(ctx) -> str | None

Parameters:
- context_files: explicit list of file paths
- context_discovery: whether to auto-discover context files
- is_subagent: applies subagent filtering rules
- max_chars: per-file truncation threshold

Return values:
- get_instructions returns formatted context prompt or None if no files.

Validation and error handling:
- Missing files are silently skipped during loading.
- Truncation preserves head and tail with a truncation marker.
- Subagent filtering restricts visible files to an allowlist.

```mermaid
flowchart TD
Start(["get_instructions(ctx)"]) --> CheckMode{"context_discovery or context_files?"}
CheckMode --> |No| ReturnNone["Return None"]
CheckMode --> |Yes| Paths["Resolve paths"]
Paths --> Load["load_context_files(backend, paths)"]
Load --> Found{"Any files loaded?"}
Found --> |No| ReturnNone
Found --> |Yes| Format["format_context_prompt(files, is_subagent, max_chars)"]
Format --> ReturnPrompt["Return formatted prompt or None"]
```

**Diagram sources**
- [context.py:181-208](file://pydantic_deep/toolsets/context.py#L181-L208)

**Section sources**
- [context.py:47-208](file://pydantic_deep/toolsets/context.py#L47-L208)
- [agent.py:561-570](file://pydantic_deep/agent.py#L561-L570)

### Memory Toolset
The memory toolset provides persistent memory per agent/subagent with read, append, and update operations. It auto-injects memory into the system prompt.

Key classes and functions:
- get_memory_path(memory_dir, agent_name) -> str
- load_memory(backend, path, agent_name) -> MemoryFile | None
- format_memory_prompt(memory, max_lines) -> str
- AgentMemoryToolset.__init__(agent_name="main", memory_dir=DEFAULT_MEMORY_DIR, max_lines=DEFAULT_MAX_MEMORY_LINES, descriptions=None)
- AgentMemoryToolset.get_instructions(ctx) -> str | None

Tools:
- read_memory() -> str
- write_memory(content: str) -> str
- update_memory(old_text: str, new_text: str) -> str

Parameters:
- agent_name: identifies the agent owner
- memory_dir: base directory for memory files
- max_lines: truncation threshold for system prompt injection

Return values:
- read_memory returns full memory content or a message indicating no memory exists
- write_memory returns a summary of updated line count
- update_memory returns a summary or a not-found message

Validation and error handling:
- write_memory appends with proper newlines
- update_memory replaces only the first occurrence and checks for presence of old_text

```mermaid
classDiagram
class AgentMemoryToolset {
+__init__(agent_name, memory_dir, max_lines, descriptions)
+get_instructions(ctx) str|None
+read_memory() str
+write_memory(content) str
+update_memory(old_text, new_text) str
}
class MemoryFile {
+agent_name : str
+path : str
+content : str
}
AgentMemoryToolset --> MemoryFile : "loads/writes"
```

**Diagram sources**
- [memory.py:130-231](file://pydantic_deep/toolsets/memory.py#L130-L231)

**Section sources**
- [memory.py:69-231](file://pydantic_deep/toolsets/memory.py#L69-L231)
- [agent.py:584-611](file://pydantic_deep/agent.py#L584-L611)

### Skills Toolset
The skills toolset integrates skill discovery and management with Pydantic AI agents. It supports programmatic skills, filesystem-based discovery, backend-based discovery, and dynamic system prompt injection.

Key classes and functions:
- SkillsToolset.__init__(skills=None, directories=None, validate=True, max_depth=3, id=None, instruction_template=None, exclude_tools=None, descriptions=None)
- list_skills() -> dict[str, str]
- load_skill(skill_name: str) -> str
- read_skill_resource(skill_name: str, resource_name: str, args: dict[str, Any] | None = None) -> str
- run_skill_script(skill_name: str, script_name: str, args: dict[str, Any] | None = None) -> str
- get_instructions(ctx) -> str | None
- skill(...) -> SkillWrapper (decorator)
- get_skill(name: str) -> Skill

Parameters and validation:
- exclude_tools must be a subset of ["list_skills", "load_skill", "read_skill_resource", "run_skill_script"]
- Skill name validation enforces lowercase, numbers, and hyphens; length limit; uniqueness warnings on duplicates
- Directory-based discovery supports depth limits and resource/script discovery with safety checks

Return values:
- list_skills returns a mapping of skill name to description
- load_skill returns a structured XML-like skill document
- read_skill_resource returns resource content or error message
- run_skill_script returns script output or error message
- get_instructions returns a skills header with available skills

Integration:
- The agent factory constructs SkillsToolset with provided skills and/or directories and injects system prompt instructions.

```mermaid
classDiagram
class SkillsToolset {
+__init__(skills, directories, validate, max_depth, id, instruction_template, exclude_tools, descriptions)
+skills : dict[str, Skill]
+get_skill(name) Skill
+list_skills() dict[str,str]
+load_skill(skill_name) str
+read_skill_resource(skill_name, resource_name, args) str
+run_skill_script(skill_name, script_name, args) str
+get_instructions(ctx) str|None
+skill(...) SkillWrapper
}
class Skill {
+name : str
+description : str
+content : str
+uri : str|None
+resources : SkillResource[]
+scripts : SkillScript[]
+metadata : dict[str,Any]|None
}
SkillsToolset --> Skill : "manages"
```

**Diagram sources**
- [skills/toolset.py:112-598](file://pydantic_deep/toolsets/skills/toolset.py#L112-L598)
- [types.py:34-39](file://pydantic_deep/types.py#L34-L39)

**Section sources**
- [skills/toolset.py:112-598](file://pydantic_deep/toolsets/skills/toolset.py#L112-L598)
- [skills/backend.py:397-565](file://pydantic_deep/toolsets/skills/backend.py#L397-L565)
- [skills/directory.py:444-532](file://pydantic_deep/toolsets/skills/directory.py#L444-L532)
- [agent.py:623-662](file://pydantic_deep/agent.py#L623-L662)
- [types.py:34-39](file://pydantic_deep/types.py#L34-L39)

### Web Toolset
The web toolset provides pluggable web search, URL fetching, and HTTP request tools. It returns strings and avoids raising exceptions, surfacing errors as messages.

Factory and tools:
- create_web_toolset(id=None, search_provider=None, include_search=True, include_fetch=True, include_http=True, require_approval=True, user_agent=DEFAULT_USER_AGENT, descriptions=None)
- web_search(query: str, max_results: int = 5, topic: str = "general") -> str
- fetch_url(url: str, timeout: int = 30) -> str
- http_request(url: str, method: str = "GET", headers: dict[str, str] | None = None, data: str | None = None, timeout: int = 30) -> str

Parameters:
- search_provider: pluggable provider implementing SearchProvider protocol
- require_approval: approval gating for tools
- user_agent: default User-Agent header
- max_results: capped at 10

Return values:
- web_search returns JSON of results or error message
- fetch_url returns markdown content or error message
- http_request returns a structured result with success, status_code, url, and content

Validation and error handling:
- Imports guarded with descriptive error messages
- Requests exceptions caught and returned as messages
- fetch_url truncates long content with a marker

```mermaid
sequenceDiagram
participant Agent as "Agent"
participant Web as "WebToolset"
participant Provider as "SearchProvider"
participant HTTP as "requests"
Agent->>Web : web_search(query, max_results, topic)
Web->>Provider : search(query, ...)
Provider-->>Web : results
Web-->>Agent : JSON results or error message
Agent->>Web : fetch_url(url, timeout)
Web->>HTTP : GET url
HTTP-->>Web : HTML
Web-->>Agent : Markdown or error message
Agent->>Web : http_request(url, method, headers, data, timeout)
Web->>HTTP : request(method, url, ...)
HTTP-->>Web : response
Web-->>Agent : structured result or error message
```

**Diagram sources**
- [web.py:214-408](file://pydantic_deep/toolsets/web.py#L214-L408)

**Section sources**
- [web.py:214-408](file://pydantic_deep/toolsets/web.py#L214-L408)
- [agent.py:709-718](file://pydantic_deep/agent.py#L709-L718)

### Checkpoint Toolset
The checkpoint toolset enables conversation checkpointing, listing, and rewinding. It integrates with middleware for auto-saving and provides manual controls.

Classes and functions:
- Checkpoint(id, label, turn, messages, message_count, created_at, metadata)
- RewindRequested(checkpoint_id, label, messages) -> Exception
- CheckpointStore protocol (save, get, get_by_label, list_all, remove, remove_oldest, count, clear)
- InMemoryCheckpointStore, FileCheckpointStore
- CheckpointMiddleware(before_model_request, after_tool_call)
- CheckpointToolset.__init__(store=None, id="deep-checkpoints", descriptions=None)
- save_checkpoint(label: str) -> str
- list_checkpoints() -> str
- rewind_to(checkpoint_id: str) -> str

Parameters:
- store: fallback store; resolved from ctx.deps.checkpoint_store at runtime
- frequency: "every_turn", "every_tool", "manual_only"
- max_checkpoints: pruning limit

Return values:
- save_checkpoint returns a labeled checkpoint summary or a message indicating no checkpoint is available
- list_checkpoints returns a formatted list of checkpoints
- rewind_to raises RewindRequested to signal app-level rewind

Validation and error handling:
- RewindRequested bubbles up from rewind_to to allow application-level restoration
- Store operations guarded by existence checks and descriptive messages

```mermaid
flowchart TD
Start(["Rewind requested"]) --> Lookup["Lookup checkpoint by id"]
Lookup --> Exists{"Exists?"}
Exists --> |No| NotFound["Return not found message"]
Exists --> |Yes| Raise["Raise RewindRequested(messages)"]
Raise --> App["App restores session.message_history<br/>and restarts"]
```

**Diagram sources**
- [checkpointing.py:533-556](file://pydantic_deep/toolsets/checkpointing.py#L533-L556)

**Section sources**
- [checkpointing.py:448-603](file://pydantic_deep/toolsets/checkpointing.py#L448-L603)
- [agent.py:691-701](file://pydantic_deep/agent.py#L691-L701)

### Conceptual Overview
The toolsets collectively extend the agent’s capabilities:
- Planning: decompose tasks and persist plans
- Context: inject project context into system prompts
- Memory: maintain persistent agent memory
- Skills: modular capabilities with resources and scripts
- Web: external knowledge and API access
- Checkpointing: reliable session recovery

```mermaid
graph TB
subgraph "Agent Runtime"
A1["System Prompt"]
A2["Tool Calls"]
A3["Model Response"]
end
subgraph "Toolsets"
T1["Planning"]
T2["Context"]
T3["Memory"]
T4["Skills"]
T5["Web"]
T6["Checkpoint"]
end
T1 --> A2
T2 --> A1
T3 --> A1
T4 --> A2
T5 --> A2
T6 --> A2
A2 --> A3
```

[No sources needed since this diagram shows conceptual workflow, not actual code structure]

[No sources needed since this section doesn't analyze specific source files]

## Dependency Analysis
The agent factory composes toolsets and middleware based on configuration flags. Skills toolset depends on skills types and directory/backend discovery modules. Context and memory toolsets depend on the backend protocol. Web toolset depends on optional external libraries. Checkpoint toolset depends on middleware and storage protocols.

```mermaid
graph TB
Agent["agent.py:create_deep_agent"] --> CTX["context.py:ContextToolset"]
Agent --> MEM["memory.py:AgentMemoryToolset"]
Agent --> SK["skills/toolset.py:SkillsToolset"]
SK --> SKDIR["skills/directory.py:SkillsDirectory"]
SK --> SKBD["skills/backend.py:BackendSkillsDirectory"]
Agent --> PLAN["plan/toolset.py:PlanToolset"]
Agent --> WEB["web.py:WebToolset"]
Agent --> CP["checkpointing.py:CheckpointToolset"]
```

**Diagram sources**
- [agent.py:196-800](file://pydantic_deep/agent.py#L196-L800)
- [context.py:150-208](file://pydantic_deep/toolsets/context.py#L150-L208)
- [memory.py:130-231](file://pydantic_deep/toolsets/memory.py#L130-L231)
- [skills/toolset.py:112-598](file://pydantic_deep/toolsets/skills/toolset.py#L112-L598)
- [skills/directory.py:444-532](file://pydantic_deep/toolsets/skills/directory.py#L444-L532)
- [skills/backend.py:397-565](file://pydantic_deep/toolsets/skills/backend.py#L397-L565)
- [plan/toolset.py:139-220](file://pydantic_deep/toolsets/plan/toolset.py#L139-L220)
- [web.py:214-408](file://pydantic_deep/toolsets/web.py#L214-L408)
- [checkpointing.py:448-603](file://pydantic_deep/toolsets/checkpointing.py#L448-L603)

**Section sources**
- [agent.py:196-800](file://pydantic_deep/agent.py#L196-L800)

## Performance Considerations
- Context and memory toolsets support truncation to manage token budgets.
- Skills toolset supports depth-limited discovery and resource/script safety checks.
- Web toolset caps max_results and truncates fetch_url output.
- Checkpoint toolset prunes older checkpoints to limit storage growth.
- Eviction processor can reduce tool output size before summarization.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Missing API keys or packages: web toolset requires TAVILY_API_KEY and optional dependencies; errors are returned as messages.
- Invalid skill names or duplicates: skills toolset validates names and warns on duplicates.
- Backend read/write failures: context and memory toolsets return descriptive messages; web toolset handles request exceptions gracefully.
- Checkpoint not found: rewind_to returns a not-found message; ensure correct checkpoint_id.

**Section sources**
- [web.py:278-287](file://pydantic_deep/toolsets/web.py#L278-L287)
- [skills/toolset.py:194-206](file://pydantic_deep/toolsets/skills/toolset.py#L194-L206)
- [context.py:62-70](file://pydantic_deep/toolsets/context.py#L62-L70)
- [memory.py:176-192](file://pydantic_deep/toolsets/memory.py#L176-L192)
- [checkpointing.py:540-550](file://pydantic_deep/toolsets/checkpointing.py#L540-L550)

## Conclusion
The toolset APIs provide a cohesive extension mechanism for pydantic-deep agents. Planning, context, memory, skills, web, and checkpoint toolsets integrate seamlessly with the agent factory and middleware pipeline. Their documented interfaces, parameter specifications, return formats, validation, and error handling enable robust multi-agent workflows and reliable session management.

## Appendices
- Integration patterns:
  - Enable planner subagent via include_plan and include_subagents flags.
  - Configure context and memory per agent/subagent using ContextToolset and AgentMemoryToolset.
  - Supply skills via programmatic Skill instances or directory/backend discovery.
  - Gate sensitive tools with require_approval and interrupt_on settings.
  - Use checkpoint middleware and toolset for reliable recovery and forking.

**Section sources**
- [agent.py:256-800](file://pydantic_deep/agent.py#L256-L800)
- [plan/toolset.py:139-220](file://pydantic_deep/toolsets/plan/toolset.py#L139-L220)
- [context.py:150-208](file://pydantic_deep/toolsets/context.py#L150-L208)
- [memory.py:130-231](file://pydantic_deep/toolsets/memory.py#L130-L231)
- [skills/toolset.py:112-598](file://pydantic_deep/toolsets/skills/toolset.py#L112-L598)
- [web.py:214-408](file://pydantic_deep/toolsets/web.py#L214-L408)
- [checkpointing.py:448-603](file://pydantic_deep/toolsets/checkpointing.py#L448-L603)
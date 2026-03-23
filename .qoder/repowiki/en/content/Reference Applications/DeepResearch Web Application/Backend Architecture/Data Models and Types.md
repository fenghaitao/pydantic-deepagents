# Data Models and Types

<cite>
**Referenced Files in This Document**
- [types.py](file://pydantic_deep/types.py)
- [types.py](file://apps/deepresearch/src/deepresearch/types.py)
- [types.py](file://apps/swebench_agent/types.py)
- [agent.py](file://pydantic_deep/agent.py)
- [checkpointing.py](file://pydantic_deep/toolsets/checkpointing.py)
- [history_archive.py](file://pydantic_deep/processors/history_archive.py)
- [context.py](file://pydantic_deep/toolsets/context.py)
- [memory.py](file://pydantic_deep/toolsets/memory.py)
- [skills/types.py](file://pydantic_deep/toolsets/skills/types.py)
- [app.py](file://apps/deepresearch/src/deepresearch/app.py)
- [app.py](file://examples/full_app/app.py)
- [config.py](file://cli/config.py)
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

## Introduction
This document explains the data models and type definitions used across the application, focusing on:
- UserSession dataclass for per-user session state
- Pydantic models for structured research reports
- Dataclasses for SWE-bench evaluation
- Type definitions for skills and agent interactions
- Serialization patterns, validation rules, and data transformation processes
- Message history management, checkpoint storage types, and session state persistence
- WebSocket message types and streaming semantics

## Project Structure
The data models and types span several modules:
- Core type definitions and re-exports
- Structured models for research reports
- Dataclasses for SWE-bench evaluation
- Agent configuration and toolset types
- Session state and persistence utilities
- WebSocket streaming and event types

```mermaid
graph TB
subgraph "Core Types"
A["pydantic_deep/types.py"]
B["pydantic_deep/toolsets/skills/types.py"]
end
subgraph "Application Models"
C["apps/deepresearch/src/deepresearch/types.py"]
D["apps/swebench_agent/types.py"]
end
subgraph "Agent & Toolsets"
E["pydantic_deep/agent.py"]
F["pydantic_deep/toolsets/checkpointing.py"]
G["pydantic_deep/processors/history_archive.py"]
H["pydantic_deep/toolsets/context.py"]
I["pydantic_deep/toolsets/memory.py"]
end
subgraph "Session & Streaming"
J["apps/deepresearch/src/deepresearch/app.py"]
K["examples/full_app/app.py"]
L["cli/config.py"]
end
A --> E
B --> E
C --> J
D --> J
E --> F
E --> G
E --> H
E --> I
J --> K
L --> J
```

**Diagram sources**
- [types.py:1-99](file://pydantic_deep/types.py#L1-L99)
- [skills/types.py:1-521](file://pydantic_deep/toolsets/skills/types.py#L1-L521)
- [types.py:1-72](file://apps/deepresearch/src/deepresearch/types.py#L1-L72)
- [types.py:1-77](file://apps/swebench_agent/types.py#L1-L77)
- [agent.py:1-1001](file://pydantic_deep/agent.py#L1-L1001)
- [checkpointing.py:1-603](file://pydantic_deep/toolsets/checkpointing.py#L1-L603)
- [history_archive.py:1-195](file://pydantic_deep/processors/history_archive.py#L1-L195)
- [context.py:1-208](file://pydantic_deep/toolsets/context.py#L1-L208)
- [memory.py:1-231](file://pydantic_deep/toolsets/memory.py#L1-L231)
- [app.py:241-308](file://apps/deepresearch/src/deepresearch/app.py#L241-L308)
- [app.py:1-200](file://examples/full_app/app.py#L1-L200)
- [config.py:1-254](file://cli/config.py#L1-L254)

**Section sources**
- [types.py:1-99](file://pydantic_deep/types.py#L1-L99)
- [skills/types.py:1-521](file://pydantic_deep/toolsets/skills/types.py#L1-L521)
- [types.py:1-72](file://apps/deepresearch/src/deepresearch/types.py#L1-L72)
- [types.py:1-77](file://apps/swebench_agent/types.py#L1-L77)
- [agent.py:1-1001](file://pydantic_deep/agent.py#L1-L1001)
- [checkpointing.py:1-603](file://pydantic_deep/toolsets/checkpointing.py#L1-L603)
- [history_archive.py:1-195](file://pydantic_deep/processors/history_archive.py#L1-L195)
- [context.py:1-208](file://pydantic_deep/toolsets/context.py#L1-L208)
- [memory.py:1-231](file://pydantic_deep/toolsets/memory.py#L1-L231)
- [app.py:241-308](file://apps/deepresearch/src/deepresearch/app.py#L241-L308)
- [app.py:1-200](file://examples/full_app/app.py#L1-L200)
- [config.py:1-254](file://cli/config.py#L1-L254)

## Core Components
- UserSession: Per-user session state container with message history, approvals, tasks, and checkpoint store.
- Pydantic models for research reports: Source, Finding, ReportSection, ReportMetadata, ResearchReport.
- SWE-bench dataclasses: SWEBenchInstance, Prediction, InstanceResult, RunConfig.
- Skill dataclasses: Skill, SkillResource, SkillScript, SkillWrapper.
- Checkpoint types: Checkpoint, CheckpointStore protocol, in-memory and file-backed stores.
- Context and memory toolsets: ContextFile, AgentMemoryToolset, and related utilities.
- History archive: Toolset and processor for searching persisted conversation history.
- CLI configuration: CliConfig dataclass and helpers for session and project directories.

**Section sources**
- [app.py:241-308](file://apps/deepresearch/src/deepresearch/app.py#L241-L308)
- [types.py:8-72](file://apps/deepresearch/src/deepresearch/types.py#L8-L72)
- [types.py:9-77](file://apps/swebench_agent/types.py#L9-L77)
- [skills/types.py:75-521](file://pydantic_deep/toolsets/skills/types.py#L75-L521)
- [checkpointing.py:59-603](file://pydantic_deep/toolsets/checkpointing.py#L59-L603)
- [context.py:35-208](file://pydantic_deep/toolsets/context.py#L35-L208)
- [memory.py:57-231](file://pydantic_deep/toolsets/memory.py#L57-L231)
- [history_archive.py:134-195](file://pydantic_deep/processors/history_archive.py#L134-L195)
- [config.py:70-254](file://cli/config.py#L70-L254)

## Architecture Overview
The data models integrate with agent configuration and toolsets to manage:
- Message history and streaming events
- Persistent session state and checkpoints
- Context and memory injection
- Structured output and report generation

```mermaid
classDiagram
class UserSession {
+string session_id
+DeepAgentDeps deps
+ModelMessage[] message_history
+dict pending_approval_state
+Event cancel_event
+Task running_task
+list latest_todos
+dict pending_questions
+InMemoryCheckpointStore checkpoint_store
}
class Checkpoint {
+string id
+string label
+int turn
+ModelMessage[] messages
+int message_count
+datetime created_at
+dict metadata
}
class CheckpointStore {
<<interface>>
+save(checkpoint) None
+get(checkpoint_id) Checkpoint|None
+get_by_label(label) Checkpoint|None
+list_all() Checkpoint[]
+remove(checkpoint_id) bool
+remove_oldest() bool
+count() int
+clear() None
}
class InMemoryCheckpointStore {
-dict _checkpoints
+save(checkpoint) None
+get(checkpoint_id) Checkpoint|None
+get_by_label(label) Checkpoint|None
+list_all() Checkpoint[]
+remove(checkpoint_id) bool
+remove_oldest() bool
+count() int
+clear() None
}
class FileCheckpointStore {
-Path _dir
+save(checkpoint) None
+get(checkpoint_id) Checkpoint|None
+get_by_label(label) Checkpoint|None
+list_all() Checkpoint[]
+remove(checkpoint_id) bool
+remove_oldest() bool
+count() int
+clear() None
}
class ResearchReport {
+string title
+string question
+string executive_summary
+ReportSection[] sections
+string[] conclusions
+Source[] sources
+ReportMetadata metadata
}
class Source {
+int id
+string title
+string url
+string|None author
+string|None date
+string source_type
}
class Finding {
+string claim
+string evidence
+int[] source_ids
+string confidence
}
class ReportSection {
+string title
+string content
+Finding[] findings
}
class ReportMetadata {
+int total_sources
+int search_queries_used
+int pages_read
+float research_duration_seconds
+int diagrams_generated
}
class SWEBenchInstance {
+string instance_id
+string repo
+string base_commit
+string problem_statement
+string hints_text
+string patch
+string test_patch
+string FAIL_TO_PASS
+string PASS_TO_PASS
+string version
+string environment_setup_commit
}
class Prediction {
+string instance_id
+string model_name_or_path
+string model_patch
+to_dict() dict
}
class InstanceResult {
+string instance_id
+string model_patch
+float cost_usd
+float duration_seconds
+string|None error
+int tokens_used
+string trajectory
}
class RunConfig {
+string model
+string dataset
+string split
+string[] instance_ids
+int workers
+int timeout
+string output_path
+float temperature
+float|None cost_budget_usd
+dict|None model_settings
+string|None image_template
+string|None trajs_dir
}
UserSession --> CheckpointStore : "owns"
CheckpointStore <|.. InMemoryCheckpointStore
CheckpointStore <|.. FileCheckpointStore
ResearchReport --> ReportSection
ReportSection --> Finding
Finding --> Source : "references"
Prediction --> SWEBenchInstance : "relates to"
```

**Diagram sources**
- [app.py:241-308](file://apps/deepresearch/src/deepresearch/app.py#L241-L308)
- [checkpointing.py:59-603](file://pydantic_deep/toolsets/checkpointing.py#L59-L603)
- [types.py:8-72](file://apps/deepresearch/src/deepresearch/types.py#L8-L72)
- [types.py:9-77](file://apps/swebench_agent/types.py#L9-L77)

## Detailed Component Analysis

### UserSession Dataclass
- Purpose: Encapsulates per-user session state, including message history, approvals, tasks, and checkpoint store.
- Fields:
  - session_id: Unique session identifier
  - deps: Agent dependencies
  - message_history: List of ModelMessage for conversation continuity
  - pending_approval_state: Approval gating state
  - cancel_event: Async cancellation signaling
  - running_task: Current async task
  - latest_todos: Active task list
  - pending_questions: Pending user questions
  - checkpoint_store: In-memory checkpoint store for rewinds/forks
- Persistence:
  - Events logged to JSONL per session
  - Metadata written to meta.json with timestamps and counts
- WebSocket integration:
  - Session creation and event streaming
  - Real-time updates for todos and tool usage

```mermaid
sequenceDiagram
participant Client as "Client"
participant WS as "WebSocket Handler"
participant Session as "UserSession"
participant Agent as "Agent"
Client->>WS : Connect with optional session_id
WS->>Session : Create/get session
WS->>Client : Emit session_created
Client->>WS : Send message
WS->>Agent : Run with session.message_history
Agent-->>WS : Stream events (text_delta, tool_start, etc.)
WS->>Client : Forward events
WS->>Session : Persist events to JSONL/meta
```

**Diagram sources**
- [app.py:739-1200](file://apps/deepresearch/src/deepresearch/app.py#L739-L1200)
- [app.py:788-816](file://examples/full_app/app.py#L788-L816)
- [app.py:241-308](file://apps/deepresearch/src/deepresearch/app.py#L241-L308)

**Section sources**
- [app.py:241-308](file://apps/deepresearch/src/deepresearch/app.py#L241-L308)
- [app.py:739-1200](file://apps/deepresearch/src/deepresearch/app.py#L739-L1200)
- [app.py:788-816](file://examples/full_app/app.py#L788-L816)

### Pydantic Models for Research Reports
- Source: Identifies a cited source with metadata
- Finding: A factual claim supported by evidence and source references
- ReportSection: A section with content and findings
- ReportMetadata: Metrics about the research process
- ResearchReport: Top-level report aggregating sections, findings, and metadata

Validation and serialization:
- Pydantic models enforce field types and defaults
- Nested lists and references ensure structured output suitable for downstream processing

**Section sources**
- [types.py:8-72](file://apps/deepresearch/src/deepresearch/types.py#L8-L72)

### SWE-bench Dataclasses
- SWEBenchInstance: Mirrors dataset columns for evaluation instances
- Prediction: Output format for predictions (JSONL)
- InstanceResult: Aggregated metrics and trajectory for each instance
- RunConfig: Evaluation run configuration including model, dataset, and output paths

Serialization:
- Prediction.to_dict produces a dictionary compatible with evaluation harness
- RunConfig supports optional fields and typed defaults

**Section sources**
- [types.py:9-77](file://apps/swebench_agent/types.py#L9-L77)

### Skill Dataclasses and Type Definitions
- SkillResource: Static or dynamic resource with function schema
- SkillScript: Executable script with function schema
- Skill: Composite skill with metadata, content, resources, and scripts
- SkillWrapper: Decorator-based wrapper for type-safe dependency injection

Validation and transformation:
- Validation ensures resources/scripts have either content/function or uri
- Function schemas are generated for callable resources/scripts
- Skill normalization enforces naming constraints

**Section sources**
- [skills/types.py:75-521](file://pydantic_deep/toolsets/skills/types.py#L75-L521)
- [types.py:34-39](file://pydantic_deep/types.py#L34-L39)

### Message History Management and Streaming
- Agent configuration:
  - history_processors: Eviction and summarization processors
  - context_manager: Automatic token tracking and compression
  - include_history_archive: Enables search tool over persisted messages
- Streaming events:
  - Text deltas, tool call deltas, tool outputs, and final response
  - WebSocket server emits structured event types

```mermaid
flowchart TD
Start(["Agent.run()"]) --> Init["Initialize message_history"]
Init --> Stream["Stream PartDeltaEvent"]
Stream --> Emit["Emit WebSocket events"]
Emit --> Persist["Persist events to JSONL/meta"]
Persist --> Continue{"More steps?"}
Continue --> |Yes| Stream
Continue --> |No| Done(["FinalResultEvent"])
```

**Diagram sources**
- [agent.py:750-800](file://pydantic_deep/agent.py#L750-L800)
- [app.py:788-816](file://examples/full_app/app.py#L788-L816)

**Section sources**
- [agent.py:750-800](file://pydantic_deep/agent.py#L750-L800)
- [app.py:788-816](file://examples/full_app/app.py#L788-L816)

### Checkpoint Storage Types and Rewind/Fork
- Checkpoint: Immutable snapshot with id, label, turn, messages, metadata
- CheckpointStore protocol: Save, get, list, remove, prune, count, clear
- InMemoryCheckpointStore: Dict-backed store with insertion-order iteration
- FileCheckpointStore: JSON files with ModelMessagesTypeAdapter serialization
- RewindRequested: Exception to signal app-level rewind with message restoration
- fork_from_checkpoint: Utility to retrieve messages for new session initialization

```mermaid
classDiagram
class Checkpoint {
+string id
+string label
+int turn
+ModelMessage[] messages
+int message_count
+datetime created_at
+dict metadata
}
class CheckpointStore {
<<interface>>
+save(checkpoint) None
+get(checkpoint_id) Checkpoint|None
+get_by_label(label) Checkpoint|None
+list_all() Checkpoint[]
+remove(checkpoint_id) bool
+remove_oldest() bool
+count() int
+clear() None
}
class InMemoryCheckpointStore {
-dict _checkpoints
+save(checkpoint) None
+get(checkpoint_id) Checkpoint|None
+get_by_label(label) Checkpoint|None
+list_all() Checkpoint[]
+remove(checkpoint_id) bool
+remove_oldest() bool
+count() int
+clear() None
}
class FileCheckpointStore {
-Path _dir
+save(checkpoint) None
+get(checkpoint_id) Checkpoint|None
+get_by_label(label) Checkpoint|None
+list_all() Checkpoint[]
+remove(checkpoint_id) bool
+remove_oldest() bool
+count() int
+clear() None
}
class RewindRequested {
+string checkpoint_id
+string label
+ModelMessage[] messages
}
CheckpointStore <|.. InMemoryCheckpointStore
CheckpointStore <|.. FileCheckpointStore
RewindRequested --> Checkpoint : "messages snapshot"
```

**Diagram sources**
- [checkpointing.py:59-603](file://pydantic_deep/toolsets/checkpointing.py#L59-L603)

**Section sources**
- [checkpointing.py:59-603](file://pydantic_deep/toolsets/checkpointing.py#L59-L603)

### Context and Memory Toolsets
- ContextToolset: Loads and injects project context files into system prompt
- AgentMemoryToolset: Reads/writes/updaes persistent MEMORY.md files
- Both integrate with backend protocols and respect token budgets and truncation policies

**Section sources**
- [context.py:35-208](file://pydantic_deep/toolsets/context.py#L35-L208)
- [memory.py:57-231](file://pydantic_deep/toolsets/memory.py#L57-L231)

### History Archive Processor
- Provides search_conversation_history tool to query persisted messages.json
- Formats messages into readable excerpts with surrounding context
- Limits matches and respects maximum characters per message

**Section sources**
- [history_archive.py:134-195](file://pydantic_deep/processors/history_archive.py#L134-L195)

### CLI Configuration and Session Directories
- CliConfig: Dataclass for configuration with environment overrides
- Helpers: Project directory, sessions directory, history path resolution

**Section sources**
- [config.py:70-254](file://cli/config.py#L70-L254)

## Dependency Analysis
- UserSession depends on:
  - DeepAgentDeps for backend access
  - InMemoryCheckpointStore for rewinds/forks
  - JSONL and meta.json for persistence
- Agent configuration composes:
  - Toolsets (console, todo, subagents, skills, context, memory)
  - Processors (eviction, summarization)
  - Middleware (context manager, cost tracking)
  - Checkpoint toolset and middleware
- WebSocket server depends on:
  - Agent streaming events
  - UserSession for state continuity
  - JSONL persistence for replay

```mermaid
graph LR
UserSession --> JSONL["events.jsonl"]
UserSession --> Meta["meta.json"]
Agent --> Toolsets["Console/Todo/Subagents/Skills/Context/Memory"]
Agent --> Processors["Eviction/Summarization"]
Agent --> Middleware["ContextManager/CostTracking"]
Agent --> Checkpoints["CheckpointToolset/Middleware"]
WebSocket --> Agent
WebSocket --> UserSession
```

**Diagram sources**
- [app.py:241-308](file://apps/deepresearch/src/deepresearch/app.py#L241-L308)
- [agent.py:505-800](file://pydantic_deep/agent.py#L505-L800)

**Section sources**
- [app.py:241-308](file://apps/deepresearch/src/deepresearch/app.py#L241-L308)
- [agent.py:505-800](file://pydantic_deep/agent.py#L505-L800)

## Performance Considerations
- Token budgeting and eviction:
  - EvictionProcessor truncates large tool outputs to preserve context
  - ContextManagerMiddleware compresses context when nearing limits
- Checkpoint pruning:
  - Stores maintain bounded counts to avoid unbounded growth
- Streaming:
  - WebSocket events minimize payload sizes and batch updates
- File-based persistence:
  - JSONL and meta.json are append-only for low contention

## Troubleshooting Guide
- Validation failures:
  - Skill names must match normalized pattern; ensure names use lowercase, digits, and hyphens
  - Resources/scripts must define either content/function or uri
- Checkpoint issues:
  - RewindRequested indicates a checkpoint was selected; ensure the app catches and replays message_history
  - FileCheckpointStore requires valid JSON; verify serialization/deserialization paths
- WebSocket connectivity:
  - Session creation emits session_created; confirm client handles reconnects and resumption
  - Ensure message_history is preserved across runs for continuity

**Section sources**
- [skills/types.py:34-72](file://pydantic_deep/toolsets/skills/types.py#L34-L72)
- [checkpointing.py:87-107](file://pydantic_deep/toolsets/checkpointing.py#L87-L107)
- [app.py:739-775](file://apps/deepresearch/src/deepresearch/app.py#L739-L775)

## Conclusion
The application’s data models and types provide a robust foundation for agent interactions, session state management, and structured output. They integrate seamlessly with toolsets, middleware, and persistence mechanisms to support real-time streaming, checkpointing, and long-term memory. By leveraging Pydantic models, dataclasses, and typed protocols, the system ensures strong validation, predictable serialization, and scalable session handling.
# DeepResearch Web Application

<cite>
**Referenced Files in This Document**
- [app.py](file://apps/deepresearch/src/deepresearch/app.py)
- [agent.py](file://apps/deepresearch/src/deepresearch/agent.py)
- [config.py](file://apps/deepresearch/src/deepresearch/config.py)
- [prompts.py](file://apps/deepresearch/src/deepresearch/prompts.py)
- [middleware.py](file://apps/deepresearch/src/deepresearch/middleware.py)
- [index.html](file://apps/deepresearch/static/index.html)
- [app.js](file://apps/deepresearch/static/app.js)
- [styles.css](file://apps/deepresearch/static/styles.css)
- [Dockerfile](file://apps/deepresearch/Dockerfile)
- [docker-compose.yml](file://apps/deepresearch/docker-compose.yml)
- [pyproject.toml](file://apps/deepresearch/pyproject.toml)
- [README.md](file://apps/deepresearch/README.md)
- [SKILL.md (research-methodology)](file://apps/deepresearch/skills/research-methodology/SKILL.md)
- [DEEP.md](file://apps/deepresearch/workspace/DEEP.md)
- [MEMORY.md](file://apps/deepresearch/workspace/MEMORY.md)
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
DeepResearch is a complete AI-powered research assistant with a FastAPI backend and a React-like single-page frontend. It integrates with MCP (Model Context Protocol) servers for web search, web scraping, browser automation, and diagram generation. The system runs inside Docker-managed sandboxed environments for secure file operations and code execution. Users interact via a WebSocket stream for real-time responses, with a dark-themed UI and rich tooling for research, planning, subagents, and report generation.

## Project Structure
The application is organized into:
- Backend: FastAPI application with WebSocket streaming, agent factory, MCP server integration, and middleware/hooks
- Frontend: Single-page app with HTML/CSS/JS for chat, file tree, Excalidraw canvas, and tool rendering
- Docker: Containerized runtime with optional Excalidraw canvas service
- Skills and workspace: Domain-specific skills and persistent context files

```mermaid
graph TB
subgraph "Frontend"
FE_HTML["index.html"]
FE_JS["app.js"]
FE_CSS["styles.css"]
end
subgraph "Backend"
BE_APP["FastAPI app.py"]
BE_AGENT["Agent factory agent.py"]
BE_CFG["Config config.py"]
BE_PROMPTS["Prompts prompts.py"]
BE_MW["Middleware middleware.py"]
end
subgraph "MCP Servers"
MCP_TAVILY["Tavily (npx)"]
MCP_BRAVE["Brave (npx)"]
MCP_JINA["Jina (HTTP)"]
MCP_FIRECRAWL["Firecrawl (npx)"]
MCP_PLAYWRIGHT["Playwright (npx)"]
MCP_EXCAL["Excalidraw (Docker)"]
end
subgraph "Runtime"
DOCKER["Dockerfile"]
DCMP["docker-compose.yml"]
end
FE_HTML --> FE_JS
FE_JS --> BE_APP
BE_APP --> BE_AGENT
BE_APP --> BE_CFG
BE_APP --> BE_MW
BE_AGENT --> BE_PROMPTS
BE_CFG --> MCP_TAVILY
BE_CFG --> MCP_BRAVE
BE_CFG --> MCP_JINA
BE_CFG --> MCP_FIRECRAWL
BE_CFG --> MCP_PLAYWRIGHT
BE_CFG --> MCP_EXCAL
DOCKER --> BE_APP
DCMP --> MCP_EXCAL
```

**Diagram sources**
- [app.py:636-692](file://apps/deepresearch/src/deepresearch/app.py#L636-L692)
- [agent.py:376-430](file://apps/deepresearch/src/deepresearch/agent.py#L376-L430)
- [config.py:58-151](file://apps/deepresearch/src/deepresearch/config.py#L58-L151)
- [Dockerfile:1-48](file://apps/deepresearch/Dockerfile#L1-L48)
- [docker-compose.yml:1-29](file://apps/deepresearch/docker-compose.yml#L1-L29)

**Section sources**
- [README.md:158-183](file://apps/deepresearch/README.md#L158-L183)
- [pyproject.toml:1-37](file://apps/deepresearch/pyproject.toml#L1-L37)

## Core Components
- FastAPI backend with WebSocket streaming for real-time chat
- Agent factory with hooks, subagents, skills, and instructions
- MCP server integrations for web search, scraping, browser automation, and diagrams
- Docker-based sandboxed execution environment
- React-like frontend with dark theme and file operations
- Session management with persistence and canvas isolation

**Section sources**
- [app.py:636-692](file://apps/deepresearch/src/deepresearch/app.py#L636-L692)
- [agent.py:376-430](file://apps/deepresearch/src/deepresearch/agent.py#L376-L430)
- [config.py:58-151](file://apps/deepresearch/src/deepresearch/config.py#L58-L151)
- [middleware.py:33-122](file://apps/deepresearch/src/deepresearch/middleware.py#L33-L122)

## Architecture Overview
DeepResearch uses a layered architecture:
- Presentation: SPA with WebSocket-driven UI
- Application: FastAPI routes and WebSocket handlers
- Intelligence: Agent factory with hooks, subagents, and skills
- Integration: MCP servers for external tools
- Runtime: Docker-managed sandbox for safe execution

```mermaid
sequenceDiagram
participant Client as "Browser (index.html + app.js)"
participant WS as "WebSocket /ws/chat (app.py)"
participant Agent as "Agent (agent.py)"
participant MCP as "MCP Servers (config.py)"
participant Sandbox as "Docker Sandbox"
Client->>WS : Connect and send session_id
WS->>WS : Create/restore session
WS->>Agent : Start streaming response
Agent->>MCP : Invoke tool (search/scrape/browser/draw)
MCP-->>Agent : Tool result
Agent->>Sandbox : Execute shell commands (optional)
Sandbox-->>Agent : Execution result
Agent-->>WS : Stream text/tool deltas
WS-->>Client : Render real-time UI updates
```

**Diagram sources**
- [app.py:719-800](file://apps/deepresearch/src/deepresearch/app.py#L719-L800)
- [agent.py:376-430](file://apps/deepresearch/src/deepresearch/agent.py#L376-L430)
- [config.py:58-151](file://apps/deepresearch/src/deepresearch/config.py#L58-L151)

## Detailed Component Analysis

### Backend: FastAPI and WebSocket Streaming
- Initializes agent with MCP servers and middleware
- Manages per-user sessions with isolated Docker containers
- Streams model responses and tool events via WebSocket
- Persists events to JSONL and maintains session metadata/history
- Integrates Excalidraw canvas per session

```mermaid
flowchart TD
Start(["WebSocket /ws/chat"]) --> Accept["Accept connection"]
Accept --> InitSession["Create/restore session"]
InitSession --> PatchSend["Monkey-patch send_json to log events"]
PatchSend --> SetupAskUser["Setup ask_user callback"]
SetupAskUser --> MonitorTasks["Start background task monitor"]
MonitorTasks --> SwitchCanvas["Switch Excalidraw canvas"]
SwitchCanvas --> Ready["Send canvas_ready"]
Ready --> Loop{"Incoming message"}
Loop --> |User message| Stream["Stream response via agent"]
Loop --> |Approval| Approve["Forward approval to agent"]
Loop --> |Cancel| Cancel["Cancel running task"]
Loop --> |Disconnect| End(["Close"])
```

**Diagram sources**
- [app.py:719-800](file://apps/deepresearch/src/deepresearch/app.py#L719-L800)
- [app.py:271-326](file://apps/deepresearch/src/deepresearch/app.py#L271-L326)
- [app.py:366-405](file://apps/deepresearch/src/deepresearch/app.py#L366-L405)
- [app.py:497-560](file://apps/deepresearch/src/deepresearch/app.py#L497-L560)

**Section sources**
- [app.py:636-692](file://apps/deepresearch/src/deepresearch/app.py#L636-L692)
- [app.py:719-800](file://apps/deepresearch/src/deepresearch/app.py#L719-L800)
- [app.py:271-326](file://apps/deepresearch/src/deepresearch/app.py#L271-L326)

### Agent Factory: Hooks, Subagents, Skills, Instructions
- Defines audit logger and safety gate hooks
- Creates planner, general-purpose, and code-reviewer subagents
- Provides programmatic skills and quick reference guide
- Includes research-specific instructions and routing rules

```mermaid
classDiagram
class AgentFactory {
+create_research_agent(mcp_servers, middleware)
+SUBAGENT_CONFIGS
+PROGRAMMATIC_SKILLS
+MAIN_INSTRUCTIONS
}
class Hooks {
+audit_logger_handler(input) HookResult
+safety_gate_handler(input) HookResult
}
class Subagents {
+planner
+general-purpose
+code-reviewer
}
class Skills {
+research-methodology
+report-writing
+diagram-design
+quick-reference
}
AgentFactory --> Hooks : "registers"
AgentFactory --> Subagents : "creates"
AgentFactory --> Skills : "loads"
```

**Diagram sources**
- [agent.py:376-430](file://apps/deepresearch/src/deepresearch/agent.py#L376-L430)
- [agent.py:69-81](file://apps/deepresearch/src/deepresearch/agent.py#L69-L81)
- [agent.py:179-225](file://apps/deepresearch/src/deepresearch/agent.py#L179-L225)
- [agent.py:271-338](file://apps/deepresearch/src/deepresearch/agent.py#L271-L338)

**Section sources**
- [agent.py:376-430](file://apps/deepresearch/src/deepresearch/agent.py#L376-L430)
- [prompts.py:3-320](file://apps/deepresearch/src/deepresearch/prompts.py#L3-L320)
- [SKILL.md (research-methodology):1-70](file://apps/deepresearch/skills/research-methodology/SKILL.md#L1-L70)

### MCP Server Integrations
- Web search: Tavily, Brave Search (npx), Jina URL reader (HTTP)
- Web scraping: Firecrawl (npx)
- Browser automation: Playwright (npx)
- Diagrams: Excalidraw via Docker-managed MCP server

```mermaid
graph LR
CFG["config.py:create_mcp_servers"] --> TAV["Tavily (npx)"]
CFG --> BRAVE["Brave (npx)"]
CFG --> JINA["Jina (HTTP)"]
CFG --> FIRECRAWL["Firecrawl (npx)"]
CFG --> PLAYWRIGHT["Playwright (npx)"]
CFG --> EXCAL["Excalidraw (Docker)"]
```

**Diagram sources**
- [config.py:58-151](file://apps/deepresearch/src/deepresearch/config.py#L58-L151)

**Section sources**
- [config.py:58-151](file://apps/deepresearch/src/deepresearch/config.py#L58-L151)

### Middleware and Security
- AuditMiddleware: tracks tool usage stats and durations
- PermissionMiddleware: blocks access to sensitive paths for file tools
- Safety gate hook prevents dangerous shell commands

```mermaid
flowchart TD
Call["Tool call"] --> Audit["AuditMiddleware.before_tool_call"]
Audit --> Exec["Execute tool"]
Exec --> Audit2["AuditMiddleware.after_tool_call"]
Exec --> Perm["PermissionMiddleware.before_tool_call"]
Perm --> |Allowed| Proceed["Proceed"]
Perm --> |Denied| Block["Block with reason"]
Exec --> Safety["Safety Gate Hook (PRE_TOOL_USE)"]
Safety --> |Allow| Proceed
Safety --> |Deny| Stop["Stop with reason"]
```

**Diagram sources**
- [middleware.py:33-122](file://apps/deepresearch/src/deepresearch/middleware.py#L33-L122)
- [agent.py:45-81](file://apps/deepresearch/src/deepresearch/agent.py#L45-L81)

**Section sources**
- [middleware.py:33-122](file://apps/deepresearch/src/deepresearch/middleware.py#L33-L122)
- [agent.py:45-81](file://apps/deepresearch/src/deepresearch/agent.py#L45-L81)

### Frontend: React-like SPA with Dark Theme
- Single-page app with tabs for sessions, files, and config
- Real-time WebSocket updates with streaming deltas
- File tree, preview panel, and Excalidraw canvas integration
- Tool rendering for search, subagents, and Excalidraw

```mermaid
graph TB
UI["index.html + app.js"] --> WS["WebSocket /ws/chat"]
WS --> Render["Render messages/tools/streaming"]
Render --> Files["File tree and preview"]
Render --> Canvas["Excalidraw canvas panel"]
Render --> Tasks["Task progress and notifications"]
```

**Diagram sources**
- [index.html:1-176](file://apps/deepresearch/static/index.html#L1-L176)
- [app.js:1-800](file://apps/deepresearch/static/app.js#L1-L800)
- [styles.css:1-800](file://apps/deepresearch/static/styles.css#L1-L800)

**Section sources**
- [index.html:1-176](file://apps/deepresearch/static/index.html#L1-L176)
- [app.js:1-800](file://apps/deepresearch/static/app.js#L1-L800)
- [styles.css:1-800](file://apps/deepresearch/static/styles.css#L1-L800)

### Docker-Based Sandbox and Deployment
- Python 3.12 base with Node.js and Docker CLI
- Installs pydantic-deep and related packages
- Exposes port 8080, runs FastAPI app module
- docker-compose includes Excalidraw canvas service

```mermaid
graph TB
Dev["Developer Machine"] --> Dockerfile["Dockerfile"]
Dockerfile --> Image["Container Image"]
Image --> Service["DeepResearch Service"]
Service --> Excal["Excalidraw Canvas Service"]
```

**Diagram sources**
- [Dockerfile:1-48](file://apps/deepresearch/Dockerfile#L1-L48)
- [docker-compose.yml:1-29](file://apps/deepresearch/docker-compose.yml#L1-L29)

**Section sources**
- [Dockerfile:1-48](file://apps/deepresearch/Dockerfile#L1-L48)
- [docker-compose.yml:1-29](file://apps/deepresearch/docker-compose.yml#L1-L29)
- [README.md:209-224](file://apps/deepresearch/README.md#L209-L224)

## Dependency Analysis
- Backend depends on pydantic-ai, pydantic-deep, and subagents libraries
- MCP servers are optional and dynamically configured based on environment variables
- Frontend depends on WebSocket connectivity and Excalidraw canvas availability
- Docker runtime provides sandbox isolation for file operations and code execution

```mermaid
graph LR
BE["Backend (FastAPI)"] --> PD["pydantic-deep"]
BE --> PAI["pydantic-ai"]
BE --> MW["pydantic-ai-middleware"]
BE --> SB["pydantic-ai-backend[docker]"]
BE --> SA["subagents-pydantic-ai"]
BE --> SUM["summarization-pydantic-ai"]
BE --> TODO["pydantic-ai-todo"]
```

**Diagram sources**
- [pyproject.toml:6-15](file://apps/deepresearch/pyproject.toml#L6-L15)
- [Dockerfile:21-31](file://apps/deepresearch/Dockerfile#L21-L31)

**Section sources**
- [pyproject.toml:6-15](file://apps/deepresearch/pyproject.toml#L6-L15)
- [Dockerfile:21-31](file://apps/deepresearch/Dockerfile#L21-L31)

## Performance Considerations
- WebSocket streaming reduces latency for real-time updates
- MCP servers are optional; disabling them reduces startup overhead
- Docker sandbox ensures resource isolation but adds container startup time
- AuditMiddleware provides tool usage metrics to identify bottlenecks
- Excalidraw canvas synchronization adds network overhead; disable if not needed

## Troubleshooting Guide
- MCP server failures: The backend attempts to rebuild the agent without problematic servers and logs warnings
- Docker availability: Excalidraw requires Docker; if unavailable, it is disabled with a warning
- Permission denials: PermissionMiddleware blocks sensitive paths; adjust tool arguments accordingly
- WebSocket disconnects: Frontend reconnects with exponential backoff; ensure backend remains reachable

**Section sources**
- [app.py:670-686](file://apps/deepresearch/src/deepresearch/app.py#L670-L686)
- [config.py:107-127](file://apps/deepresearch/src/deepresearch/config.py#L107-L127)
- [middleware.py:95-122](file://apps/deepresearch/src/deepresearch/middleware.py#L95-L122)
- [app.js:74-105](file://apps/deepresearch/static/app.js#L74-L105)

## Conclusion
DeepResearch delivers a powerful, extensible research assistant with robust integrations, secure sandboxing, and a polished UI. Its modular design enables easy addition of new MCP servers and skills, while the agent factory supports complex workflows through planning, subagents, and checkpointing.

## Appendices

### Setup Instructions
- Install prerequisites: Python 3.12+, uv, Node.js 20+, Docker
- Sync dependencies and optionally enable export extras
- Configure environment variables for MCP servers and Excalidraw
- Start Excalidraw canvas service and run the application

**Section sources**
- [README.md:12-62](file://apps/deepresearch/README.md#L12-L62)
- [README.md:84-98](file://apps/deepresearch/README.md#L84-L98)

### Environment Variables
- MODEL_NAME: LLM model selection
- TAVILY_API_KEY, BRAVE_API_KEY, JINA_API_KEY, FIRECRAWL_API_KEY: MCP server credentials
- PLAYWRIGHT_MCP: Enable Playwright browser automation
- EXCALIDRAW_ENABLED, EXCALIDRAW_SERVER_URL, EXCALIDRAW_CANVAS_URL: Excalidraw configuration

**Section sources**
- [README.md:84-98](file://apps/deepresearch/README.md#L84-L98)
- [config.py:30, 36, 107-127:30-36](file://apps/deepresearch/src/deepresearch/config.py#L30-L36)

### Deployment Options
- Local development: Run natively with uv; use Excalidraw canvas service
- Containerized: Build and run with Docker; mount Docker socket for sandboxing

**Section sources**
- [README.md:209-224](file://apps/deepresearch/README.md#L209-L224)
- [docker-compose.yml:1-29](file://apps/deepresearch/docker-compose.yml#L1-L29)

### Customization Guidelines
- Add new MCP servers in config.py with appropriate prefixes
- Extend agent factory with additional subagents and skills
- Customize prompts and instructions for domain-specific workflows
- Modify frontend UI by editing index.html, app.js, and styles.css

**Section sources**
- [config.py:58-151](file://apps/deepresearch/src/deepresearch/config.py#L58-L151)
- [agent.py:376-430](file://apps/deepresearch/src/deepresearch/agent.py#L376-L430)
- [prompts.py:3-320](file://apps/deepresearch/src/deepresearch/prompts.py#L3-L320)
- [index.html:1-176](file://apps/deepresearch/static/index.html#L1-L176)
- [styles.css:1-800](file://apps/deepresearch/static/styles.css#L1-L800)

### Security Considerations
- PermissionMiddleware blocks sensitive file paths
- Safety gate hook filters dangerous shell commands
- Docker sandbox isolates file operations and code execution
- AuditMiddleware logs tool usage for monitoring

**Section sources**
- [middleware.py:77-122](file://apps/deepresearch/src/deepresearch/middleware.py#L77-L122)
- [agent.py:45-81](file://apps/deepresearch/src/deepresearch/agent.py#L45-L81)
- [README.md:209-224](file://apps/deepresearch/README.md#L209-L224)

### Workspace and Context
- DEEP.md and MEMORY.md provide persistent context across sessions
- Workspace organization encourages modular research and reporting

**Section sources**
- [DEEP.md:1-12](file://apps/deepresearch/workspace/DEEP.md#L1-L12)
- [MEMORY.md:1-4](file://apps/deepresearch/workspace/MEMORY.md#L1-L4)
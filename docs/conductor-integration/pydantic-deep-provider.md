# PydanticDeepProvider Design

Status: **Proposed**

## Summary

Add `pydantic-deep` as a first-class Conductor provider by implementing
`PydanticDeepProvider` — an `AgentProvider` subclass that drives agent
execution through `pydantic-deepagents` (`create_deep_agent` + `agent.run`)
in the same way `CopilotProvider` drives the `github-copilot-sdk` and
`ClaudeProvider` drives the Anthropic SDK.

---

## Motivation

### How existing providers work

Conductor already has two providers that wrap full agentic-loop SDKs, not
just model transports:

| Provider | SDK | Execution model |
|---|---|---|
| `CopilotProvider` | `github-copilot-sdk` | `create_session` → `session.send(prompt)` → event loop with `tool.execution_start/complete` |
| `ClaudeProvider` | `anthropic` SDK | `messages.create` + in-process tool-use loop with manual dispatch |

Both SDKs manage:

- An autonomous tool-calling agentic loop
- Permission / approval semantics around tool calls
- Idle/session limits
- Streaming event emission (reasoning, tool start/complete, message)
- Structured output via JSON schema injection + parse-recovery loops
- MCP tool connectivity

`pydantic-deepagents` operates at exactly the same level:

| Concern | `github-copilot-sdk` | `pydantic-deepagents` |
|---|---|---|
| Execution model | `session.send()` event loop | `agent.run()` / `agent.iter()` pydantic-ai loop |
| Tool calling | SDK-dispatched, `tool.execution_start/complete` events | pydantic-ai `AbstractCapability.before/after_tool_execute` |
| Structured output | JSON schema in prompt + parse recovery | `output_type=` Pydantic model — no prompt hacking, no recovery loop |
| Reasoning | `reasoning_effort` on session | `thinking=` setting on `create_deep_agent` |
| MCP | `mcp_servers` on session | pydantic-ai native `MCP(url=)` / `MCP(command=)` capabilities |
| Model access | Copilot models only | Any pydantic-ai model + LiteLLM bridge |

### Why this matters

A `PydanticDeepProvider` gives Conductor:

1. **Multi-model from one provider** — via LiteLLM integration the same
   provider string covers Copilot models (`github_copilot/gpt-4o`),
   Anthropic models, OpenAI, Ollama, OpenRouter, and any OpenAI-compatible
   endpoint. Users stop needing separate `--provider copilot` vs
   `--provider claude` flags for model selection.

2. **Typed structured output without prompt engineering** — pydantic-ai
   converts `agent.output` schema → Pydantic model and enforces it at the
   Python type level, eliminating the current hack of injecting JSON schema
   text into the user prompt and the five-attempt parse-recovery loop in
   `CopilotProvider`.

3. **Richer built-in capabilities** — context compression, stuck-loop
   detection, and large-output eviction are available as opt-in flags rather
   than being hand-built in Conductor per provider.

4. **Path to deprecating duplicate providers** — once `PydanticDeepProvider`
   reaches parity with `CopilotProvider` and `ClaudeProvider`, those two can
   be soft-deprecated; users migrate by changing `provider:` in their YAML.

---

## Architecture

### Provider contract (unchanged)

All of the following already exist in `base.py` and are **not modified** by
this design.

```
AgentProvider (ABC)
  execute(agent, context, rendered_prompt, tools, interrupt_signal, event_callback) → AgentOutput
  validate_connection() → bool
  close()
  execute_dialog_turn(system_prompt, user_message, history, model) → str   # optional
  get_max_prompt_tokens(model) → int | None                                 # optional
```

`PydanticDeepProvider` implements the same contract as `CopilotProvider` and
`ClaudeProvider`.

### New file layout

```
src/conductor/providers/
  base.py          (unchanged)
  copilot.py       (unchanged)
  claude.py        (unchanged)
  pydantic_deep.py (new)
  factory.py       (extend case block)
  registry.py      (extend ProviderType literal)
reasoning.py       (unchanged — shared effort helper already used)
```

### Schema changes

Three literal strings gain a new member (`pydantic-deep`):

| Location | Current | After |
|---|---|---|
| `RuntimeConfig.provider` in `schema.py` | `"copilot" \| "openai-agents" \| "claude"` | `+ "pydantic-deep"` |
| `AgentDef.provider` in `schema.py` | `"copilot" \| "claude"` | `+ "pydantic-deep"` |
| `ProviderType` in `registry.py` | same | `+ "pydantic-deep"` |

---

## Implementation

### `PydanticDeepProvider.__init__`

```python
class PydanticDeepProvider(AgentProvider):
    def __init__(
        self,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = 600.0,
        mcp_servers: dict[str, Any] | None = None,
        max_agent_iterations: int | None = None,
        default_reasoning_effort: ReasoningEffort | None = None,
    ) -> None:
        ...
```

`model` follows pydantic-ai format: `"anthropic:claude-sonnet-4-6"`,
`"openai:gpt-4o"`, `"github_copilot/gpt-4o"` (via LiteLLM), or any
pydantic-ai model string. When `None`, defaults to
`"anthropic:claude-sonnet-4-6"`.

### `execute` — core execution path

```python
async def execute(self, agent, context, rendered_prompt, tools=None,
                  interrupt_signal=None, event_callback=None) -> AgentOutput:
```

Internally:

```
1. Build output_type Pydantic model from agent.output schema
   (see "Structured Output" below)

2. Build capabilities list:
   - EventCapability (new, see "Event Mapping" below)
   - MCP capabilities from mcp_servers config
   - Optional reasoning capability from agent.reasoning.effort

3. Create pydantic-ai Agent via create_deep_agent(
       model=resolved_model,
       output_type=output_type,
       capabilities=capabilities,
       include_todo=False,         # Conductor manages planning
       include_filesystem=False,   # Conductor manages tools via MCP
       include_subagents=False,    # Conductor manages agent DAG
       include_memory=False,       # Conductor manages context
       include_skills=False,       # Conductor manages skills
       web_search=False,
       web_fetch=False,
       context_manager=False,      # Conductor manages context limits
   )

4. Create DeepAgentDeps(backend=StateBackend())

5. await agent.run(rendered_prompt, deps=deps)

6. Extract result.output → dict, result.usage() → tokens

7. Return AgentOutput(content=..., input_tokens=..., output_tokens=..., model=...)
```

All the deep-agent capabilities (memory, subagents, todos, compression) are
**disabled** at the `execute` level. They are Conductor-level concerns already
handled by the workflow engine. Users who want them can enable them per-agent
via an `agent_options:` extension field in a follow-on iteration.

### Structured output

Conductor's `agent.output` is a `dict[str, OutputField]` with recursive
`OutputField(type, items, properties)`. The provider dynamically builds a
Pydantic model from this schema at call time:

```python
def _build_output_model(self, output_schema: dict[str, OutputField]) -> type[BaseModel]:
    """Convert Conductor OutputField schema → Pydantic BaseModel class."""
    fields: dict[str, Any] = {}
    for name, field in output_schema.items():
        fields[name] = (_conductor_type_to_python(field), ...)
    return create_model("AgentOutput", **fields)
```

`_conductor_type_to_python` recursively maps:

| OutputField.type | Python type |
|---|---|
| `"string"` | `str` |
| `"number"` | `float` |
| `"boolean"` | `bool` |
| `"array"` | `list[T]` (T from `items`) |
| `"object"` | nested `BaseModel` (from `properties`) |

When `agent.output` is `None`, `output_type` is omitted and pydantic-ai
returns a plain `str`, which is wrapped as `{"result": response_str}`.

This completely replaces the prompt-injection + parse-recovery loop in
`CopilotProvider`. The model receives a formal tool definition from pydantic-ai
and is forced to emit valid structured output at the API level.

### Event mapping

Conductor consumers (console renderer, JSONL logger, web dashboard) require
these event types emitted via `event_callback`:

| Conductor event | Trigger |
|---|---|
| `agent_turn_start {"turn": "awaiting_model"}` | Before each model request |
| `agent_turn_start {"turn": N}` | Each tool-call iteration |
| `agent_message {"content": "..."}` | Each text response part |
| `agent_reasoning {"content": "..."}` | Thinking/reasoning blocks |
| `agent_tool_start {"tool_name": "...", "arguments": "..."}` | Tool call begins |
| `agent_tool_complete {"tool_name": "...", "result": "..."}` | Tool call finishes |

pydantic-ai exposes lifecycle hooks via `AbstractCapability`:

```python
class EventCapability(AbstractCapability[Any]):
    def __init__(self, callback: EventCallback, turn_counter: list[int]) -> None: ...

    async def before_model_request(self, ctx, request_context) -> None:
        callback("agent_turn_start", {"turn": "awaiting_model"})

    async def after_model_request(self, ctx, response) -> None:
        turn_counter[0] += 1
        callback("agent_turn_start", {"turn": turn_counter[0]})
        for part in response.parts:
            if isinstance(part, TextPart):
                callback("agent_message", {"content": part.content})
            elif isinstance(part, ThinkingPart):
                callback("agent_reasoning", {"content": part.thinking})

    async def before_tool_execute(self, ctx, call, tool_def) -> None:
        callback("agent_tool_start", {
            "tool_name": call.tool_name,
            "arguments": format_tool_arguments(call.args_as_dict()),
        })

    async def after_tool_execute(self, ctx, call, tool_def, result) -> None:
        callback("agent_tool_complete", {
            "tool_name": call.tool_name,
            "result": extract_tool_result_text(result),
        })
```

`format_tool_arguments` and `extract_tool_result_text` already exist in
`providers/_event_format.py` — reused unchanged.

### Reasoning effort

Conductor's unified `ReasoningEffort` (`low` | `medium` | `high` | `xhigh`)
maps to pydantic-deepagents' `thinking=` parameter:

| Conductor effort | pydantic-deep `thinking=` |
|---|---|
| `None` | `"high"` (deepagents default) |
| `"low"` | `"low"` |
| `"medium"` | `"medium"` |
| `"high"` | `"high"` |
| `"xhigh"` | `"xhigh"` |

pydantic-deep passes this through to the native model API — pydantic-ai maps
it to Anthropic extended-thinking budget or OpenAI reasoning tokens as
appropriate. No separate validation needed; pydantic-ai raises at `agent.run`
time if the model doesn't support the requested effort level, which propagates
as `ProviderError`.

### MCP tool connectivity

Conductor's `MCPServerDef` (type `stdio` or `http`/`sse`) maps to pydantic-ai
native MCP capabilities:

```python
def _build_mcp_capabilities(self, mcp_servers: dict[str, MCPServerDef]) -> list[Any]:
    from pydantic_ai.capabilities import MCP
    caps = []
    for name, srv in mcp_servers.items():
        if srv.type == "stdio":
            caps.append(MCP(command=srv.command, args=srv.args or [], env=srv.env or {}))
        elif srv.type in ("http", "sse"):
            caps.append(MCP(url=srv.url))
    return caps
```

All three MCP types (stdio, http, sse) are supported — a direct improvement
over `ClaudeProvider` which only supports `stdio`.

### LiteLLM model strings for Copilot models

Users who previously used `provider: copilot` can migrate transparently:

```yaml
# Before
runtime:
  provider: copilot
  default_model: gpt-4o

# After
runtime:
  provider: pydantic-deep
  default_model: github_copilot/gpt-4o
```

The `LiteLLMModel` adapter in pydantic-deepagents handles the OAuth token
flow and required headers (`Editor-Version`, `Copilot-Integration-Id`)
automatically.

### `validate_connection`

```python
async def validate_connection(self) -> bool:
    """Attempt a minimal model call to verify credentials and reachability."""
    try:
        agent = create_deep_agent(
            model=self._default_model,
            include_todo=False,
            include_filesystem=False,
            include_subagents=False,
            include_memory=False,
            include_skills=False,
            web_search=False,
            web_fetch=False,
            context_manager=False,
        )
        deps = DeepAgentDeps(backend=StateBackend())
        await agent.run("ping", deps=deps, usage_limits=UsageLimits(request_limit=1))
        return True
    except Exception:
        return False
```

### `close`

pydantic-ai agents are stateless across runs; no persistent connection to
teardown. `close()` is a no-op except for MCP capability teardown if
pydantic-ai adds that lifecycle hook in the future.

---

## Factory and registry wiring

### `factory.py`

```python
case "pydantic-deep":
    if not PYDANTIC_DEEP_AVAILABLE:
        raise ProviderError(
            "pydantic-deep provider requires pydantic-deep package",
            suggestion="Install with: uv add 'pydantic-deep>=0.3.14'",
        )
    provider = PydanticDeepProvider(
        model=default_model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout or 600.0,
        mcp_servers=mcp_servers,
        max_agent_iterations=max_agent_iterations,
        default_reasoning_effort=default_reasoning_effort,
    )
```

### `registry.py`

```python
ProviderType = Literal["copilot", "openai-agents", "claude", "pydantic-deep"]
```

### Optional dependency

pydantic-deep is not added to `pyproject.toml` core dependencies. It is
optional, checked at import time:

```python
try:
    from pydantic_deep import create_deep_agent, DeepAgentDeps
    from pydantic_ai_backends import StateBackend
    from pydantic_ai.usage import UsageLimits
    PYDANTIC_DEEP_AVAILABLE = True
except ImportError:
    PYDANTIC_DEEP_AVAILABLE = False
```

Users who want it run `uv add 'pydantic-deep>=0.3.14'`, mirroring how
`ClaudeProvider` gates on `anthropic`.

---

## YAML usage

### Simple usage

```yaml
workflow:
  name: research
  entry_point: researcher
  runtime:
    provider: pydantic-deep
    default_model: anthropic:claude-sonnet-4-6

agents:
  - name: researcher
    prompt: "Research {{ workflow.input.topic }} and summarize key findings."
    output:
      summary:
        type: string
      key_points:
        type: array
        items:
          type: string
    routes:
      - to: $end
```

### Copilot model via LiteLLM

```yaml
runtime:
  provider: pydantic-deep
  default_model: github_copilot/gpt-4o
```

### Multi-provider workflow (unchanged pattern)

```yaml
runtime:
  provider: pydantic-deep        # default
  default_model: anthropic:claude-sonnet-4-6

agents:
  - name: planner
    # uses default provider
    ...

  - name: coder
    provider: copilot             # still valid — per-agent override
    model: gpt-4o
    ...
```

---

## Interrupt / mid-run cancellation

pydantic-ai's `agent.run()` is a coroutine. Conductor's `interrupt_signal`
(an `asyncio.Event`) is handled by racing the coroutine against the event:

```python
run_task = asyncio.create_task(agent.run(rendered_prompt, deps=deps))
interrupt_task = asyncio.create_task(interrupt_signal.wait())
done, pending = await asyncio.wait(
    [run_task, interrupt_task],
    return_when=asyncio.FIRST_COMPLETED,
)
for t in pending:
    t.cancel()

if interrupt_task in done:
    # Interrupted — return partial AgentOutput
    run_task.cancel()
    return AgentOutput(content={"result": ""}, ..., partial=True)

result = run_task.result()
```

This is simpler than the Copilot provider's `session.abort()` path because
pydantic-ai tasks are plain asyncio coroutines with no custom RPC protocol.

---

## Retry contract

Provider-level retry (exponential backoff, `max_attempts=3`) is implemented
in `PydanticDeepProvider._execute_with_retry`, mirroring `CopilotProvider`.
pydantic-ai raises `ModelRetry` internally for transient errors; the provider
wraps unknown exceptions as `ProviderError(is_retryable=True)` and API key /
validation errors as `ProviderError(is_retryable=False)`. Per-agent
`retry:` policy from `AgentDef` is applied the same way as in other providers.

---

## Dialog turns

`execute_dialog_turn` is implemented by creating a minimal agent (no toolsets,
no capabilities) and calling `agent.run` with the composed message history.
This provides parity with `CopilotProvider.execute_dialog_turn` used by the
dialog evaluator.

---

## Token reporting

`result.usage()` from pydantic-ai returns a `RequestUsage` object:

```python
usage = result.usage()
return AgentOutput(
    content=...,
    input_tokens=usage.input_tokens,
    output_tokens=usage.output_tokens,
    tokens_used=(usage.input_tokens or 0) + (usage.output_tokens or 0),
    model=self._default_model,
)
```

---

## Test plan

Tests mirror the existing provider suites in `tests/test_providers/`:

| Test file | Coverage |
|---|---|
| `test_pydantic_deep.py` | Core execute, output schema → Pydantic model, token extraction |
| `test_pydantic_deep_events.py` | `EventCapability` emits correct Conductor event types |
| `test_pydantic_deep_mcp.py` | stdio and http MCP configs build correct pydantic-ai capabilities |
| `test_pydantic_deep_reasoning.py` | Effort levels map correctly to `thinking=` |
| `test_pydantic_deep_interrupt.py` | `interrupt_signal` cancels run, returns `partial=True` |
| `test_pydantic_deep_retry.py` | Transient errors retry, fatal errors do not |
| `test_pydantic_deep_factory.py` | `create_provider("pydantic-deep")` wires up correctly |

All tests use a pydantic-ai `TestModel` fixture rather than real API calls.
`TestModel` is the pydantic-ai-native equivalent of `CopilotProvider`'s
`mock_handler` parameter.

---

## Provider parity checklist

Per `AGENTS.md`, all providers must maintain parity on the following. Items
marked ✓ are satisfied by this design.

| Requirement | Status |
|---|---|
| `agent_turn_start {"turn": "awaiting_model"}` before API call | ✓ `before_model_request` |
| `agent_turn_start {"turn": N}` at each iteration | ✓ `after_model_request` counter |
| `agent_message` for text content | ✓ `TextPart` in `after_model_request` |
| `agent_reasoning` for reasoning/thinking content | ✓ `ThinkingPart` in `after_model_request` |
| `agent_tool_start` / `agent_tool_complete` | ✓ `before/after_tool_execute` |
| Same `AgentOutput` field population | ✓ via `result.usage()` |
| Same retry semantics | ✓ mirrors `CopilotProvider._execute_with_retry` |
| `reasoning.effort` → native API | ✓ maps to `thinking=` |
| `execute_dialog_turn` | ✓ minimal agent, no toolsets |
| `get_max_prompt_tokens` | default `None` (best-effort; pydantic-ai exposes no model-metadata endpoint today) |

---

## Migration path

| Scenario | What changes |
|---|---|
| New users wanting multi-model | Use `provider: pydantic-deep` + pydantic-ai model string |
| Existing Copilot users | Change `provider:` to `pydantic-deep`, prepend `github_copilot/` to model name |
| Existing Claude users | Change `provider:` to `pydantic-deep`, prepend `anthropic:` to model name |
| Mixed-provider workflows | Keep per-agent `provider: copilot` / `provider: claude` overrides; `pydantic-deep` as default |

`CopilotProvider` and `ClaudeProvider` are **not removed** by this design.
They remain fully supported. Deprecation is a separate decision after
`PydanticDeepProvider` reaches sustained production use.

---

## Open questions

1. **Filesystem tools during agent execution** — pydantic-deepagents ships
   a console toolset (read, write, execute). Should `PydanticDeepProvider`
   enable it when `tools` is non-empty and Conductor's MCP servers do not
   already cover filesystem ops? Decision deferred to implementation phase.

2. **`include_memory` / per-agent deep capabilities** — some workflows may
   benefit from persistent `MEMORY.md` within a single agent step. An
   optional `agent_options:` extension field could expose these on a
   per-agent basis without coupling the core schema to pydantic-deep.

3. **pydantic-deep version pinning** — `>=0.3.14` is the minimum that
   exposes `after_tool_execute` on `AbstractCapability`. The package
   evolves quickly; consider a tighter upper bound during initial rollout.

4. **`get_max_prompt_tokens`** — pydantic-ai does not expose a
   model-listing endpoint today. Until it does, the context-window bar
   in the web dashboard will be hidden for pydantic-deep agents. This is
   a safe degradation (same behavior as today for `CopilotProvider` models
   that return `None`).

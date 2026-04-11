# Stuck Loop Detection

The `StuckLoopDetection` capability detects repetitive agent behavior and intervenes before the agent wastes tokens on unproductive loops. It is **enabled by default**.

## Quick Start

```python
from pydantic_deep import create_deep_agent

# Enabled by default
agent = create_deep_agent()

# Disable
agent = create_deep_agent(stuck_loop_detection=False)

# Custom: use as a capability directly
from pydantic_deep import StuckLoopDetection

agent = create_deep_agent(
    stuck_loop_detection=False,
    capabilities=[StuckLoopDetection(max_repeated=5, action="error")],
)
```

## Detection Patterns

### Repeated Identical Calls

Same tool called with the same arguments N times in a row:

```
read_file(path="/src/app.py")    # 1
read_file(path="/src/app.py")    # 2
read_file(path="/src/app.py")    # 3  -> TRIGGERED
```

### Alternating A-B-A-B

Two tool calls alternating back and forth:

```
grep(pattern="TODO")             # A
read_file(path="/src/app.py")    # B
grep(pattern="TODO")             # A
read_file(path="/src/app.py")    # B  -> TRIGGERED
```

### No-Op Calls

Same tool returning the same result repeatedly (the operation has no effect):

```
list_files(path="/src")  -> ["a.py", "b.py"]
list_files(path="/src")  -> ["a.py", "b.py"]
list_files(path="/src")  -> ["a.py", "b.py"]  -> TRIGGERED
```

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_repeated` | `int` | `3` | Number of repetitions before triggering |
| `action` | `str` | `"warn"` | `"warn"` raises `ModelRetry` (model can self-correct), `"error"` raises `StuckLoopError` (run aborts) |
| `detect_repeated` | `bool` | `True` | Enable repeated identical call detection |
| `detect_alternating` | `bool` | `True` | Enable A-B-A-B pattern detection |
| `detect_noop` | `bool` | `True` | Enable no-op (same result) detection |

## How It Works

The capability uses the `after_tool_execute` hook to track every tool call:

1. After each tool call, it records `(tool_name, args_hash)` and `(tool_name, result_hash)`
2. Checks the recorded history against the three detection patterns
3. If a pattern is detected:
    - **`action="warn"`** — raises `ModelRetry` with a message explaining the pattern. The model receives the feedback and can try a different approach
    - **`action="error"`** — raises `StuckLoopError` to abort the run immediately

Per-run state isolation via `for_run()` ensures concurrent agent runs don't share detection history.

## Actions

### Warn (default)

```python
StuckLoopDetection(action="warn")
```

Raises `ModelRetry` — the model receives the error as a retry prompt and can self-correct:

```
You called `read_file` with identical arguments 3 times in a row.
Try a different approach.
```

### Error

```python
StuckLoopDetection(action="error")
```

Raises `StuckLoopError` — the run aborts. Useful when you want hard limits:

```python
from pydantic_deep import StuckLoopError

try:
    result = await agent.run("...", deps=deps)
except StuckLoopError as e:
    print(f"Agent stuck: {e.pattern} — {e}")
```

## Components

| Component | Description |
|-----------|-------------|
| [`StuckLoopDetection`][pydantic_deep.capabilities.stuck_loop.StuckLoopDetection] | Capability that detects stuck loops |
| [`StuckLoopError`][pydantic_deep.capabilities.stuck_loop.StuckLoopError] | Exception raised when `action="error"` |

## Next Steps

- [Eviction](eviction.md) -- Large tool output management
- [Cost Tracking](cost-tracking.md) -- Token and cost monitoring
- [Hooks](hooks.md) -- Custom lifecycle hooks

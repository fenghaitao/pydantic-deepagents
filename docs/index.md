<h1 align="center">Pydantic Deep Agents</h1>
<p align="center">
  <em>Build autonomous AI assistants in Python — file access, web search, memory, multi-agent teams, and unlimited context, out of the box.</em>
</p>
<p align="center">
  <a href="https://github.com/vstorm-co/pydantic-deepagents/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/pydantic-deepagents/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/vstorm-co/pydantic-deepagents"><img src="https://img.shields.io/badge/coverage-100%25-brightgreen" alt="Coverage"></a>
  <a href="https://pypi.org/project/pydantic-deep/"><img src="https://img.shields.io/pypi/v/pydantic-deep.svg" alt="PyPI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue" alt="Python"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
</p>

---

**pydantic-deep** is a Python library that solves the gap between an AI language model and a useful autonomous assistant.

A language model on its own can answer questions, but it cannot read your files, run code, search the web, remember things between sessions, or work on several tasks at once. **pydantic-deep provides all of that infrastructure** — so you wire up `create_deep_agent()` once and the model gains: file read/write/edit, shell execution, web search and browsing, persistent memory, parallel sub-tasks, and automatic handling of long conversations. You focus on what the agent should do; pydantic-deep handles the rest.

Built on [Pydantic AI](https://ai.pydantic.dev/). Works with Claude, GPT-4, Gemini, and any other model supported by Pydantic AI.

Think of it as the open-source, self-hosted foundation for building your own [Claude Code](https://claude.ai/code), [Manus](https://manus.im/), or [Devin](https://devin.ai/)-style AI assistant.

## Why use Pydantic Deep Agents?

1. **Built on Pydantic AI**: Leverages the same ergonomic design that made FastAPI successful - type hints, async/await, and familiar Python patterns.

2. **Production Ready**: 100% test coverage, strict typing with Pyright + MyPy, and battle-tested in real applications.

3. **Modular Architecture**: Use the full framework or cherry-pick components. Each capability is an independent package you can use standalone.

4. **Secure Execution**: Docker sandbox for isolated code execution, permission controls, and human-in-the-loop approval workflows.

## Hello World Example

```python
import asyncio
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend

async def main():
    # Create a deep agent with all capabilities
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful coding assistant.",
    )

    # Create dependencies with in-memory storage
    deps = DeepAgentDeps(backend=StateBackend())

    # Run the agent
    result = await agent.run(
        "Create a Python function that calculates fibonacci numbers",
        deps=deps,
    )

    print(result.output)

asyncio.run(main())
```

## Tools & Dependency Injection Example

```python
from pydantic_ai import RunContext
from pydantic_deep import create_deep_agent, DeepAgentDeps

# Define a custom tool
async def get_weather(
    ctx: RunContext[DeepAgentDeps],
    city: str,
) -> str:
    """Get weather for a city."""
    # Access dependencies via ctx.deps
    return f"Weather in {city}: Sunny, 22°C"

# Create agent with custom tools
agent = create_deep_agent(
    tools=[get_weather],
    instructions="You can check weather and work with files.",
)
```

## Core Capabilities

| Capability | Description |
|------------|-------------|
| **Planning** | Built-in todo list for task decomposition and progress tracking |
| **Filesystem** | Read, write, edit files with grep and glob support |
| **Subagents** | Delegate specialized tasks to isolated subagents |
| **Skills** | Modular capability packages loaded on-demand |
| **Backends** | StateBackend, LocalBackend, DockerSandbox, CompositeBackend |
| **Summarization** | Automatic context management for long conversations |

## Modular Ecosystem

Pydantic Deep Agents is built from standalone packages you can use independently:

| Package | Description |
|---------|-------------|
| [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend) | File storage, Docker sandbox, permission controls |
| [pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo) | Task planning with PostgreSQL and event streaming |
| [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai) | Multi-agent orchestration |
| [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai) | Context management processors |

## Installation

```bash
pip install pydantic-deep
```

With Docker sandbox support:

```bash
pip install pydantic-deep[sandbox]
```

## llms.txt

Pydantic Deep Agents supports the [llms.txt](https://llmstxt.org/) standard. Access documentation at `/llms.txt` for LLM-optimized content.

## Next Steps

- [Installation](installation.md) - Get started in minutes
- [Core Concepts](concepts/index.md) - Learn about agents, backends, and toolsets
- [Examples](examples/index.md) - See pydantic-deep in action
- [API Reference](api/index.md) - Complete API documentation
- [Getting Help](getting-help.md) - Report bugs or request features
- [Contributing](contributing.md) - How to contribute code or documentation

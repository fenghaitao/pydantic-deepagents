"""Headless (non-interactive) runner for pydantic-deep.

Executes a single task without user interaction and returns the result.
Designed for benchmarks, CI/CD pipelines, and scripted automation.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from pydantic_ai.usage import Usage

from apps.cli.agent import create_cli_agent
from pydantic_deep.deps import DEFAULT_USAGE_LIMITS


async def execute_headless(  # noqa: C901
    *,
    task: str,
    working_dir: str,
    model: str | None = None,
    output_json: bool = False,
    max_turns: int | None = None,
    timeout: int | None = None,
    web_search: bool | None = None,
    web_fetch: bool | None = None,
    thinking: str | None = None,
    include_todo: bool | None = None,
    include_subagents: bool | None = None,
    include_skills: bool | None = None,
    include_plan: bool | None = None,
    include_memory: bool | None = None,
    include_teams: bool | None = None,
    context_discovery: bool | None = None,
    temperature: float | None = None,
    config_path: str | None = None,
    sandbox: str | None = None,
    workspace: str | None = None,
    verbose: bool = False,
    include_browser: bool | None = None,
    browser_headless: bool | None = None,
    code_graph: bool | None = None,
    project_id: str | None = None,
    user_id: str | None = None,
    enable_mcp: bool = False,
) -> int:
    """Execute a task in headless mode and print the result.

    All feature flags default to ``None`` which means "use config.toml
    defaults" — the same defaults as the interactive TUI. Pass explicit
    values to override.

    Args:
        task: The task description to execute.
        working_dir: Filesystem root directory.
        model: Model override (default: from config).
        output_json: Whether to output result as JSON.
        max_turns: Maximum number of agent turns.
        timeout: Timeout in seconds.
        web_search: Enable web search. None = from config.
        web_fetch: Enable web fetch. None = from config.
        thinking: Thinking effort level. None = from config.
        include_todo: Enable todo tools. None = from config.
        include_subagents: Enable subagent tools. None = from config.
        include_skills: Enable skills. None = from config.
        include_plan: Enable plan mode. None = from config.
        include_memory: Enable persistent memory. None = from config.
        config_path: Override config file path.
        code_graph: Enable code graph capabilities. None = from config.
        project_id: Potpie project ID (overrides config).
        user_id: Potpie user ID (overrides config).

    Returns:
        Exit code (0 for success, 1 for error).
    """
    from pathlib import Path

    from apps.cli.init import ensure_initialized

    ensure_initialized(Path(working_dir))

    agent_kwargs: dict[str, Any] = {
        "model": model,
        "working_dir": working_dir,
        "non_interactive": True,
    }
    if config_path is not None:
        agent_kwargs["config_path"] = Path(config_path)
    # Only pass explicit overrides — None means "use config default"
    if web_search is not None:
        agent_kwargs["web_search"] = web_search
    if web_fetch is not None:
        agent_kwargs["web_fetch"] = web_fetch
    if thinking is not None:
        # "false" from CLI string → False bool
        agent_kwargs["thinking"] = False if thinking.lower() == "false" else thinking
    if include_todo is not None:
        agent_kwargs["include_todo"] = include_todo
    if include_subagents is not None:
        agent_kwargs["include_subagents"] = include_subagents
    if include_skills is not None:
        agent_kwargs["include_skills"] = include_skills
    if include_plan is not None:
        agent_kwargs["include_plan"] = include_plan
    if include_memory is not None:
        agent_kwargs["include_memory"] = include_memory
    if include_teams is not None:
        agent_kwargs["include_teams"] = include_teams
    if context_discovery is not None:
        agent_kwargs["context_discovery"] = context_discovery
    if temperature is not None:
        agent_kwargs["temperature"] = temperature
    if sandbox is not None:
        agent_kwargs["sandbox"] = sandbox
    if workspace is not None:
        agent_kwargs["workspace"] = workspace
    if include_browser is not None:
        agent_kwargs["include_browser"] = include_browser
    if browser_headless is not None:
        agent_kwargs["browser_headless"] = browser_headless
    if code_graph is not None and code_graph:
        from pathlib import Path as _Path

        from apps.cli.code_graph import build_code_graph_capabilities

        # Resolve the configured code-graph provider (potpie | cgc | graphify).
        _cg_provider = "potpie"
        try:
            from apps.cli.config import load_config as _load_config

            _cg_provider = _load_config(agent_kwargs.get("config_path")).kg.provider or "potpie"
        except Exception:
            pass

        user_id = user_id or "defaultuser"
        _root = _Path(working_dir) if working_dir else _Path.cwd()
        _status = None if not verbose else (lambda msg: print(f"[dim]{msg}[/dim]"))
        cap = None
        simics_cap = None
        try:
            cap, simics_cap, _extra_cg, project_id = await build_code_graph_capabilities(
                _cg_provider,
                project_id=project_id,
                user_id=user_id,
                root=_root,
                on_status=_status,
            )
            if _cg_provider == "potpie":
                if cap is None:
                    print(
                        "[yellow]Warning: --code-graph requested but no Potpie project found. "
                        "Pass --project-id <id> or set a default with: "
                        "pydantic-deep config set kg.project_id <id>[/yellow]",
                        file=sys.stderr,
                    )
                if simics_cap is None:
                    print(
                        "[yellow]Warning: --code-graph requested but no Simics device project found. "
                        "Pass --project-id <id> or set a default with: "
                        "pydantic-deep config set kg.project_id <id>[/yellow]",
                        file=sys.stderr,
                    )
            elif _extra_cg:
                _ex = list(agent_kwargs.get("extra_capabilities") or [])
                _ex.extend(_extra_cg)
                agent_kwargs["extra_capabilities"] = _ex
            else:
                print(
                    f"[yellow]Warning: --code-graph requested but no {_cg_provider} graph found. "
                    "Build it first (e.g. `graphify .` for graphify, `cgc index .` for cgc).[/yellow]",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[yellow]Warning: could not load {_cg_provider} code-graph tools: {e}[/yellow]")

        agent_kwargs["kg_capability"] = cap
        agent_kwargs["simics_dev_capability"] = simics_cap

    # Auto-connect to code-graph MCP server when --mcp is passed.
    # The provider is determined by kg.provider in config: "potpie" (streamable-http) or "cgc" (stdio).
    # Both use the toolset API (MCPServerStreamableHTTP / MCPServerStdio) with tool_prefix and
    # process_tool_call for project_id injection.
    import asyncio as _asyncio
    import os as _os

    if enable_mcp:
        # Resolve provider from config
        _kg_provider = "potpie"
        try:
            from apps.cli.config import load_config as _load_config
            _cfg = _load_config(agent_kwargs.get("config_path"))
            _kg_provider = _cfg.kg.provider or "potpie"
        except Exception:
            pass

        # Resolve project_id: CLI --project-id > env var > config file kg.project_id
        _pid = project_id or _os.environ.get("POTPIE_PROJECT_ID")
        if not _pid:
            try:
                _pid = _cfg.kg.project_id or None  # type: ignore[possibly-undefined]
            except Exception:
                pass

        if _kg_provider == "potpie":
            _potpie_mcp_port = _os.environ.get("POTPIE_MCP_PORT", "13100")
            _potpie_mcp_host = _os.environ.get("POTPIE_MCP_HOST", "127.0.0.1")
            try:
                _reader, _writer = await _asyncio.wait_for(
                    _asyncio.open_connection(_potpie_mcp_host, int(_potpie_mcp_port)),
                    timeout=1.0,
                )
                _writer.close()
                await _writer.wait_closed()

                from pydantic_ai.capabilities import MCP
                from pydantic_deep.capabilities.code_graph_mcp import CodeGraphMCPCapability

                # Use streamable-http transport (/mcp) — more reliable than SSE in CI/server envs.
                # Override path via POTPIE_MCP_PATH env var if you're running an older SSE server.
                _potpie_mcp_path = _os.environ.get("POTPIE_MCP_PATH", "/mcp")
                _mcp_url = f"http://{_potpie_mcp_host}:{_potpie_mcp_port}{_potpie_mcp_path}"
                _extra = list(agent_kwargs.get("extra_capabilities") or [])
                _extra.append(CodeGraphMCPCapability(wrapped=MCP(url=_mcp_url), prefix="potpie", project_id=_pid))
                agent_kwargs["extra_capabilities"] = _extra
                print(
                    f"Potpie MCP connected: {_mcp_url}"
                    + (f" (project_id={_pid})" if _pid else ""),
                    file=sys.stderr,
                )
            except (_asyncio.TimeoutError, OSError):
                print(
                    f"Warning: --mcp: could not connect to Potpie MCP server at "
                    f"{_potpie_mcp_host}:{_potpie_mcp_port}. "
                    "Start it with: potpie-mcp start --transport streamable-http --background",
                    file=sys.stderr,
                )
            except Exception as _mcp_exc:
                print(f"Warning: --mcp: unexpected error: {_mcp_exc}", file=sys.stderr)

        elif _kg_provider == "cgc":
            try:
                import shutil
                from pathlib import Path as _Path

                from pydantic_ai.capabilities import MCP
                from pydantic_ai.mcp import MCPServerStdio
                from pydantic_deep.capabilities.code_graph_mcp import CodeGraphMCPCapability

                # Resolve cgc command: prefer installed 'cgc' on PATH, otherwise
                # invoke via the in-tree source with sys.executable + PYTHONPATH.
                _cgc_bin = shutil.which("cgc")
                if _cgc_bin:
                    _cgc_cmd = _cgc_bin
                    _cgc_args = ["mcp", "start"]
                    # MCP SDK's default env only passes a small allowlist (HOME, PATH, etc.)
                    # so we must explicitly pass the full environment for CGC_RUNTIME_DB_TYPE etc.
                    _cgc_env = _os.environ.copy()
                else:
                    _cgc_src = str(
                        _Path(__file__).resolve().parent.parent.parent
                        / "code-graph-providers" / "CodeGraphContext" / "src"
                    )
                    _cgc_cmd = sys.executable
                    _cgc_args = ["-m", "codegraphcontext", "mcp", "start"]
                    _cgc_env = {**_os.environ, "PYTHONPATH": _cgc_src}

                _cgc_stdio = MCPServerStdio(_cgc_cmd, _cgc_args, env=_cgc_env, timeout=30)
                _extra = list(agent_kwargs.get("extra_capabilities") or [])
                _extra.append(CodeGraphMCPCapability(
                    wrapped=MCP(url="stdio://cgc", local=_cgc_stdio),
                    prefix="cgc",
                    project_id=_pid,
                ))
                agent_kwargs["extra_capabilities"] = _extra
                print("CGC MCP server configured (stdio: cgc mcp start)", file=sys.stderr)
            except Exception as _mcp_exc:
                print(f"Warning: --mcp: unexpected error: {_mcp_exc}", file=sys.stderr)

        elif _kg_provider == "graphify":
            try:
                import shutil
                from pathlib import Path as _Path

                from pydantic_ai.capabilities import MCP
                from pydantic_ai.mcp import MCPServerStdio
                from pydantic_deep.capabilities.code_graph_mcp import CodeGraphMCPCapability

                # Resolve graphify graph path: prefer working dir's graphify-out.
                _gf_root = _Path(working_dir) if working_dir else _Path.cwd()
                _gf_graph = str(_gf_root / "graphify-out" / "graph.json")

                # Prefer the installed 'graphify-mcp' script, otherwise invoke
                # the in-tree source via sys.executable + PYTHONPATH.
                _gf_bin = shutil.which("graphify-mcp")
                if _gf_bin:
                    _gf_cmd = _gf_bin
                    _gf_args = [_gf_graph]
                    _gf_env = _os.environ.copy()
                else:
                    _gf_src = str(
                        _Path(__file__).resolve().parent.parent.parent
                        / "code-graph-providers" / "graphify"
                    )
                    _gf_cmd = sys.executable
                    _gf_args = ["-m", "graphify.serve", _gf_graph]
                    _gf_env = {**_os.environ, "PYTHONPATH": _gf_src}

                _gf_stdio = MCPServerStdio(_gf_cmd, _gf_args, env=_gf_env, timeout=30)
                _extra = list(agent_kwargs.get("extra_capabilities") or [])
                _extra.append(CodeGraphMCPCapability(
                    wrapped=MCP(url="stdio://graphify", local=_gf_stdio),
                    prefix="graphify",
                    project_id=_pid,
                ))
                agent_kwargs["extra_capabilities"] = _extra
                print(
                    f"Graphify MCP server configured (stdio: graphify.serve {_gf_graph})",
                    file=sys.stderr,
                )
            except Exception as _mcp_exc:
                print(f"Warning: --mcp: unexpected error: {_mcp_exc}", file=sys.stderr)

        else:
            print(
                f"Warning: --mcp: unsupported kg.provider '{_kg_provider}'. "
                "Supported providers: potpie, cgc, graphify",
                file=sys.stderr,
            )

    agent, deps = create_cli_agent(**agent_kwargs)

    import secrets
    session_id = secrets.token_hex(6)
    try:
        from apps.cli.config import get_sessions_dir
        from apps.cli.logfire_tracer import notify_session_start
        notify_session_start(session_id, get_sessions_dir() / session_id)
    except Exception:
        pass

    try:
        run_kwargs: dict[str, Any] = {
            "usage_limits": DEFAULT_USAGE_LIMITS,
        }
        if max_turns is not None:
            run_kwargs["max_turns"] = max_turns

        if verbose:
            run_coro = _run_verbose(agent, task, deps, run_kwargs)
        else:
            run_coro = agent.run(task, deps=deps, **run_kwargs)

        if timeout is not None:
            import asyncio

            try:
                result = await asyncio.wait_for(run_coro, timeout=timeout)
            except asyncio.TimeoutError:
                _print_error("Timed out", output_json)
                return 1
        else:
            result = await run_coro

        if output_json:
            output = _build_json_output(result.output, result.usage())
            print(json.dumps(output, indent=2, default=str))
        else:
            print(result.output)

        return 0
    finally:
        # Stop Docker container if sandbox backend was used
        if hasattr(deps.backend, "stop"):
            deps.backend.stop()
        try:
            from apps.cli.logfire_tracer import end_session_span
            end_session_span(session_id)
        except Exception:
            pass


async def _run_verbose(  # noqa: C901
    agent: Any, task: str, deps: Any, run_kwargs: dict[str, Any]
) -> Any:
    """Run agent with verbose progress on stderr."""
    import time as _time

    from pydantic_ai import Agent
    from pydantic_ai._agent_graph import End, UserPromptNode
    from pydantic_ai.messages import (
        FinalResultEvent,
        FunctionToolCallEvent,
        FunctionToolResultEvent,
        PartDeltaEvent,
        TextPartDelta,
        ThinkingPartDelta,
    )

    _log = lambda msg: print(msg, file=sys.stderr, flush=True)  # noqa: E731
    start = _time.monotonic()

    async with agent.iter(task, deps=deps, **run_kwargs) as run:
        async for node in run:
            elapsed = _time.monotonic() - start

            if isinstance(node, UserPromptNode):
                continue

            elif Agent.is_model_request_node(node):
                _log(f"[{elapsed:6.1f}s] model request...")
                async with node.stream(run.ctx) as stream:
                    thinking_chars = 0
                    text_chars = 0
                    async for event in stream:
                        if isinstance(event, PartDeltaEvent):
                            if isinstance(event.delta, ThinkingPartDelta):
                                thinking_chars += len(event.delta.content_delta or "")
                            elif isinstance(event.delta, TextPartDelta):
                                text_chars += len(event.delta.content_delta or "")
                        elif isinstance(event, FinalResultEvent):
                            break
                    if thinking_chars:
                        t = _time.monotonic() - start
                        _log(f"[{t:6.1f}s]   thinking: {thinking_chars} chars")
                    if text_chars:
                        _log(f"[{_time.monotonic() - start:6.1f}s]   text: {text_chars} chars")

            elif Agent.is_call_tools_node(node):
                async with node.stream(run.ctx) as handle:
                    async for event in handle:
                        e = _time.monotonic() - start
                        if isinstance(event, FunctionToolCallEvent):
                            name = event.part.tool_name
                            args_preview = str(event.part.args)[:80]
                            _log(f"[{e:6.1f}s] tool: {name}({args_preview})")
                        elif isinstance(event, FunctionToolResultEvent):
                            name = getattr(event.result, "tool_name", "?")
                            content = str(event.result.content)
                            _log(f"[{e:6.1f}s]   -> {name}: {content[:120]}")

            elif isinstance(node, End):
                pass

    assert run.result is not None
    total = _time.monotonic() - start
    usage = run.result.usage()
    _log(
        f"[{total:6.1f}s] done — "
        f"in:{usage.request_tokens} out:{usage.response_tokens} reqs:{usage.requests}"
    )
    return run.result


def _build_json_output(output: str, usage: Usage) -> dict[str, Any]:
    """Build a JSON-serializable output dict."""
    return {
        "output": output,
        "usage": {
            "total_tokens": usage.total_tokens,
            "request_tokens": usage.request_tokens,
            "response_tokens": usage.response_tokens,
            "requests": usage.requests,
        },
    }


def _print_error(message: str, output_json: bool) -> None:
    """Print an error message to stderr (or as JSON)."""
    if output_json:
        print(json.dumps({"error": message}), file=sys.stderr)
    else:
        print(f"Error: {message}", file=sys.stderr)

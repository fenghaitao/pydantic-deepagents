"""CLI entry point for pydantic-deep.

Usage:
    pydantic-deep                           # Launch TUI (default)
    pydantic-deep tui [-m model] [-w dir]   # Launch TUI
    pydantic-deep run "task description"    # Headless non-interactive run (potpie)
    pydantic-deep run-upstream "task"       # Headless non-interactive run (upstream)
    pydantic-deep chat [-m model] [-w dir]  # Interactive chat
    pydantic-deep init                      # Initialize project
    pydantic-deep config show               # Show configuration
    pydantic-deep skills list               # List available skills
    pydantic-deep threads list              # List saved threads
    pydantic-deep projects delete <id>      # Delete a code graph project
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import fields
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text


def _configure_litellm_transport_early() -> None:
    """Prefer httpx over aiohttp for LiteLLM (avoids aiohttp unclosed-session warnings
    when the CLI shares one process with in-process Potpie tools).

    Set ``LITELLM_USE_AIOHTTP=1`` to force aiohttp (LiteLLM default transport).
    """
    if os.getenv("LITELLM_USE_AIOHTTP", "").lower() in ("1", "true", "yes"):
        return
    try:
        import litellm

        litellm.disable_aiohttp_transport = True
    except Exception:
        pass


_configure_litellm_transport_early()

app = typer.Typer(
    name="pydantic-deep",
    help="Deep Agent CLI — AI coding assistant powered by pydantic-ai.",
    invoke_without_command=True,
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    if value:
        from pydantic_deep import __version__

        typer.echo(f"pydantic-deep v{__version__}")
        raise typer.Exit()


def _setup_phoenix(endpoint: str) -> None:
    """Configure OpenTelemetry tracing to send spans to an Arize Phoenix server."""
    try:
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        host = parsed.hostname or "localhost"
        port = parsed.port or 80
        try:
            with socket.create_connection((host, port), timeout=3):
                pass
        except OSError:
            print(
                f"Phoenix server not reachable at {endpoint}. "
                "Start it with: PHOENIX_PORT=<port> phoenix serve",
                file=sys.stderr,
            )
            raise SystemExit(1)

        # Verify it's actually a Phoenix server, not some other app on that port
        import urllib.request
        import urllib.error
        healthz_url = endpoint.rstrip("/") + "/healthz"
        try:
            with urllib.request.urlopen(healthz_url, timeout=3) as resp:
                if resp.status != 200:
                    raise ValueError(f"status {resp.status}")
        except Exception as e:
            print(
                f"Port {port} is in use but does not appear to be a Phoenix server "
                f"({healthz_url} failed: {e}). "
                "Start Phoenix with: PHOENIX_PORT=<port> phoenix serve",
                file=sys.stderr,
            )
            raise SystemExit(1)

        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from pydantic_ai.agent import Agent, InstrumentationSettings

        otlp_endpoint = endpoint.rstrip("/") + "/v1/traces"
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        resource = Resource(attributes={"service.name": "pydantic-deep"})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Pass provider explicitly so pydantic-ai uses it; include_content=True
        # ensures user prompts and completions are captured as span attributes.
        Agent.instrument_all(InstrumentationSettings(
            tracer_provider=provider,
            include_content=True,
        ))
    except ImportError as e:
        print(
            f"Phoenix tracing dependencies not installed ({e}). "
            "Run: pip install opentelemetry-exporter-otlp-proto-http",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


def _setup_logfire() -> None:
    """Configure Logfire tracing for all pydantic-ai agents.

    When LOGFIRE_TOKEN is set, spans are sent to logfire.pydantic.dev.
    Without a token, spans are written locally to .traces/<session_id>.jsonl.
    """
    try:
        import logfire
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        from apps.cli.logfire_tracer import SessionFileExporter
        import apps.cli.logfire_tracer as _tracer

        token = os.environ.get("LOGFIRE_TOKEN")
        kwargs: dict = {"token": token, "send_to_logfire": "if-token-present"}

        if not token:
            kwargs["additional_span_processors"] = [
                SimpleSpanProcessor(SessionFileExporter())
            ]
            kwargs["console"] = False

        logfire.configure(**kwargs)
        logfire.instrument_pydantic_ai()
        _tracer._logfire_enabled = True

        log_level_str = os.environ.get("PYDANTIC_DEEP_LOG_LEVEL", "").upper()
        if log_level_str:
            import logging as _logging
            _level = getattr(_logging, log_level_str, None)
            if _level is not None:
                _logging.getLogger("logfire").setLevel(_level)
                _logging.getLogger("opentelemetry").setLevel(_level)
    except ImportError:
        print(
            "Logfire not installed. Run: pip install pydantic-deep[logfire]",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


@app.callback(invoke_without_command=True)
def _main_callback(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = None,
    logfire_enabled: Annotated[
        bool | None,
        typer.Option("--logfire/--no-logfire", help="Enable Logfire tracing (overrides PYDANTIC_DEEP_LOGFIRE env var)"),
    ] = None,
    phoenix_enabled: Annotated[
        bool,
        typer.Option("--phoenix/--no-phoenix", help="Send traces to Arize Phoenix (reads PHOENIX_PORT from .env, defaults to 6006)"),
    ] = False,
) -> None:
    """Deep Agent CLI — AI coding assistant powered by pydantic-ai."""
    try:
        from dotenv import load_dotenv

        load_dotenv(Path.cwd() / "code-graph-providers" / "potpie" / ".env", override=False)
        load_dotenv(Path.home() / ".pydantic-deep" / ".env", override=False)
        load_dotenv(Path.cwd() / ".pydantic-deep" / ".env", override=True)
        load_dotenv()
    except ImportError:  # pragma: no cover
        pass

    if logfire_enabled is None:
        # Flag not explicitly passed — fall back to config/env var.
        from apps.cli.config import load_config

        config = load_config()
        logfire_enabled = config.logfire
    # If --logfire or --no-logfire was explicitly passed it takes full precedence
    # over the PYDANTIC_DEEP_LOGFIRE env var.

    if logfire_enabled:
        _setup_logfire()

    if phoenix_enabled:
        phoenix_port = os.environ.get("PHOENIX_PORT", "6006")
        _setup_phoenix(f"http://localhost:{phoenix_port}")

    # Non-blocking update notification (uses 24-hour file cache)
    from apps.cli.update import check_for_update
    _upd = check_for_update()
    if _upd:
        Console().print(
            f"[yellow]Update available:[/yellow] "
            f"v{_upd.current} → [bold]v{_upd.latest}[/bold]  "
            f"Run: [cyan]pydantic-deep update[/cyan]"
        )

    # Default: launch TUI when no subcommand is given
    if ctx.invoked_subcommand is None:
        from apps.cli.init import ensure_initialized
        from apps.cli.tui import run_tui

        ensure_initialized()
        run_tui(working_dir=os.getcwd())


@app.command()
def tui(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (default: from config)"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option("--working-dir", "-w", help="Working directory"),
    ] = None,
    sandbox: Annotated[
        str | None,
        typer.Option("--sandbox", "-s", help="Sandbox backend: local or docker (from config)"),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help=(
                "Named Docker workspace shared across threads. "
                "Packages and state persist between sessions. "
                "Implies --sandbox docker."
            ),
        ),
    ] = None,
) -> None:
    """Launch the Textual-based TUI (rich interactive interface)."""
    from apps.cli.init import ensure_initialized
    from apps.cli.tui import run_tui

    # --workspace implies --sandbox docker
    if workspace and not sandbox:
        sandbox = "docker"

    ensure_initialized()
    run_tui(
        model=model,
        working_dir=working_dir or os.getcwd(),
        sandbox=sandbox,
        workspace=workspace,
    )


@app.command()
def run(
    task: Annotated[
        str | None,
        typer.Argument(help="Task description (or use --task-file)"),
    ] = None,
    task_file: Annotated[
        Path | None,
        typer.Option("--task-file", "-f", help="Read task from file"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option("--working-dir", "-w", help="Working directory"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (default: from config)"),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON"),
    ] = False,
    max_turns: Annotated[
        int | None,
        typer.Option("--max-turns", help="Maximum number of agent turns"),
    ] = None,
    timeout: Annotated[
        int | None,
        typer.Option("--timeout", help="Timeout in seconds"),
    ] = None,
    # Feature flags — None means "use config.toml default" (same as TUI)
    web_search: Annotated[
        bool | None,
        typer.Option("--web-search/--no-web-search", help="Enable web search (from config)"),
    ] = None,
    web_fetch: Annotated[
        bool | None,
        typer.Option("--web-fetch/--no-web-fetch", help="Enable web fetch (default: from config)"),
    ] = None,
    thinking: Annotated[
        str | None,
        typer.Option("--thinking", help="Thinking effort: minimal/low/medium/high/xhigh or false"),
    ] = None,
    include_todo: Annotated[
        bool | None,
        typer.Option("--todo/--no-todo", help="Enable task planning (default: from config)"),
    ] = None,
    include_subagents: Annotated[
        bool | None,
        typer.Option(
            "--subagents/--no-subagents", help="Enable subagent delegation (default: from config)"
        ),
    ] = None,
    include_skills: Annotated[
        bool | None,
        typer.Option("--skills/--no-skills", help="Enable skills (default: from config)"),
    ] = None,
    include_plan: Annotated[
        bool | None,
        typer.Option("--plan/--no-plan", help="Enable plan mode (default: from config)"),
    ] = None,
    include_memory: Annotated[
        bool | None,
        typer.Option("--memory/--no-memory", help="Enable persistent memory (from config)"),
    ] = None,
    include_teams: Annotated[
        bool | None,
        typer.Option("--teams/--no-teams", help="Enable agent teams (from config)"),
    ] = None,
    context_discovery: Annotated[
        bool | None,
        typer.Option("--context/--no-context", help="Auto-discover AGENTS.md (from config)"),
    ] = None,
    temperature: Annotated[
        float | None,
        typer.Option("--temperature", help="Sampling temperature (default: 0.0)"),
    ] = None,
    sandbox: Annotated[
        str | None,
        typer.Option("--sandbox", "-s", help="Sandbox backend: local or docker (from config)"),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help=(
                "Named Docker workspace shared across threads. "
                "Packages and state persist between sessions. "
                "Implies --sandbox docker."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Stream progress to stderr"),
    ] = False,
    include_browser: Annotated[
        bool | None,
        typer.Option(
            "--browser/--no-browser",
            help="Enable Playwright browser automation (requires pydantic-deep[browser])",
        ),
    ] = None,
    browser_headless: Annotated[
        bool | None,
        typer.Option(
            "--browser-headless/--browser-headed",
            help="Browser window mode: headless (hidden) or headed (visible, default)",
        ),
    ] = None,
) -> None:
    """Run a task non-interactively (headless mode).

    Executes a single task and prints the result to stdout.
    Designed for benchmarks, CI/CD pipelines, and scripted automation.

    All feature flags default to the same values as the TUI (from
    .pydantic-deep/config.toml). Use --no-web-search, --no-thinking,
    etc. to override specific features.

    Examples:
        pydantic-deep run "Fix the failing test in test_auth.py"
        pydantic-deep run --task-file task.md --json
        pydantic-deep run "Refactor utils.py" --max-turns 50 --timeout 300
        pydantic-deep run "Research X" --web-search --web-fetch
        pydantic-deep run "Fix bug" --no-web-search --no-web-fetch --thinking false
        pydantic-deep run "Analyze data" --sandbox docker
        pydantic-deep run "Train model" --workspace ml-env
    """
    from apps.cli.run import execute_headless

    # --workspace implies --sandbox docker
    if workspace and not sandbox:
        sandbox = "docker"

    if task is None and task_file is None:
        typer.echo("Error: provide a task argument or --task-file", err=True)
        raise typer.Exit(1)

    if task_file is not None:
        if not task_file.exists():
            typer.echo(f"Error: task file not found: {task_file}", err=True)
            raise typer.Exit(1)
        task_text = task_file.read_text().strip()
    else:
        assert task is not None
        task_text = task

    if not task_text:
        typer.echo("Error: task is empty", err=True)
        raise typer.Exit(1)

    import asyncio

    result = asyncio.run(
        execute_headless(
            task=task_text,
            working_dir=working_dir or os.getcwd(),
            model=model,
            output_json=output_json,
            max_turns=max_turns,
            timeout=timeout,
            web_search=web_search,
            web_fetch=web_fetch,
            thinking=thinking,
            include_todo=include_todo,
            include_subagents=include_subagents,
            include_skills=include_skills,
            include_plan=include_plan,
            include_memory=include_memory,
            include_teams=include_teams,
            context_discovery=context_discovery,
            temperature=temperature,
            sandbox=sandbox,
            workspace=workspace,
            verbose=verbose,
            include_browser=include_browser,
            browser_headless=browser_headless,
        )
    )
    raise typer.Exit(result)


def _build_model_settings(
    model_settings_json: str | None,
    temperature: float | None,
    reasoning_effort: str | None,
    thinking: bool,
    thinking_budget: int | None,
) -> dict[str, Any] | None:
    """Build model settings dict from CLI flags."""
    settings: dict[str, Any] = {}
    if model_settings_json:
        settings = json.loads(model_settings_json)
    if temperature is not None:
        settings["temperature"] = temperature
    if reasoning_effort:
        settings["openai_reasoning_effort"] = reasoning_effort
    if thinking:
        if thinking_budget:
            settings["anthropic_thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        else:
            settings["anthropic_thinking"] = {"type": "adaptive"}
    elif thinking_budget:
        settings["anthropic_thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    return settings if settings else None


@app.command()
def init(
    directory: Annotated[
        str | None,
        typer.Option("--dir", "-d", help="Project directory (default: CWD)"),
    ] = None,
) -> None:
    """Initialize .pydantic-deep/ project directory with scaffolding."""
    from apps.cli.init import init_project

    root = Path(directory) if directory else Path.cwd()
    init_project(root)


@app.command()
def tui(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (default: from config)"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option("--working-dir", "-w", help="Working directory"),
    ] = None,
    sandbox: Annotated[
        str | None,
        typer.Option("--sandbox", "-s", help="Sandbox backend: local or docker (from config)"),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help=(
                "Named Docker workspace shared across threads. "
                "Packages and state persist between sessions. "
                "Implies --sandbox docker."
            ),
        ),
    ] = None,
) -> None:
    """Launch the Textual-based TUI (rich interactive interface)."""
    from apps.cli.init import ensure_initialized
    from apps.cli.tui import run_tui

    # --workspace implies --sandbox docker
    if workspace and not sandbox:
        sandbox = "docker"

    ensure_initialized()
    run_tui(
        model=model,
        working_dir=working_dir or os.getcwd(),
        sandbox=sandbox,
        workspace=workspace,
    )


@app.command()
def run(
    prompt: Annotated[str, typer.Argument(help="Task to execute")],
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (default: from config)"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option("--working-dir", "-w", help="Working directory"),
    ] = None,
    shell_allow_list: Annotated[
        list[str] | None,
        typer.Option("--shell-allow-list", help="Allowed shell commands"),
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress diagnostics")] = False,
    no_stream: Annotated[
        bool, typer.Option("--no-stream", help="Buffer output instead of streaming")
    ] = False,
    sandbox: Annotated[bool, typer.Option("--sandbox", help="Run in Docker sandbox")] = False,
    runtime: Annotated[
        str, typer.Option("--runtime", help="Sandbox runtime (e.g. python-minimal)")
    ] = "python-minimal",
    output_format: Annotated[
        str, typer.Option("--output-format", "-f", help="Output format: text, json, markdown")
    ] = "text",
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable verbose output")] = False,
    temperature: Annotated[
        float | None,
        typer.Option("--temperature", "-t", help="Model temperature (0.0 = deterministic)"),
    ] = None,
    reasoning_effort: Annotated[
        str | None,
        typer.Option("--reasoning-effort", help="Reasoning effort: low, medium, high"),
    ] = None,
    thinking: Annotated[
        bool,
        typer.Option("--thinking/--no-thinking", help="Enable extended thinking (Anthropic)"),
    ] = False,
    thinking_budget: Annotated[
        int | None,
        typer.Option("--thinking-budget", help="Thinking budget in tokens (Anthropic)"),
    ] = None,
    model_settings_json: Annotated[
        str | None,
        typer.Option("--model-settings", help="Model settings as JSON"),
    ] = None,
    lean: Annotated[
        bool,
        typer.Option("--lean", help="Use minimal system prompt (less noise for benchmarks)"),
    ] = False,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", "-p", help="Potpie project ID (overrides config)"),
    ] = None,
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="Potpie user ID"),
    ] = "defaultuser",
) -> None:
    """Run a task non-interactively (benchmark mode)."""
    from apps.cli.config import load_config
    from apps.cli.init import ensure_initialized
    from apps.cli.non_interactive import run_non_interactive

    ensure_initialized()

    config = load_config()
    effective_project_id = project_id or config.kg.project_id

    settings = _build_model_settings(
        model_settings_json, temperature, reasoning_effort, thinking, thinking_budget
    )

    async def _run_and_cleanup() -> int:
        try:
            return await run_non_interactive(
                message=prompt,
                model=model,
                working_dir=working_dir,
                shell_allow_list=shell_allow_list,
                quiet=quiet,
                stream=not no_stream,
                sandbox=sandbox,
                runtime=runtime,
                output_format=output_format,
                verbose=verbose,
                model_settings=settings,
                lean=lean,
                project_id=effective_project_id,
                user_id=user_id,
            )
        finally:
            # Close LiteLLM's cached aiohttp/httpx clients before the event loop stops
            # (avoids "Unclosed client session / connector" from asyncio).
            try:
                from litellm import close_litellm_async_clients

                await close_litellm_async_clients()
            except Exception:
                pass
            await asyncio.sleep(0)

    exit_code = asyncio.run(_run_and_cleanup())
    raise typer.Exit(exit_code)


@app.command("run-upstream")
def run_upstream(
    task: Annotated[
        str | None,
        typer.Argument(help="Task description (or use --task-file)"),
    ] = None,
    task_file: Annotated[
        Path | None,
        typer.Option("--task-file", "-f", help="Read task from file"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option("--working-dir", "-w", help="Working directory"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (default: from config)"),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON"),
    ] = False,
    max_turns: Annotated[
        int | None,
        typer.Option("--max-turns", help="Maximum number of agent turns"),
    ] = None,
    timeout: Annotated[
        int | None,
        typer.Option("--timeout", help="Timeout in seconds"),
    ] = None,
    web_search: Annotated[
        bool | None,
        typer.Option("--web-search/--no-web-search", help="Enable web search (from config)"),
    ] = None,
    web_fetch: Annotated[
        bool | None,
        typer.Option("--web-fetch/--no-web-fetch", help="Enable web fetch (from config)"),
    ] = None,
    thinking: Annotated[
        str | None,
        typer.Option("--thinking", help="Thinking effort: minimal/low/medium/high/xhigh or false"),
    ] = None,
    include_todo: Annotated[
        bool | None,
        typer.Option("--todo/--no-todo", help="Enable task planning (default: from config)"),
    ] = None,
    include_subagents: Annotated[
        bool | None,
        typer.Option("--subagents/--no-subagents", help="Enable subagent delegation (default: from config)"),
    ] = None,
    include_skills: Annotated[
        bool | None,
        typer.Option("--skills/--no-skills", help="Enable skills (default: from config)"),
    ] = None,
    include_plan: Annotated[
        bool | None,
        typer.Option("--plan/--no-plan", help="Enable plan mode (default: from config)"),
    ] = None,
    include_memory: Annotated[
        bool | None,
        typer.Option("--memory/--no-memory", help="Enable persistent memory (from config)"),
    ] = None,
    include_teams: Annotated[
        bool | None,
        typer.Option("--teams/--no-teams", help="Enable agent teams (from config)"),
    ] = None,
    context_discovery: Annotated[
        bool | None,
        typer.Option("--context/--no-context", help="Auto-discover AGENTS.md (from config)"),
    ] = None,
    temperature: Annotated[
        float | None,
        typer.Option("--temperature", help="Sampling temperature (default: 0.0)"),
    ] = None,
    sandbox: Annotated[
        str | None,
        typer.Option("--sandbox", "-s", help="Sandbox backend: local or docker (from config)"),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option("--workspace", help="Named Docker workspace. Implies --sandbox docker."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Stream progress to stderr"),
    ] = False,
    include_browser: Annotated[
        bool | None,
        typer.Option("--browser/--no-browser", help="Enable Playwright browser automation"),
    ] = None,
    browser_headless: Annotated[
        bool | None,
        typer.Option("--browser-headless/--browser-headed", help="Browser window mode"),
    ] = None,
) -> None:
    """Run a task non-interactively (upstream headless mode).

    Uses execute_headless from run.py — supports --task-file, --max-turns,
    --timeout, feature flags, and sandbox options.

    Examples:
        pydantic-deep run-upstream "Fix the failing test"
        pydantic-deep run-upstream --task-file task.md --json
        pydantic-deep run-upstream "Refactor utils.py" --max-turns 50 --timeout 300
    """
    from apps.cli.run import execute_headless

    if workspace and not sandbox:
        sandbox = "docker"

    if task is None and task_file is None:
        typer.echo("Error: provide a task argument or --task-file", err=True)
        raise typer.Exit(1)

    if task_file is not None:
        if not task_file.exists():
            typer.echo(f"Error: task file not found: {task_file}", err=True)
            raise typer.Exit(1)
        task_text = task_file.read_text().strip()
    else:
        assert task is not None
        task_text = task

    if not task_text:
        typer.echo("Error: task is empty", err=True)
        raise typer.Exit(1)

    result = asyncio.run(
        execute_headless(
            task=task_text,
            working_dir=working_dir or os.getcwd(),
            model=model,
            output_json=output_json,
            max_turns=max_turns,
            timeout=timeout,
            web_search=web_search,
            web_fetch=web_fetch,
            thinking=thinking,
            include_todo=include_todo,
            include_subagents=include_subagents,
            include_skills=include_skills,
            include_plan=include_plan,
            include_memory=include_memory,
            include_teams=include_teams,
            context_discovery=context_discovery,
            temperature=temperature,
            sandbox=sandbox,
            workspace=workspace,
            verbose=verbose,
            include_browser=include_browser,
            browser_headless=browser_headless,
        )
    )
    raise typer.Exit(result)


@app.command()
def chat(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (default: from config)"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option("--working-dir", "-w", help="Working directory"),
    ] = None,
    sandbox: Annotated[bool, typer.Option("--sandbox", help="Run in Docker sandbox")] = False,
    runtime: Annotated[
        str, typer.Option("--runtime", help="Sandbox runtime (e.g. python-minimal)")
    ] = "python-minimal",
    resume: Annotated[
        str | None,
        typer.Option("--resume", "-r", help="Resume a session by ID"),
    ] = None,
    sessions: Annotated[
        bool,
        typer.Option("--sessions", "-s", help="Pick a previous session to resume"),
    ] = False,
    auto_approve: Annotated[
        bool,
        typer.Option("--auto-approve", help="Auto-approve all tool calls (skip HITL)"),
    ] = False,
    temperature: Annotated[
        float | None,
        typer.Option("--temperature", "-t", help="Model temperature (0.0 = deterministic)"),
    ] = None,
    reasoning_effort: Annotated[
        str | None,
        typer.Option("--reasoning-effort", help="Reasoning effort: low, medium, high"),
    ] = None,
    thinking: Annotated[
        bool,
        typer.Option("--thinking/--no-thinking", help="Enable extended thinking (Anthropic)"),
    ] = False,
    thinking_budget: Annotated[
        int | None,
        typer.Option("--thinking-budget", help="Thinking budget in tokens (Anthropic)"),
    ] = None,
    model_settings_json: Annotated[
        str | None,
        typer.Option("--model-settings", help="Model settings as JSON"),
    ] = None,
    fork: Annotated[
        bool,
        typer.Option("--fork", help="Fork from a resumed session (new session, same history)"),
    ] = False,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", "-p", help="Potpie project ID (overrides config)"),
    ] = None,
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="Potpie user ID"),
    ] = "defaultuser",
    lean: Annotated[
        bool,
        typer.Option(
            "--lean",
            help="Minimal system prompt — disables skills, subagents, memory (reduces token usage)",
        ),
    ] = False,
) -> None:
    """Start an interactive chat session."""
    from apps.cli.config import load_config
    from apps.cli.init import ensure_initialized
    from apps.cli.interactive import run_interactive

    ensure_initialized()

    settings = _build_model_settings(
        model_settings_json, temperature, reasoning_effort, thinking, thinking_budget
    )

    # --sessions flag triggers interactive picker (resume="")
    effective_resume = "" if sessions else resume

    config = load_config()
    effective_project_id = project_id or config.kg.project_id

    asyncio.run(
        run_interactive(
            model=model,
            working_dir=working_dir,
            sandbox=sandbox,
            runtime=runtime,
            resume=effective_resume,
            auto_approve=auto_approve,
            model_settings=settings,
            fork_session=fork,
            project_id=effective_project_id,
            user_id=user_id,
            lean=lean,
        )
    )


# ── Config subcommands ──────────────────────────────────────────

config_app = typer.Typer(name="config", help="Manage configuration.", no_args_is_help=True)
app.add_typer(config_app)


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    from apps.cli.config import CliConfig, load_config

    config = load_config()
    console = Console()
    table = Table(show_header=True, header_style="bold", show_lines=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    for f in fields(CliConfig):
        value = getattr(config, f.name)
        if isinstance(value, bool):
            style = "green" if value else "red"
            table.add_row(f.name, Text(str(value), style=style))
        elif value is None:
            table.add_row(f.name, Text("None", style="dim"))
        else:
            table.add_row(f.name, str(value))

    console.print(table)


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Config key to set")],
    value: Annotated[str, typer.Argument(help="Value to set")],
) -> None:
    """Set a configuration value."""
    from apps.cli.config import get_config_path, set_config_value

    try:
        set_config_value(get_config_path(), key, value)
    except KeyError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Set {key} = {value}")


# ── Sandbox subcommands ────────────────────────────────────────

sandbox_app = typer.Typer(
    name="sandbox", help="Manage Docker sandbox workspaces.", no_args_is_help=True
)
app.add_typer(sandbox_app)


def _get_project_container_prefix() -> str:
    """Return the Docker container name prefix for the current project."""
    import hashlib

    dir_hash = hashlib.md5(str(Path.cwd().resolve()).encode()).hexdigest()[:8]
    return f"pydantic-deep-{dir_hash}-"


@sandbox_app.command("list")
def sandbox_list() -> None:
    """List Docker sandbox workspaces for this project."""
    try:
        import docker
    except ImportError:
        typer.echo(
            "Docker package not installed. Install with: pip install pydantic-ai-backend[docker]",
            err=True,
        )
        raise typer.Exit(1) from None

    prefix = _get_project_container_prefix()
    client = docker.from_env()

    containers = [c for c in client.containers.list(all=True) if c.name.startswith(prefix)]

    if not containers:
        typer.echo("No sandbox workspaces found for this project.")
        return

    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Workspace", style="cyan")
    table.add_column("Status")
    table.add_column("Image", style="dim")
    table.add_column("Created", style="dim")

    for c in sorted(containers, key=lambda x: x.name):
        # Strip project prefix to show short workspace name
        workspace_name = c.name[len(prefix) :]
        status_style = "green" if c.status == "running" else "yellow"
        table.add_row(
            workspace_name,
            Text(c.status, style=status_style),
            c.image.tags[0] if c.image.tags else str(c.image.short_id),
            c.attrs.get("Created", "")[:19],
        )

    console.print(table)
    typer.echo(f"\nProject: {Path.cwd()}")
    typer.echo(f"Prefix:  {prefix}*")


@sandbox_app.command("stop")
def sandbox_stop(
    name: Annotated[
        str | None,
        typer.Argument(help="Workspace name to stop (or 'all')"),
    ] = None,
    remove: Annotated[
        bool,
        typer.Option("--rm", help="Remove workspace container after stopping"),
    ] = False,
) -> None:
    """Stop sandbox workspaces for this project.

    Examples:
        pydantic-deep sandbox stop ml-env     # Stop one workspace
        pydantic-deep sandbox stop all        # Stop all for this project
        pydantic-deep sandbox stop all --rm   # Stop and remove all
    """
    try:
        import docker
    except ImportError:
        typer.echo(
            "Docker package not installed. Install with: pip install pydantic-ai-backend[docker]",
            err=True,
        )
        raise typer.Exit(1) from None

    if name is None:
        typer.echo("Provide a workspace name or 'all'.", err=True)
        raise typer.Exit(1)

    prefix = _get_project_container_prefix()
    client = docker.from_env()

    if name == "all":
        targets = [c for c in client.containers.list(all=True) if c.name.startswith(prefix)]
    else:
        full_name = f"{prefix}{name}"
        try:
            targets = [client.containers.get(full_name)]
        except docker.errors.NotFound:
            typer.echo(f"Workspace '{name}' not found.", err=True)
            raise typer.Exit(1) from None

    for c in targets:
        short = c.name[len(prefix) :]
        if c.status == "running":
            c.stop()
            typer.echo(f"Stopped: {short}")
        if remove:
            c.remove()
            typer.echo(f"Removed: {short}")
        elif c.status != "running":
            typer.echo(f"Already stopped: {short}")

    if not targets:
        typer.echo("No containers to stop.")


# ── Skills subcommands ──────────────────────────────────────────

skills_app = typer.Typer(name="skills", help="Manage skills.", no_args_is_help=True)
app.add_typer(skills_app)


def _get_builtin_skills_dir() -> Path:
    return Path(__file__).parent / "skills"


def _discover_all_skills(user_dir: str | None = None) -> list[dict[str, str]]:
    """Discover all skills from all sources."""
    seen_names: set[str] = set()
    skills: list[dict[str, str]] = []

    def _scan_dir(directory: Path, source: str) -> None:
        if not directory.is_dir():
            return
        for skill_dir in sorted(directory.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if skill_file.is_file():
                name, desc = _parse_skill_frontmatter(skill_file)
                if name in seen_names:
                    skills[:] = [s for s in skills if s["name"] != name]
                seen_names.add(name)
                skills.append(
                    {"name": name, "description": desc, "path": str(skill_file), "source": source}
                )

    _scan_dir(_get_builtin_skills_dir(), "built-in")
    _scan_dir(Path.home() / ".pydantic-deep" / "skills", "user")
    _scan_dir(Path.cwd() / ".pydantic-deep" / "skills", "project")
    if user_dir:
        _scan_dir(Path(user_dir), "custom")
    return skills


def _parse_skill_frontmatter(path: Path) -> tuple[str, str]:
    content = path.read_text()
    name = path.parent.name
    description = ""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                line = line.strip()
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"').strip("'")
    return name, description


@skills_app.command("list")
def skills_list(directory: Annotated[str | None, typer.Option("--dir", "-d")] = None) -> None:
    """List available skills (built-in + user)."""
    skills = _discover_all_skills(directory)
    if not skills:
        typer.echo("No skills found.")
        return
    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Source", style="dim")
    for s in skills:
        table.add_row(s["name"], s["description"], s["source"])
    console.print(table)


@skills_app.command("info")
def skills_info(name: Annotated[str, typer.Argument(help="Skill name")]) -> None:
    """Show details for a specific skill."""
    from rich.markdown import Markdown
    from rich.panel import Panel

    skills = _discover_all_skills()
    for s in skills:
        if s["name"] == name:
            console = Console()
            content = Path(s["path"]).read_text()
            body_text = content
            if content.startswith("---"):
                fm_parts = content.split("---", 2)
                if len(fm_parts) >= 3:
                    body_text = fm_parts[2].strip()
            header = (
                f"[dim]Description:[/dim] {s['description']}\n"
                f"[dim]Source:[/dim]      {s['source']}\n"
                f"[dim]Path:[/dim]        {s['path']}"
            )
            console.print()
            console.print(
                Panel(header, title=f"[bold cyan]{s['name']}[/bold cyan]", padding=(0, 1))
            )
            if body_text:
                console.print()
                console.print(Markdown(body_text))
            return
    typer.echo(f"Skill '{name}' not found.", err=True)
    raise typer.Exit(1)


@skills_app.command("create")
def skills_create(
    name: Annotated[str, typer.Argument(help="Skill name")],
    directory: Annotated[str, typer.Option("--dir", "-d")] = "./skills",
) -> None:
    """Create a new skill scaffold."""
    skill_dir = Path(directory) / name
    skill_file = skill_dir / "SKILL.md"
    if skill_file.exists():
        typer.echo(f"Skill already exists at {skill_file}", err=True)
        raise typer.Exit(1)
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        f"---\nname: {name}\n"
        f'description: ""\n'
        f"---\n\n# {name}\n\n"
        f"Instructions for this skill go here.\n"
    )
    typer.echo(f"Created skill scaffold at {skill_dir}/")


# ── Threads subcommands ─────────────────────────────────────────

threads_app = typer.Typer(name="threads", help="Manage conversation threads.", no_args_is_help=True)
app.add_typer(threads_app)


# ── traces sub-app ────────────────────────────────────────────────────────────

traces_app = typer.Typer(name="traces", help="View session traces.", no_args_is_help=True)
app.add_typer(traces_app)


@traces_app.command("view")
def traces_view(
    session_id: Annotated[str, typer.Argument(help="Session ID (or prefix)")],
    directory: Annotated[
        str | None,
        typer.Option("--dir", "-d", help="Sessions directory"),
    ] = None,
) -> None:
    """Render a session trace as a timeline in the terminal."""
    from apps.cli.config import get_sessions_dir
    from apps.cli.traces_view import render_traces

    sessions_dir = Path(directory) if directory else get_sessions_dir()

    # Support prefix matching
    match = None
    if sessions_dir.exists():
        for d in sessions_dir.iterdir():
            if d.is_dir() and d.name.startswith(session_id):
                match = d
                break

    if match is None:
        typer.echo(f"Session '{session_id}' not found in {sessions_dir}", err=True)
        raise typer.Exit(1)

    render_traces(match.name, match / "traces.jsonl")


@traces_app.command("upload")
def traces_upload(
    session_id: Annotated[str, typer.Argument(help="Session ID (or prefix)")],
    directory: Annotated[
        str | None,
        typer.Option("--dir", "-d", help="Sessions directory"),
    ] = None,
    phoenix_port: Annotated[
        str | None,
        typer.Option("--phoenix-port", "-p", help="Phoenix server port (default: PHOENIX_PORT env or 6006)"),
    ] = None,
) -> None:
    """Upload a local session trace to the Phoenix tracing server."""
    from apps.cli.config import get_sessions_dir
    from apps.cli.traces_upload import upload_traces

    sessions_dir = Path(directory) if directory else get_sessions_dir()

    match = None
    if sessions_dir.exists():
        for d in sessions_dir.iterdir():
            if d.is_dir() and d.name.startswith(session_id):
                match = d
                break

    if match is None:
        typer.echo(f"Session '{session_id}' not found in {sessions_dir}", err=True)
        raise typer.Exit(1)

    port = phoenix_port or os.environ.get("PHOENIX_PORT", "6006")
    endpoint = f"http://localhost:{port}"

    typer.echo(f"Uploading traces for session {match.name} to {endpoint} ...")
    try:
        count = upload_traces(match / "traces.jsonl", endpoint)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Uploaded {count} span(s). Open Phoenix at {endpoint} to view.")


@threads_app.command("list")
def threads_list(directory: Annotated[str | None, typer.Option("--dir", "-d")] = None) -> None:
    """List saved conversation threads."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    from apps.cli.config import get_sessions_dir

    store_path = Path(directory) if directory else get_sessions_dir()
    if not store_path.exists():
        typer.echo("No threads found.")
        return
    sessions: list[tuple[str, int]] = []
    for session_dir in sorted(store_path.iterdir()):
        if not session_dir.is_dir():
            continue
        mf = session_dir / "messages.json"
        if mf.exists():
            try:
                raw = mf.read_bytes()
                if raw:
                    sessions.append(
                        (session_dir.name, len(ModelMessagesTypeAdapter.validate_json(raw)))
                    )
            except Exception:
                pass
    if not sessions:
        typer.echo("No threads found.")
        return
    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Session ID", style="cyan", width=14)
    table.add_column("Messages", justify="right")
    for sid, mc in sessions:
        table.add_row(sid, str(mc))
    console.print(table)


@threads_app.command("delete")
def threads_delete(
    thread_id: Annotated[str, typer.Argument(help="Thread ID (or prefix)")],
    directory: Annotated[str | None, typer.Option("--dir", "-d")] = None,
) -> None:
    """Delete a conversation thread."""
    import shutil

    from apps.cli.config import get_sessions_dir

    store_path = Path(directory) if directory else get_sessions_dir()
    if not store_path.exists():
        typer.echo("No threads found.", err=True)
        raise typer.Exit(1)
    match_dir = None
    for sd in store_path.iterdir():
        if sd.is_dir() and sd.name.startswith(thread_id):
            match_dir = sd
            break
    if match_dir is None:
        typer.echo(f"Thread '{thread_id}' not found.", err=True)
        raise typer.Exit(1)
    shutil.rmtree(match_dir)
    typer.echo(f"Deleted thread {match_dir.name}")


@threads_app.command("export")
def threads_export(
    thread_id: Annotated[str, typer.Argument(help="Thread ID (or prefix)")],
    directory: Annotated[str | None, typer.Option("--dir", "-d")] = None,
    output_format: Annotated[str, typer.Option("--format", "-f")] = "markdown",
) -> None:
    """Export a conversation thread."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    from apps.cli.config import get_sessions_dir

    store_path = Path(directory) if directory else get_sessions_dir()
    if not store_path.exists():
        typer.echo("No threads found.", err=True)
        raise typer.Exit(1)
    session_dir = None
    for d in store_path.iterdir():
        if d.is_dir() and d.name.startswith(thread_id):
            session_dir = d
            break
    if session_dir is None:
        typer.echo(f"Thread '{thread_id}' not found.", err=True)
        raise typer.Exit(1)
    mf = session_dir / "messages.json"
    if not mf.exists():
        typer.echo("Thread has no history.", err=True)
        raise typer.Exit(1)
    messages = list(ModelMessagesTypeAdapter.validate_json(mf.read_bytes()))
    if output_format == "json":
        typer.echo(
            json.dumps(
                {
                    "id": session_dir.name,
                    "message_count": len(messages),
                    "messages": [str(m) for m in messages],
                },
                indent=2,
                default=str,
            )
        )
    else:
        typer.echo(f"# Thread: {session_dir.name}\n\nMessages: {len(messages)}\n")
        for msg in messages:
            typer.echo(f"---\n{msg}\n")


    asyncio.run(_run())


@app.command()
def update() -> None:
    """Update pydantic-deep to the latest version."""
    from apps.cli.update import run_update

    Console().print("Updating pydantic-deep...")
    raise typer.Exit(run_update())


def main() -> None:
    """Entry point for the CLI."""
    app()


def _make_code_graph_runtime():
    """Return a CodeGraphProvider for the configured provider (potpie or cgc)."""
    from apps.cli.config import load_config
    from pydantic_deep.providers.code_graph import make_provider

    cfg = load_config()
    return make_provider(cfg.kg.provider)


# ── parse sub-app ─────────────────────────────────────────────────────────────

parse_app = typer.Typer(
    name="parse", help="Parse repositories into the code graph.", no_args_is_help=True
)
app.add_typer(parse_app)


@parse_app.command("repo")
def parse_repo(
    path: Annotated[str, typer.Argument(help="Local path to the git repository")],
    branch: Annotated[str, typer.Option("--branch", "-b", help="Branch name")] = "main",
    repo_name: Annotated[
        str | None,
        typer.Option("--repo-name", help="Override repo name (default: directory name)"),
    ] = None,
    commit_id: Annotated[
        str | None,
        typer.Option("--commit", help="Specific commit SHA to parse"),
    ] = None,
    no_wait: Annotated[
        bool,
        typer.Option("--no-wait", help="Return immediately; do not poll for status"),
    ] = False,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API"),
    ] = False,
) -> None:
    """Parse a repository and build its code knowledge graph.

    After parsing, the returned project_id can be set as the default:\n
        pydantic-deep config set kg.project_id <project_id>
    """

    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()
        with console.status(f"[bold blue]Parsing {path} ({branch})…"):
            result = await runtime.parse(
                repo_path=path,
                repo_name=repo_name,
                branch=branch,
                commit_id=commit_id,
            )

        project_id = result.get("project_id", "")
        status = result.get("status", "UNKNOWN")
        message = result.get("message", "")

        console.print(f"[bold]Project ID:[/bold] {project_id}")
        console.print(f"[bold]Status:[/bold]     {status}")
        if message:
            console.print(f"[dim]{message}[/dim]")

        if not no_wait and status not in ("READY", "ERROR") and project_id:
            console.print("[dim]Polling for completion…[/dim]")
            max_polls = 120
            for _ in range(max_polls):
                await asyncio.sleep(5)
                st = await runtime.parsing_status(project_id)
                current = st.get("status", "UNKNOWN")
                console.print(f"  status: {current}")
                if current in ("READY", "ERROR", "DONE"):
                    break
            status = current

        if status == "READY":
            console.print("\n[green]Parsing complete.[/green]")
            console.print(
                "[dim]Set as default: pydantic-deep config set"
                f" kg.project_id {project_id}[/dim]"
            )
        elif status == "ERROR":
            console.print("\n[red]Parsing failed.[/red]")
            raise typer.Exit(1)

    asyncio.run(_run())


@parse_app.command("status")
def parse_status(
    project_id: Annotated[str, typer.Argument(help="Project ID to check")],
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API"),
    ] = False,
) -> None:
    """Check the parsing status of a project."""
    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()
        result = await runtime.parsing_status(project_id)
        status = result.get("status", "UNKNOWN")
        style = "green" if status == "READY" else ("red" if status == "ERROR" else "yellow")
        console.print(f"[bold]Project:[/bold] {project_id}")
        console.print(f"[bold]Status:[/bold]  [{style}]{status}[/{style}]")

    asyncio.run(_run())


# ── projects sub-app ──────────────────────────────────────────────────────────

projects_app = typer.Typer(name="projects", help="Manage parsed projects.", no_args_is_help=True)
app.add_typer(projects_app)


@projects_app.command("list")
def projects_list(
    output_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help="Provider to query: 'potpie', 'cgc', or 'all'. Defaults to configured provider.",
        ),
    ] = None,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API"),
    ] = False,
) -> None:
    """List all indexed projects.

    Use --provider all to list projects from both Potpie and CGC simultaneously.
    """
    console = Console()

    async def _run() -> None:
        from apps.cli.config import load_config
        from pydantic_deep.providers.code_graph import make_provider

        cfg = load_config()
        effective_provider = provider or cfg.kg.provider

        def _render_table(projects: list[dict]) -> None:
            if not projects:
                console.print("[dim]No projects found.[/dim]")
                return
            table = Table(show_header=True, header_style="bold")
            table.add_column("ID", style="cyan")
            table.add_column("Repo")
            table.add_column("Branch")
            table.add_column("Repo Path", style="dim")
            table.add_column("Status")
            for p in projects:
                status = p.get("status", "")
                style = "green" if status == "READY" else ("red" if status == "ERROR" else "yellow")
                table.add_row(
                    p.get("id", ""),
                    p.get("repo_name", p.get("project_name", "")),
                    p.get("branch_name", ""),
                    p.get("repo_path", ""),
                    Text(status, style=style),
                )
            console.print(table)

        if effective_provider == "all":
            all_results: dict[str, list[dict]] = {}
            for p_name in ("potpie", "cgc"):
                try:
                    all_results[p_name] = await make_provider(p_name).list_projects()
                except Exception:
                    all_results[p_name] = []

            if output_json:
                typer.echo(json.dumps(all_results, indent=2, default=str))
                return

            for p_name, projects in all_results.items():
                console.print(f"\n[bold]{p_name.upper()}[/bold]")
                _render_table(projects)
        else:
            projects = await make_provider(effective_provider).list_projects()

            if output_json:
                typer.echo(json.dumps(projects, indent=2, default=str))
                return

            _render_table(projects)

    asyncio.run(_run())


@projects_app.command("delete")
def projects_delete(
    project_id: Annotated[str, typer.Argument(help="Project ID to delete")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API"),
    ] = False,
) -> None:
    """Delete a project and its code graph data."""
    if not force:
        typer.confirm(f"Delete project {project_id}?", abort=True)

    async def _run() -> None:
        runtime = _make_code_graph_runtime()
        result = await runtime.delete_project(project_id)
        typer.echo(f"Deleted: {result.get('deleted', project_id)}")

    asyncio.run(_run())


@projects_app.command("delete-all")
def projects_delete_all(
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API"),
    ] = False,
) -> None:
    """Delete ALL projects for this user."""
    if not force:
        typer.confirm("Delete ALL projects? This cannot be undone.", abort=True)

    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()
        result = await runtime.delete_all_projects()
        console.print(f"[green]Deleted {result.get('deleted', 0)} project(s).[/green]")
        if result.get("errors"):
            for err in result["errors"]:
                console.print(f"[red]Error: {err}[/red]")

    asyncio.run(_run())


# ── cache sub-app ─────────────────────────────────────────────────────────────

cache_app = typer.Typer(name="cache", help="Manage inference cache.", no_args_is_help=True)
app.add_typer(cache_app)


@cache_app.command("stats")
def cache_stats(
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", "-p", help="Show stats for a specific project"),
    ] = None,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API"),
    ] = False,
) -> None:
    """Show inference cache statistics."""
    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()
        stats = await runtime.cache_stats(project_id=project_id)

        table = Table(show_header=False, show_lines=False, box=None)
        table.add_column("Key", style="cyan")
        table.add_column("Value")
        for k, v in stats.items():
            table.add_row(str(k), str(v))
        console.print(table)

    asyncio.run(_run())


@cache_app.command("clean")
def cache_clean(
    all_entries: Annotated[
        bool,
        typer.Option("--all", help="Delete all inference cache rows"),
    ] = False,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", "-p", help="Delete rows for a specific project"),
    ] = None,
    expired: Annotated[
        bool,
        typer.Option("--expired", help="Delete expired rows"),
    ] = False,
    trim: Annotated[
        bool,
        typer.Option("--trim", help="Trim cache to --max-entries"),
    ] = False,
    max_entries: Annotated[
        int,
        typer.Option("--max-entries", help="Max entries to retain when trimming"),
    ] = 100_000,
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API"),
    ] = False,
) -> None:
    """Clean the inference cache.

    Must specify at least one of: --all, --project-id, --expired, --trim.
    """
    if not any([all_entries, project_id, expired, trim]):
        typer.echo(
            "Error: specify at least one of --all, --project-id, --expired, --trim", err=True
        )
        raise typer.Exit(1)

    if not force:
        scope = (
            "ALL entries"
            if all_entries
            else f"project {project_id}"
            if project_id
            else "selected entries"
        )
        typer.confirm(f"Clean cache ({scope})?", abort=True)

    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()
        result = await runtime.cache_clean(
            all=all_entries,
            project_id=project_id,
            expired=expired,
            trim=trim,
            max_entries=max_entries,
        )
        for k, v in result.items():
            console.print(f"[green]{k}: {v} removed[/green]")
        if not result:
            console.print("[dim]Nothing to clean.[/dim]")

    asyncio.run(_run())


# ── agents command ────────────────────────────────────────────────────────────


@app.command("agents")
def agents_list(
    output_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API"),
    ] = False,
) -> None:
    """List available potpie agents."""
    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()
        agents = await runtime.list_agents()

        if output_json:
            typer.echo(json.dumps(agents, indent=2, default=str))
            return

        if not agents:
            console.print("[dim]No agents found.[/dim]")
            return

        table = Table(show_header=True, header_style="bold")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Description")

        for a in agents:
            table.add_row(a.get("id", ""), a.get("name", ""), a.get("description", ""))

        console.print(table)

    asyncio.run(_run())


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

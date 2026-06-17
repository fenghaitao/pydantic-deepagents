"""CLI entry point for pydantic-deep.

Usage:
    pydantic-deep                           # Launch TUI (default)
    pydantic-deep tui [-m model] [-w dir]   # Launch TUI
    pydantic-deep run "task description"    # Headless non-interactive run
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
import uuid

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
        Agent.instrument_all(
            InstrumentationSettings(
                tracer_provider=provider,
                include_content=True,
            )
        )
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
            kwargs["additional_span_processors"] = [SimpleSpanProcessor(SessionFileExporter())]
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


def _setup_vector() -> None:
    """Configure OTLP tracing to Vector (or any OTLP-compatible backend).

    Uses logfire with ``send_to_logfire=False`` so spans are exported only
    via the standard OpenTelemetry OTLP exporter.  The endpoint is resolved
    in priority order:

    1. ``VECTOR_OTLP_ENDPOINT`` environment variable (explicit override).
    2. Potpie Discovery Server — reads the dynamically allocated
       ``tempo_otlp_http`` port for the current user@host session.
    3. Hardcoded default ``http://localhost:4318``.

    Metrics are exported directly to VictoriaMetrics via OTLP HTTP
    (``/opentelemetry/v1/metrics``) using a ``PeriodicExportingMetricReader``.
    """
    try:
        import logfire
    except ImportError:
        import sys

        print(
            "Logfire not installed. Run: pip install pydantic-deep[logfire]",
            file=sys.stderr,
        )
        raise SystemExit(2) from None

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    # Resolve endpoint in priority order:
    # 1. TEMPO_OTLP_LOCAL / VECTOR_OTLP_ENDPOINT — explicit user override only.
    #    NOTE: these are NOT set in the user's shell by observability.sh (it runs
    #    as a subshell), so if they appear in the environment they are intentional.
    #    However, to guard against stale values from a previous session we prefer
    #    the live PortManager value first.
    # 2. PortManager — authoritative live allocation for this machine.
    # 3. Hardcoded fallback (Vector proxy port 4328).
    endpoint = (
        _resolve_vector_otlp_endpoint()
        or os.environ.get("TEMPO_OTLP_LOCAL")
        or os.environ.get("VECTOR_OTLP_ENDPOINT")
        or "http://localhost:4328"
    )
    service_name = os.environ.get("OTEL_SERVICE_NAME", "pydantic-deep")

    # Explicitly build the OTLP exporter — logfire.configure(send_to_logfire=False)
    # does NOT auto-consume OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, so we must wire
    # it ourselves via additional_span_processors.
    # Use SimpleSpanProcessor (synchronous) so spans are sent before the CLI exits;
    # BatchSpanProcessor would lose buffered spans on process exit.
    otlp_exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")

    # Resolve VictoriaMetrics endpoint for OTLP metrics export.
    # VictoriaMetrics accepts OTLP at /opentelemetry/v1/metrics directly.
    metrics_port: str | None = os.environ.get("VICTORIA_METRICS_PORT")
    if not metrics_port:
        try:
            from ports_allocator import PortManager
            from pathlib import Path as _Path

            _pm_port = PortManager().get(
                "obs.victoria_metrics", workspace=str(_Path.cwd().resolve())
            )
            if _pm_port:
                metrics_port = str(_pm_port)
        except Exception:
            pass
    metrics_endpoint = f"http://localhost:{metrics_port or '8428'}/opentelemetry/v1/metrics"

    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create({"service.name": service_name})
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=metrics_endpoint),
        export_interval_millis=5000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    from opentelemetry import metrics as otel_metrics

    otel_metrics.set_meter_provider(meter_provider)
    # Flush pending metrics on process exit — PeriodicExportingMetricReader fires
    # every 5 s, so short-lived CLI runs would otherwise exit before the first
    # export.  shutdown() performs a synchronous final collection + export.
    import atexit

    atexit.register(meter_provider.shutdown)

    logfire.configure(
        send_to_logfire=False,
        service_name=service_name,
        additional_span_processors=[SimpleSpanProcessor(otlp_exporter)],
    )
    logfire.instrument_pydantic_ai()

    # Also forward Python log records to Vector's HTTP JSON ingest so they
    # appear in VictoriaLogs / Grafana alongside the traces.
    _setup_vector_log_handler(service_name)


def _resolve_vector_otlp_endpoint() -> str:
    """Return the Vector OTLP HTTP proxy URL for the current machine.

    Resolution order:
    1. PortManager.get() — reads the ports_allocator session for this machine.
    2. Hardcoded default http://localhost:4328 (Vector proxy port).

    Always returns a localhost URL so corporate proxies don't intercept it.
    """
    from pathlib import Path

    workspace = str(Path.cwd().resolve())

    try:
        from ports_allocator import PortManager

        port = PortManager().get("obs.vector_otlp_http", workspace=workspace)
        if port:
            return f"http://localhost:{port}"
    except Exception:
        pass

    return "http://localhost:4328"


def _setup_vector_log_handler(service_name: str) -> None:
    """Attach a Python logging handler that POSTs JSON log records to Vector.

    Vector listens on VECTOR_INGEST_PORT for HTTP JSON; this forwards all
    root-logger records so they appear in VictoriaLogs / Grafana.
    """
    import json
    import logging
    from pathlib import Path
    from urllib.request import Request, urlopen

    # Resolve Vector ingest URL (always localhost — corporate proxies intercept
    # hostname-based URLs). Resolution order:
    # 1. VECTOR_INGEST_LOCAL / VECTOR_INGEST_PORT env vars (explicit override)
    # 2. PortManager.get() — same machine, reads ~/.ports-allocator/ directly
    # 3. Hardcoded default
    ingest_url: str | None = os.environ.get("VECTOR_INGEST_LOCAL") or (
        f"http://localhost:{os.environ['VECTOR_INGEST_PORT']}"
        if os.environ.get("VECTOR_INGEST_PORT")
        else None
    )
    if not ingest_url:
        try:
            from ports_allocator import PortManager

            port = PortManager().get("obs.vector_ingest", workspace=str(Path.cwd().resolve()))
            if port:
                ingest_url = f"http://localhost:{port}"
        except Exception:
            pass
    if not ingest_url:
        ingest_url = "http://localhost:9880"

    class VectorHandler(logging.Handler):
        def __init__(self, url: str, svc: str) -> None:
            super().__init__()
            self._url = url
            self._svc = svc

        def emit(self, record: logging.LogRecord) -> None:
            try:
                payload = json.dumps(
                    {
                        "message": self.format(record),
                        "level": record.levelname.lower(),
                        "service": self._svc,
                        "logger": record.name,
                    }
                ).encode()
                req = Request(self._url, data=payload, headers={"Content-Type": "application/json"})
                urlopen(req, timeout=1)  # noqa: S310
            except Exception:
                pass  # Never let logging errors crash the agent

    handler = VectorHandler(ingest_url, service_name)
    handler.setLevel(logging.INFO)
    # Python's root logger defaults to WARNING; lower it so INFO records can
    # propagate to our handler.  Only lower — never raise it if caller already
    # set a more verbose level.
    root_logger = logging.getLogger()
    if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)
    # Also attach directly to the CLI's structured logger (pydantic_deep.tui),
    # which has propagate=False so it never reaches the root logger.
    tui_logger = logging.getLogger("pydantic_deep.tui")
    if tui_logger.level == logging.NOTSET or tui_logger.level > logging.INFO:
        tui_logger.setLevel(logging.INFO)
    tui_logger.addHandler(handler)


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
        typer.Option(
            "--logfire/--no-logfire",
            help="Enable Logfire tracing (overrides PYDANTIC_DEEP_LOGFIRE env var)",
        ),
    ] = None,
    phoenix_enabled: Annotated[
        bool,
        typer.Option(
            "--phoenix/--no-phoenix",
            help="Send traces to Arize Phoenix (reads PHOENIX_PORT from .env, defaults to 6006)",
        ),
    ] = False,
    vector_enabled: Annotated[
        bool,
        typer.Option("--vector/--no-vector", help="Enable Vector OTLP tracing"),
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

    if logfire_enabled is None or not vector_enabled:
        # Flag not explicitly passed — fall back to config/env var.
        from apps.cli.config import load_config

        config = load_config()
        if logfire_enabled is None:
            logfire_enabled = config.logfire
        if not vector_enabled:
            vector_enabled = config.vector
    # If --logfire or --no-logfire was explicitly passed it takes full precedence
    # over the PYDANTIC_DEEP_LOGFIRE env var.

    if logfire_enabled:
        _setup_logfire()
    elif vector_enabled:
        _setup_vector()

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
    code_graph: Annotated[
        bool | None,
        typer.Option(
            "--code-graph/--no-code-graph", help="Enable code graph capabilities (from config)"
        ),
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", help="Potpie project ID (overrides config)"),
    ] = None,
    user_id: Annotated[
        str | None,
        typer.Option("--user-id", help="Potpie user ID"),
    ] = None,
    enable_mcp: Annotated[
        bool,
        typer.Option(
            "--mcp/--no-mcp",
            help="Connect to code-graph MCP server (provider from kg.provider config)",
        ),
    ] = False,
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
        pydantic-deep run "Analyze capabilities of watchdog_timer device" --code-graph --project-id my-potpie-project
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
            code_graph=code_graph,
            project_id=project_id,
            user_id=user_id,
            enable_mcp=enable_mcp,
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
        typer.Option(
            "--phoenix-port", "-p", help="Phoenix server port (default: PHOENIX_PORT env or 6006)"
        ),
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
    branch: Annotated[str | None, typer.Option("--branch", "-b", help="Branch name")] = None,
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
                f"[dim]Set as default: pydantic-deep config set kg.project_id {project_id}[/dim]"
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


# -- wiki generation command (experimental) --
@app.command("gen-wiki")
def gen_wiki(
    project_id: Annotated[str, typer.Option("--project-id", "-p", help="Project ID")],
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="User ID (default: defaultuser)"),
    ] = "defaultuser",
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "Root directory for wiki pages. "
                "Defaults to .repowiki/en/content (or POTPIE_WIKI_OUTPUT_DIR env var)."
            ),
        ),
    ] = None,
) -> None:
    """Generate wiki documentation for a Simics DML device model.

    Runs the full analysis pipeline (registers, interfaces, FSM, events,
    capabilities) and writes Markdown wiki pages. The device name is passed as
    ChatContext.query; force and output are passed via additional_context as JSON.

    Examples:\n
        pydantic-deep simics-device wiki --project-id <id> --device-name my_dev\n
        pydantic-deep simics-device wiki --project-id <id> --device-name my_dev --force\n
        pydantic-deep simics-device wiki --project-id <id> --device-name my_dev --output ./wiki
    """
    console = Console()

    async def _run() -> None:
        import app.core.models  # noqa: ensure all SQLAlchemy models are registered
        from app.modules.intelligence.agents.chat_agent import ChatContext

        runtime = _make_code_graph_runtime()
        _rt = await runtime._get_runtime()
        project_info = await _rt.projects.get(project_id)
        project_name = project_info.repo_name
        agent_id = "wiki_generation_agent"
        additional_context = json.dumps(
            {
                "output": output,
            }
        )

        try:
            agent_handle = getattr(_rt.agents, agent_id)
            conversation_id = str(uuid.uuid4())
            ctx = ChatContext(
                project_id=project_id,
                project_name=project_name,
                curr_agent_id=agent_id,
                user_id=user_id,
                query=f"Generate wiki for {project_name}",
                additional_context=additional_context,
                conversation_id=conversation_id,
                history=[],
            )
            response = await agent_handle.query(ctx)
            console.print(response.response)
        except Exception as e:
            console.print(f"[red]Error running agent:[/red] {e}")

    asyncio.run(_run())


# ── spec sub-app ──────────────────────────────────────────────────────────────

spec_app = typer.Typer(
    name="spec",
    help="Index and query specification documentation via the potpie backend.",
    no_args_is_help=True,
)
app.add_typer(spec_app)


def _collect_spec_texts(path: str, extensions: list[str] | None) -> tuple[list[str], list[str]]:
    """Read text files under *path* and return (texts, file_paths).

    If *extensions* is provided only files whose suffix (without the leading
    dot, e.g. ``"md"``) is in the set are included.  Both files and directories
    are accepted for *path*.
    """
    from pathlib import Path as _Path

    exts: set[str] | None = {e.lstrip(".").lower() for e in extensions} if extensions else None
    root = _Path(path)
    candidates = [root] if root.is_file() else list(root.rglob("*"))
    texts: list[str] = []
    file_paths: list[str] = []
    for fp in candidates:
        if not fp.is_file():
            continue
        if exts and fp.suffix.lstrip(".").lower() not in exts:
            continue
        try:
            texts.append(fp.read_text(encoding="utf-8", errors="ignore"))
            file_paths.append(str(fp))
        except OSError:
            pass
    return texts, file_paths


@spec_app.command("index")
def spec_index(
    paths: Annotated[
        list[str],
        typer.Option(
            "--path",
            "-P",
            help="File or directory to index (repeatable: --path /a --path /b).",
        ),
    ],
    project_name: Annotated[
        str | None,
        typer.Option(
            "--project-name",
            "-n",
            help="Project name — looks up an existing project by this name.",
        ),
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option(
            "--project-id",
            "-p",
            help="Project ID to index into. If --project-name is also given it must match.",
        ),
    ] = None,
    extensions: Annotated[
        list[str] | None,
        typer.Option(
            "--ext",
            "-e",
            help=(
                "File extension(s) to include when PATH is a directory "
                "(e.g. --ext md --ext rst).  Omit to include all readable files."
            ),
        ),
    ] = None,
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="User ID for the LightRAG workspace (default: defaultuser)"),
    ] = "defaultuser",
    prompt: Annotated[
        str | None,
        typer.Option(
            "--prompt",
            help="Additional user prompt for LightRAG entity extraction.",
        ),
    ] = None,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API (required)"),
    ] = False,
) -> None:
    """Index files into the LightRAG workspace for a project.

    Reads all readable files under each --path (optionally filtered by --ext)
    and inserts their text into the project's LightRAG on-disk workspace via
    ``ainsert``.  The workspace is keyed by project ID and user ID so
    ``spec query`` can read the result.

    Examples:\n
        pydantic-deep spec index --path /docs --project-name my-spec --local\n
        pydantic-deep spec index --path /a --path /b --project-id <id> --ext md --local
    """
    if not project_name and not project_id:
        typer.echo("Error: specify at least one of --project-name or --project-id.", err=True)
        raise typer.Exit(1)

    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()
        all_projects = await runtime.list_projects()

        if project_name:
            existing = next(
                (
                    p
                    for p in all_projects
                    if p.get("repo_name", p.get("project_name", "")) == project_name
                ),
                None,
            )
            if existing is None:
                console.print(f"[dim]Project '{project_name}' not found — registering it…[/dim]")
                with console.status("[bold blue]Registering project…[/bold blue]"):
                    reg_result = await runtime.register_project(project_name=project_name)
                effective_project_id = reg_result.get("project_id", "")
                if not effective_project_id:
                    console.print("[red]Failed to register project.[/red]")
                    raise typer.Exit(1)
                console.print(f"[green]Project registered:[/green] {effective_project_id}")
            else:
                found_id = existing.get("id", "")
                if project_id and project_id != found_id:
                    console.print(
                        f"[red]Error: --project-id '{project_id}' does not match the project "
                        f"for '{project_name}' (ID: '{found_id}'). Remove one of the flags.[/red]"
                    )
                    raise typer.Exit(1)
                effective_project_id = found_id
        else:
            existing = next((p for p in all_projects if p.get("id") == project_id), None)
            if existing is None:
                console.print(
                    f"[red]Project '{project_id}' not found. "
                    "Register a project first with: pydantic-deep parse repo <path> --local[/red]"
                )
                raise typer.Exit(1)
            effective_project_id = project_id

        repo_name = (
            existing.get("repo_name", existing.get("project_name", effective_project_id))
            if existing
            else project_name or effective_project_id
        )
        console.print(f"[bold]Project ID:[/bold] {effective_project_id}")
        console.print(f"[bold]Name:[/bold]       {repo_name}")

        if not paths:
            console.print("[red]Provide at least one --path to index.[/red]")
            raise typer.Exit(1)

        console.print(f"[dim]Reading files from {paths}…[/dim]")
        texts: list[str] = []
        file_paths: list[str] = []
        for p in paths:
            p_texts, p_file_paths = _collect_spec_texts(p, extensions)
            texts.extend(p_texts)
            file_paths.extend(p_file_paths)
        for fp in file_paths:
            console.print(f"[dim]  {fp}[/dim]")
        if not texts:
            console.print(
                f"[red]No readable files found under {paths}"
                + (f" (extensions: {extensions})" if extensions else "")
                + ".[/red]"
            )
            raise typer.Exit(1)

        console.print(f"[dim]Inserting {len(texts)} document(s) into LightRAG…[/dim]")
        with console.status("[bold blue]Inserting text → LightRAG…[/bold blue]"):
            result = await runtime.spec_insert_texts(
                project_id=effective_project_id,
                user_id=user_id,
                texts=texts,
                file_paths=file_paths,
                prompt=prompt,
            )

        workspace = result.get("workspace", "")
        console.print(
            f"\n[green]Done.[/green] inserted={result.get('inserted', len(texts))} document(s)"
        )
        if workspace:
            console.print(f"[dim]Workspace: {workspace}[/dim]")

        # Purge stale query-cache entries so subsequent queries reflect the new index.
        with console.status("[dim]Purging stale query cache…[/dim]"):
            purged = await runtime.spec_purge_query_cache(
                project_id=effective_project_id,
                user_id=user_id,
            )
        if purged:
            console.print(f"[dim]Purged {purged} stale query-cache entry(ies).[/dim]")

        console.print(
            "[dim]Set as default: pydantic-deep config set"
            f" potpie_project_id {effective_project_id}[/dim]"
        )

    asyncio.run(_run())


@spec_app.command("query")
def spec_query(
    query_text: Annotated[
        str | None, typer.Argument(help="Query text. Optional when --summarize is set.")
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", "-p", help="Project ID to query."),
    ] = None,
    project_name: Annotated[
        str | None,
        typer.Option(
            "--project-name",
            "-n",
            help="Project name to query — looks up the project by name. Errors if not found.",
        ),
    ] = None,
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="User ID (default: from config)"),
    ] = "defaultuser",
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            "-m",
            help="LightRAG query mode: local, global, hybrid (default), mix, naive, bypass.",
        ),
    ] = "hybrid",
    summarize: Annotated[
        bool,
        typer.Option(
            "--summarize", "-s", help="Query with a pre-defined hardware IP summary prompt."
        ),
    ] = False,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API"),
    ] = False,
) -> None:
    """Query spec documentation for a project using LightRAG.

    Modes (LightRAG):\n
      local   — entity-centric, answers about specific items\n
      global  — dataset-level, answers about overall themes\n
      hybrid  — combines local + global (default)\n
      mix     — integrated graph + vector search\n
      naive   — plain vector similarity (no graph traversal)\n
      bypass  — pass query directly to LLM without retrieval
    """
    if not project_name and not project_id:
        typer.echo("Error: specify at least one of --project-name or --project-id.", err=True)
        raise typer.Exit(1)

    if not summarize and not query_text:
        typer.echo("Error: query text is required unless --summarize is set.", err=True)
        raise typer.Exit(1)

    valid_modes = ("local", "global", "hybrid", "mix", "naive", "bypass")
    if mode not in valid_modes:
        typer.echo(f"Error: --mode must be one of {valid_modes}", err=True)
        raise typer.Exit(1)

    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()

        effective_project_id = project_id
        if project_name:
            all_projects = await runtime.list_projects()
            existing = next(
                (
                    p
                    for p in all_projects
                    if p.get("repo_name", p.get("project_name", "")) == project_name
                ),
                None,
            )
            if existing is None:
                console.print(f"[red]Project '{project_name}' not found.[/red]")
                raise typer.Exit(1)
            found_id = existing.get("id", "")
            if project_id and project_id != found_id:
                console.print(
                    f"[red]Error: --project-id '{project_id}' does not match the project "
                    f"for '{project_name}' (ID: '{found_id}'). Remove one of the flags.[/red]"
                )
                raise typer.Exit(1)
            effective_project_id = found_id

        with console.status(f"[bold blue]Querying ({mode})…[/bold blue]"):
            answer = await runtime.spec_query(
                project_id=effective_project_id,
                user_id=user_id,
                query=query_text or "",
                mode=mode,
                summarize=summarize,
            )
        console.print(answer)

    asyncio.run(_run())


@spec_app.command("list")
def spec_list(
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", "-p", help="Project ID to list documents for."),
    ] = None,
    project_name: Annotated[
        str | None,
        typer.Option(
            "--project-name",
            "-n",
            help="Project name — looks up the project by name.",
        ),
    ] = None,
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="User ID for the LightRAG workspace (default: defaultuser)"),
    ] = "defaultuser",
    output_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API (required)"),
    ] = False,
) -> None:
    """List all documents indexed in the LightRAG workspace for a project."""
    if not project_name and not project_id:
        typer.echo("Error: specify at least one of --project-name or --project-id.", err=True)
        raise typer.Exit(1)

    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()

        effective_project_id = project_id
        if project_name:
            all_projects = await runtime.list_projects()
            existing = next(
                (
                    p
                    for p in all_projects
                    if p.get("repo_name", p.get("project_name", "")) == project_name
                ),
                None,
            )
            if existing is None:
                console.print(f"[red]Project '{project_name}' not found.[/red]")
                raise typer.Exit(1)
            found_id = existing.get("id", "")
            if project_id and project_id != found_id:
                console.print(
                    f"[red]Error: --project-id '{project_id}' does not match the project "
                    f"for '{project_name}' (ID: '{found_id}'). Remove one of the flags.[/red]"
                )
                raise typer.Exit(1)
            effective_project_id = found_id

        docs = await runtime.spec_list_docs(
            project_id=effective_project_id,
            user_id=user_id,
        )

        if output_json:
            import json

            console.print(json.dumps(docs, indent=2))
            return

        if not docs:
            console.print("[dim]No indexed documents found.[/dim]")
            return

        from rich.table import Table

        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=4)
        table.add_column("Doc ID", style="dim")
        table.add_column("File Path")
        table.add_column("Status")
        table.add_column("Chunks", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Indexed At")
        for i, doc in enumerate(docs, 1):
            table.add_row(
                str(i),
                doc["doc_id"],
                doc["file_path"] or "",
                doc["status"],
                str(doc["chunks_count"]),
                str(doc["content_length"]),
                doc["created_at"][:19] if doc["created_at"] else "",
            )
        console.print(table)
        console.print(f"[dim]Total: {len(docs)} document(s)[/dim]")

    asyncio.run(_run())


@spec_app.command("del")
def spec_del(
    doc_ids: Annotated[
        list[str],
        typer.Argument(help="Document ID(s) to delete (e.g. doc-2fe649…). Repeat for multiple."),
    ],
    project_id: Annotated[
        str | None,
        typer.Option("--project-id", "-p", help="Project ID the document belongs to."),
    ] = None,
    project_name: Annotated[
        str | None,
        typer.Option(
            "--project-name",
            "-n",
            help="Project name — looks up the project by name.",
        ),
    ] = None,
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="User ID for the LightRAG workspace (default: defaultuser)"),
    ] = "defaultuser",
    delete_llm_cache: Annotated[
        bool,
        typer.Option(
            "--delete-cache", help="Also delete cached LLM extraction results for the document."
        ),
    ] = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation prompt.")] = False,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API (required)"),
    ] = False,
) -> None:
    """Delete document(s) and all their entities/edges from the LightRAG index.

    Use `pydantic-deep spec list` to find document IDs.\n
    Example:\n
        pydantic-deep spec del doc-2fe649… --project-name my-spec --local
    """
    if not project_name and not project_id:
        typer.echo("Error: specify at least one of --project-name or --project-id.", err=True)
        raise typer.Exit(1)

    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()

        effective_project_id = project_id
        if project_name:
            all_projects = await runtime.list_projects()
            existing = next(
                (
                    p
                    for p in all_projects
                    if p.get("repo_name", p.get("project_name", "")) == project_name
                ),
                None,
            )
            if existing is None:
                console.print(f"[red]Project '{project_name}' not found.[/red]")
                raise typer.Exit(1)
            found_id = existing.get("id", "")
            if project_id and project_id != found_id:
                console.print(
                    f"[red]Error: --project-id '{project_id}' does not match the project "
                    f"for '{project_name}' (ID: '{found_id}'). Remove one of the flags.[/red]"
                )
                raise typer.Exit(1)
            effective_project_id = found_id

        if not force:
            confirm = typer.confirm(
                f"Delete {len(doc_ids)} document(s) from project '{effective_project_id}'?"
            )
            if not confirm:
                console.print("[dim]Aborted.[/dim]")
                raise typer.Exit(0)

        for doc_id in doc_ids:
            with console.status(f"[bold blue]Deleting {doc_id}…[/bold blue]"):
                result = await runtime.spec_delete_doc(
                    project_id=effective_project_id,
                    user_id=user_id,
                    doc_id=doc_id,
                    delete_llm_cache=delete_llm_cache,
                )
            status = result["status"]
            msg = result.get("message", "")
            file_path = result.get("file_path") or ""
            label = f"{doc_id}" + (f" ({file_path})" if file_path else "")
            if status == "success":
                console.print(f"[green]Deleted:[/green] {label}")
            elif status == "not_found":
                console.print(f"[yellow]Not found:[/yellow] {label} — {msg}")
            else:
                console.print(f"[red]Failed:[/red] {label} — {msg}")

        # After all deletions, purge stale query-cache entries so subsequent
        # spec query calls hit the updated knowledge graph.
        with console.status("[dim]Purging stale query cache…[/dim]"):
            purged = await runtime.spec_purge_query_cache(
                project_id=effective_project_id,
                user_id=user_id,
            )
        if purged:
            console.print(f"[dim]Purged {purged} stale query-cache entry(ies).[/dim]")

    asyncio.run(_run())


@spec_app.command("diff")
def spec_diff(
    project_names: Annotated[
        list[str] | None,
        typer.Option(
            "--project-name",
            "-n",
            help="Project name (repeat twice for base and new: --project-name ip-v1 --project-name ip-v2).",
        ),
    ] = None,
    project_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--project-id",
            "-p",
            help="Project ID (repeat twice for base and new: --project-id <id-a> --project-id <id-b>).",
        ),
    ] = None,
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="User ID (default: defaultuser)"),
    ] = "defaultuser",
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            "-m",
            help="LightRAG query mode: local, global, hybrid (default), mix, naive, bypass.",
        ),
    ] = "hybrid",
    summarize: Annotated[
        bool,
        typer.Option(
            "--summarize/--no-summarize",
            "-s",
            help=(
                "When set, produce a high-level feature summary grouped under broad headings. "
                "Default (--no-summarize) gives signal-level detail: exact register/field/signal names, "
                "bit widths, reset values, and precise behavioural differences."
            ),
        ),
    ] = False,
    local: Annotated[
        bool,
        typer.Option("--local", help="Use direct PotpieRuntime instead of REST API"),
    ] = False,
) -> None:
    """Query delta features between two spec graphs.

    With --summarize (default) outputs a high-level feature delta grouped under
    broad headings.  With --no-summarize outputs signal-level detail including
    exact register/field/signal names, bit widths, and behavioural differences.

    Examples:\n
        pydantic-deep spec diff --project-name ip-v1 --project-name ip-v2 --local\n
        pydantic-deep spec diff --project-id <id-a> --project-id <id-b> --no-summarize --local
    """
    names = project_names or []
    ids = project_ids or []

    if not names and not ids:
        typer.echo(
            "Error: specify --project-name or --project-id (repeat twice for base and new).",
            err=True,
        )
        raise typer.Exit(1)
    if names and len(names) != 2:
        typer.echo(
            f"Error: --project-name must be specified exactly twice, got {len(names)}.", err=True
        )
        raise typer.Exit(1)
    if ids and len(ids) != 2:
        typer.echo(
            f"Error: --project-id must be specified exactly twice, got {len(ids)}.", err=True
        )
        raise typer.Exit(1)
    if ids and names:
        typer.echo("Error: specify either --project-name or --project-id, not both.", err=True)
        raise typer.Exit(1)

    valid_modes = ("local", "global", "hybrid", "mix", "naive", "bypass")
    if mode not in valid_modes:
        typer.echo(f"Error: --mode must be one of {valid_modes}", err=True)
        raise typer.Exit(1)

    console = Console()

    async def _run() -> None:
        runtime = _make_code_graph_runtime()
        all_projects = await runtime.list_projects()

        def _resolve(name: str | None) -> str:
            existing = next(
                (p for p in all_projects if p.get("repo_name", p.get("project_name", "")) == name),
                None,
            )
            if existing is None:
                console.print(f"[red]Project '{name}' not found.[/red]")
                raise typer.Exit(1)
            return existing.get("id", "")

        name_a, name_b = (names[0], names[1]) if names else (None, None)
        id_a, id_b = (ids[0], ids[1]) if ids else (None, None)
        if ids:
            eff_id_a, eff_id_b = id_a, id_b
        else:
            eff_id_a = _resolve(name_a)
            eff_id_b = _resolve(name_b)

        label_a = eff_id_a
        label_b = eff_id_b

        detail_label = "summary" if summarize else "signal-level detail"
        with console.status(
            f"[bold blue]Querying both specs ({mode}, {detail_label})…[/bold blue]"
        ):
            delta = await runtime.spec_diff(
                project_id_a=eff_id_a,
                project_id_b=eff_id_b,
                user_id=user_id,
                mode=mode,
                summarize=summarize,
            )

        console.print(delta)

    asyncio.run(_run())


# ── simics_device sub-app ─────────────────────────────────────────────────────

simics_device_app = typer.Typer(
    name="simics-device",
    help="Analyze and inspect Simics DML device models.",
    no_args_is_help=True,
)
app.add_typer(simics_device_app)

_ANALYZE_FEATURES = ("attribute", "register", "interface", "fsm", "event", "capability", "all")
_SHOW_FEATURES = ("attribute", "register", "interface", "fsm", "event", "capability", "all")


@simics_device_app.command("analyze")
def simics_device_analyze(
    project_id: Annotated[str, typer.Option("--project-id", "-p", help="Project ID")],
    device_name: Annotated[str, typer.Option("--device-name", "-d", help="DML device name")],
    feature: Annotated[
        str,
        typer.Option(
            "--feature",
            "-f",
            help=f"Feature to analyze: {', '.join(_ANALYZE_FEATURES)}",
        ),
    ] = "all",
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Force re-analysis (ignore cached results)")
    ] = False,
    batch_size: Annotated[
        int | None,
        typer.Option(
            "--batch-size",
            help=(
                "Optional per-request batch size. "
                "Used by register/interface/fsm/event/capability analyzers."
            ),
        ),
    ] = None,
    chunk_tokens: Annotated[
        int | None,
        typer.Option(
            "--chunk-tokens",
            help=(
                "Optional token budget per chunk. "
                "Used by register/interface/capability analyzers."
            ),
        ),
    ] = None,
    chunk_limit: Annotated[
        int | None,
        typer.Option(
            "--chunk-limit",
            help="Optional chunk limit. Used by fsm analyzer.",
        ),
    ] = None,
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="User ID (default: defaultuser)"),
    ] = "defaultuser",
) -> None:
    """Analyze a Simics DML device model (registers, interfaces, FSM, events, capabilities).

    Examples:\n
        pydantic-deep simics-device analyze --project-id <id> --device-name my_dev\n
        pydantic-deep simics-device analyze --project-id <id> --device-name my_dev --feature register --refresh
    """
    if feature not in _ANALYZE_FEATURES:
        typer.echo(f"Error: --feature must be one of: {', '.join(_ANALYZE_FEATURES)}", err=True)
        raise typer.Exit(1)

    console = Console()

    async def _run() -> None:
        from pydantic_deep.providers.code_graph import make_provider

        runtime: Any = make_provider("potpie", user_id=user_id)
        features_to_run = ["attribute", "register", "interface", "fsm", "event", "capability"] if feature == "all" else [feature]
        if "capability" in features_to_run:
            features_to_run = [feat for feat in features_to_run if feat != "capability"] + ["capability"]

        for feat in features_to_run:
            with console.status(f"[bold blue]Analyzing {feat}…[/bold blue]"):
                if feat == "register":
                    kwargs: dict[str, Any] = {
                        "project_id": project_id,
                        "device_name": device_name,
                        "refresh": refresh,
                    }
                    if batch_size is not None:
                        kwargs["batch_size"] = batch_size
                    if chunk_tokens is not None:
                        kwargs["chunk_tokens"] = chunk_tokens
                    result = await runtime.analyze_register_side_effect(**kwargs)
                elif feat == "interface":
                    kwargs = {
                        "project_id": project_id,
                        "device_name": device_name,
                        "refresh": refresh,
                    }
                    if batch_size is not None:
                        kwargs["batch_size"] = batch_size
                    if chunk_tokens is not None:
                        kwargs["chunk_tokens"] = chunk_tokens
                    result = await runtime.analyze_interface(**kwargs)
                elif feat == "fsm":
                    kwargs = {
                        "project_id": project_id,
                        "device_name": device_name,
                        "refresh": refresh,
                    }
                    if batch_size is not None:
                        kwargs["batch_size"] = batch_size
                    if chunk_limit is not None:
                        kwargs["chunk_limit"] = chunk_limit
                    result = await runtime.analyze_fsm(**kwargs)
                elif feat == "event":
                    kwargs = {
                        "project_id": project_id,
                        "device_name": device_name,
                        "refresh": refresh,
                    }
                    if batch_size is not None:
                        kwargs["batch_size"] = batch_size
                    result = await runtime.analyze_event(**kwargs)
                elif feat == "attribute":
                        kwargs = {
                            "project_id": project_id,
                            "device_name": device_name,
                            "refresh": refresh,
                        }
                        if batch_size is not None:
                            kwargs["batch_size"] = batch_size
                        result = await runtime.analyze_attribute(**kwargs)
                else:  # capability
                    kwargs = {
                        "project_id": project_id,
                        "device_name": device_name,
                        "refresh": refresh,
                    }
                    if batch_size is not None:
                        kwargs["batch_size"] = batch_size
                    if chunk_tokens is not None:
                        kwargs["chunk_tokens"] = chunk_tokens
                    result = await runtime.analyze_capability(**kwargs)

            console.print(f"\n[bold cyan]=== {feat.upper()} ===[/bold cyan]")
            if isinstance(result, dict):
                console.print_json(json.dumps(result, default=str))
            else:
                console.print(str(result))

    asyncio.run(_run())


@simics_device_app.command("show")
def simics_device_show(
    project_id: Annotated[str, typer.Option("--project-id", "-p", help="Project ID")],
    device_name: Annotated[str, typer.Option("--device-name", "-d", help="DML device name")],
    feature: Annotated[
        str,
        typer.Option(
            "--feature",
            "-f",
            help=f"Feature to show: {', '.join(_SHOW_FEATURES)}",
        ),
    ] = "all",
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="User ID (default: defaultuser)"),
    ] = "defaultuser",
    output_json: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
    gen_specs: Annotated[
        bool,
        typer.Option("--gen-specs", help="Write per-capability spec files to --output dir (capability feature only)"),
    ] = False,
    output: Annotated[
        str | None,
        typer.Option("--output", "-o", help="Output directory for capability spec files (capability feature only)"),
    ] = None,
) -> None:
    """Show stored features of a Simics DML device (registers, interfaces, FSM, events, capabilities).

    Examples:\n
        pydantic-deep simics-device show --project-id <id> --device-name my_dev\n
        pydantic-deep simics-device show --project-id <id> --device-name my_dev --feature capability --json\n
        pydantic-deep simics-device show --project-id <id> --device-name my_dev --feature capability --gen-specs --output ./specs
    """
    if feature not in _SHOW_FEATURES:
        typer.echo(f"Error: --feature must be one of: {', '.join(_SHOW_FEATURES)}", err=True)
        raise typer.Exit(1)

    if (gen_specs or output) and feature != "capability":
        typer.echo("Warning: --gen-specs and --output are only used when --feature=capability; ignoring.", err=True)

    console = Console()

    async def _run() -> None:
        import app.core.models  # noqa: ensure all SQLAlchemy models are registered
        from app.core.database import SessionLocal
        from app.modules.intelligence.tools.simics_device_tools.list_capability_tool import (
            ListCapabilityTool,
        )
        from app.modules.intelligence.tools.simics_device_tools.list_simics_device_feature import (
            ListSimicsDeviceFeatureTool,
        )

        db = SessionLocal()
        try:
            if feature == "capability":
                tool = ListCapabilityTool(db, user_id)
                result = await tool.arun(
                    project_id,
                    device_name,
                    gen_specs=gen_specs,
                    output=output,
                )
            else:
                tool = ListSimicsDeviceFeatureTool(db, user_id)
                result = await tool.arun(project_id, device_name, feature=feature)
        finally:
            db.close()

        if output_json:
            typer.echo(json.dumps(result, indent=2, default=str))
            return

        if isinstance(result, dict):
            console.print_json(json.dumps(result, default=str))
        else:
            console.print(str(result))

    asyncio.run(_run())


@simics_device_app.command("wiki")
def simics_device_wiki(
    project_id: Annotated[str, typer.Option("--project-id", "-p", help="Project ID")],
    device_name: Annotated[str, typer.Option("--device-name", "-d", help="DML device name")],
    user_id: Annotated[
        str,
        typer.Option("--user-id", help="User ID (default: defaultuser)"),
    ] = "defaultuser",
    force: Annotated[
        bool,
        typer.Option("--force", help="Force regeneration even if pages already exist"),
    ] = False,
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help=(
                "Root directory for wiki pages. "
                "Pages are written to <output>/<section>/<subsection>/<page>.md. "
                "Defaults to .repowiki/en/content (or POTPIE_WIKI_OUTPUT_DIR env var)."
            ),
        ),
    ] = None,
) -> None:
    """Generate wiki documentation for a Simics DML device model.

    Runs the full analysis pipeline (registers, interfaces, FSM, events,
    capabilities) and writes Markdown wiki pages. The device name is passed as
    ChatContext.query; force and output are passed via additional_context as JSON.

    Examples:\n
        pydantic-deep simics-device wiki --project-id <id> --device-name my_dev\n
        pydantic-deep simics-device wiki --project-id <id> --device-name my_dev --force\n
        pydantic-deep simics-device wiki --project-id <id> --device-name my_dev --output ./wiki
    """
    console = Console()

    async def _run() -> None:
        import app.core.models  # noqa: ensure all SQLAlchemy models are registered
        from app.modules.intelligence.agents.chat_agent import ChatContext

        runtime = _make_code_graph_runtime()
        _rt = await runtime._get_runtime()
        project_info = await _rt.projects.get(project_id)
        project_name = project_info.repo_name
        agent_id = "simics_device_wiki_agent"
        additional_context = json.dumps(
            {
                "force": force,
                "output": output,
            }
        )

        try:
            agent_handle = getattr(_rt.agents, agent_id)
            conversation_id = str(uuid.uuid4())
            ctx = ChatContext(
                project_id=project_id,
                project_name=project_name,
                curr_agent_id=agent_id,
                user_id=user_id,
                query=device_name,
                additional_context=additional_context,
                conversation_id=conversation_id,
                history=[],
            )
            response = await agent_handle.query(ctx)
            console.print(response.response)
        except Exception as e:
            console.print(f"[red]Error running agent:[/red] {e}")

    asyncio.run(_run())


@simics_device_app.command("explore")
def simics_device_explore(
    project_id: Annotated[str, typer.Option("--project-id", "-p", help="Project ID")],
    device_name: Annotated[str, typer.Option("--device-name", "-d", help="DML device name")],
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Force refresh of cached device structure")
    ] = False,
) -> None:
    """Explore the full structural inventory of a Simics DML device.

    Examples:\n
        pydantic-deep simics-device explore --project-id <id> --device-name my_dev\n
        pydantic-deep simics-device explore --project-id <id> --device-name my_dev --refresh
    """
    console = Console()

    async def _run() -> None:
        from app.core.database import SessionLocal
        from app.modules.intelligence.tools.simics_device_tools.explore_simics_device_tool import (
            ExploreSimicsDeviceTool,
        )

        db = SessionLocal()
        try:
            tool = ExploreSimicsDeviceTool(db, "defaultuser")
            with console.status("[bold blue]Exploring device structure…[/bold blue]"):
                result = await tool.arun(project_id, device_name, refresh=refresh)
        finally:
            db.close()

        if isinstance(result, dict):
            console.print_json(json.dumps(result, default=str))
        else:
            console.print(str(result))

    asyncio.run(_run())


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

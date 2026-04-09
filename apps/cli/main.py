"""CLI entry point for pydantic-deep.

Usage:
    pydantic-deep                           # Launch TUI (default)
    pydantic-deep tui [-m model] [-w dir]   # Launch TUI
    pydantic-deep init                      # Initialize project
    pydantic-deep config show               # Show configuration
    pydantic-deep skills list               # List available skills
    pydantic-deep threads list              # List saved threads
"""

from __future__ import annotations

import json
import os
from dataclasses import fields
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

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


def _setup_logfire() -> None:
    """Configure Logfire tracing for all pydantic-ai agents."""
    try:
        import logfire

        logfire.configure(
            token=os.environ.get("LOGFIRE_TOKEN"),
            send_to_logfire="if-token-present",
        )
        logfire.instrument_pydantic_ai()
    except ImportError:
        import sys

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
        bool,
        typer.Option("--logfire/--no-logfire", help="Enable Logfire tracing"),
    ] = False,
) -> None:
    """Deep Agent CLI — AI coding assistant powered by pydantic-ai."""
    try:
        from dotenv import load_dotenv

        load_dotenv(Path.home() / ".pydantic-deep" / ".env", override=False)
        load_dotenv(Path.cwd() / ".pydantic-deep" / ".env", override=True)
        load_dotenv()
    except ImportError:  # pragma: no cover
        pass

    if not logfire_enabled:
        from apps.cli.config import load_config

        config = load_config()
        logfire_enabled = config.logfire

    if logfire_enabled:
        _setup_logfire()

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
) -> None:
    """Launch the Textual-based TUI (rich interactive interface)."""
    from apps.cli.init import ensure_initialized
    from apps.cli.tui import run_tui

    ensure_initialized()
    run_tui(model=model, working_dir=working_dir or os.getcwd())


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


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

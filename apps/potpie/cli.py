"""Potpie-deep CLI — parse, chat, and ask commands.

Three commands that wire PotpieRuntime into the pydantic-deep agent stack:

    potpie-deep parse <repo_path>          # build knowledge graph, print project_id
    potpie-deep chat --project-id <id>     # interactive streaming chat
    potpie-deep ask "<query>" --project-id <id>  # one-shot query
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from rich.console import Console

from potpie.exceptions import ConfigurationError, PotpieError

app = typer.Typer(
    name="potpie-deep",
    help="Potpie deep-agent CLI — code intelligence powered by pydantic-deep.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


@app.command()
def parse(
    repo_path: Annotated[str, typer.Argument(help="Path to the local git repository")],
    user_id: Annotated[str, typer.Option("--user-id", "-u", help="User ID")] = "default",
    branch: Annotated[str, typer.Option("--branch", "-b", help="Branch name")] = "main",
) -> None:
    """Parse a repository and build its knowledge graph.

    Prints the project_id to stdout on success so it can be piped into
    subsequent chat / ask commands.
    """
    exit_code = asyncio.run(_parse(repo_path, user_id, branch))
    raise typer.Exit(exit_code)


async def _parse(repo_path: str, user_id: str, branch: str) -> int:
    from potpie import PotpieRuntime

    runtime = None
    try:
        runtime = PotpieRuntime.from_env()
        await runtime.initialize()

        project_id = await runtime.projects.register(
            repo_name=repo_path,
            branch_name=branch,
            user_id=user_id,
            repo_path=repo_path,
        )

        await runtime.parsing.parse_project(
            project_id=project_id,
            user_id=user_id,
        )

        # Req 3.2: print project_id to stdout on success
        typer.echo(project_id)
        return 0

    except ConfigurationError as e:
        err_console.print(
            f"[red]Configuration error:[/red] {e}\n"
            "Ensure POSTGRES_SERVER, NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD are set."
        )
        return 1
    except PotpieError as e:
        err_console.print(
            f"[red]Backend error:[/red] {e}\n"
            "Ensure PostgreSQL and Neo4j are running (see .env or docker compose up)."
        )
        return 1
    except (ConnectionError, OSError) as e:
        err_console.print(
            f"[red]Cannot connect to backend services:[/red] {e}\n"
            "Ensure PostgreSQL and Neo4j are running (see .env or docker compose up)."
        )
        return 1
    except Exception as e:
        err_console.print(f"[red]Unexpected error:[/red] {e}")
        return 1
    finally:
        # Req 3.5 / 4.6: always close runtime
        if runtime is not None:
            await runtime.close()


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


@app.command()
def chat(
    project_id: Annotated[str, typer.Option("--project-id", "-p", help="Project ID")],
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override (e.g. anthropic:claude-opus-4-6)"),
    ] = None,
    user_id: Annotated[str, typer.Option("--user-id", "-u", help="User ID")] = "default",
) -> None:
    """Start an interactive chat session with your codebase knowledge graph."""
    asyncio.run(_chat(project_id, model, user_id))


async def _chat(project_id: str, model: str | None, user_id: str) -> None:
    from potpie import PotpieRuntime

    from apps.cli.interactive import _chat_loop, _setup_readline, _save_readline_history
    from apps.cli.display import print_welcome_banner
    from apps.potpie.agent import create_potpie_agent

    runtime = None
    try:
        runtime = PotpieRuntime.from_env()
        await runtime.initialize()

        agent, deps = create_potpie_agent(
            runtime=runtime,
            project_id=project_id,
            user_id=user_id,
            model=model,
        )

        _setup_readline()
        print_welcome_banner(console, model=model, working_dir=None)
        console.print(f"[dim]Project: {project_id}[/dim]\n")

        await _chat_loop(
            agent,
            deps,
            [],
            None,
            get_cost=lambda: 0.0,
            get_model=lambda: model,
            on_model_change=lambda m: None,
        )

    except ConfigurationError as e:
        err_console.print(
            f"[red]Configuration error:[/red] {e}\n"
            "Ensure POSTGRES_SERVER, NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD are set."
        )
        raise typer.Exit(1)
    except PotpieError as e:
        err_console.print(
            f"[red]Backend error:[/red] {e}\n"
            "Ensure PostgreSQL and Neo4j are running (see .env or docker compose up)."
        )
        raise typer.Exit(1)
    except (ConnectionError, OSError) as e:
        err_console.print(
            f"[red]Cannot connect to backend services:[/red] {e}\n"
            "Ensure PostgreSQL and Neo4j are running (see .env or docker compose up)."
        )
        raise typer.Exit(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/dim]")
    except Exception as e:
        err_console.print(f"[red]Unexpected error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        # Req 4.3 / 4.6: always close runtime
        if runtime is not None:
            await runtime.close()
        try:
            _save_readline_history()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------


@app.command()
def ask(
    query: Annotated[str, typer.Argument(help="Question to ask about the codebase")],
    project_id: Annotated[str, typer.Option("--project-id", "-p", help="Project ID")],
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model override (e.g. anthropic:claude-opus-4-6)"),
    ] = None,
    user_id: Annotated[str, typer.Option("--user-id", "-u", help="User ID")] = "default",
) -> None:
    """Run a one-shot query against the codebase knowledge graph."""
    exit_code = asyncio.run(_ask(query, project_id, model, user_id))
    raise typer.Exit(exit_code)


async def _ask(query: str, project_id: str, model: str | None, user_id: str) -> int:
    from potpie import PotpieRuntime

    from apps.potpie.agent import create_potpie_agent

    runtime = None
    try:
        runtime = PotpieRuntime.from_env()
        await runtime.initialize()

        agent, deps = create_potpie_agent(
            runtime=runtime,
            project_id=project_id,
            user_id=user_id,
            model=model,
        )

        result = await agent.run(query, deps=deps)
        # Req 5.1: print result to stdout
        typer.echo(result.output)
        return 0

    except ConfigurationError as e:
        err_console.print(
            f"[red]Configuration error:[/red] {e}\n"
            "Ensure POSTGRES_SERVER, NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD are set."
        )
        return 1
    except PotpieError as e:
        err_console.print(
            f"[red]Backend error:[/red] {e}\n"
            "Ensure PostgreSQL and Neo4j are running (see .env or docker compose up)."
        )
        return 1
    except (ConnectionError, OSError) as e:
        err_console.print(
            f"[red]Cannot connect to backend services:[/red] {e}\n"
            "Ensure PostgreSQL and Neo4j are running (see .env or docker compose up)."
        )
        return 1
    except Exception as e:
        err_console.print(f"[red]Unexpected error:[/red] {e}")
        return 1
    finally:
        # Req 5.3 / 4.6: always close runtime
        if runtime is not None:
            await runtime.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the potpie-deep CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

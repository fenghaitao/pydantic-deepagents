"""Diff view modal — /diff command. Shows colored git diff."""

from __future__ import annotations

import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


def _colorize_diff(diff_text: str) -> str:
    """Apply Rich markup colors to diff lines."""
    lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            lines.append(f"[bold]{line}[/bold]")
        elif line.startswith("+"):
            lines.append(f"[green]{line}[/green]")
        elif line.startswith("-"):
            lines.append(f"[red]{line}[/red]")
        elif line.startswith("@@"):
            lines.append(f"[cyan]{line}[/cyan]")
        elif line.startswith("diff "):
            lines.append(f"[yellow bold]{line}[/]")
        else:
            lines.append(line)
    return "\n".join(lines)


class DiffViewModal(ModalScreen[None]):
    """Shows git diff --stat and full diff in a scrollable overlay."""

    DEFAULT_CSS = """
    DiffViewModal {
        align: center middle;
    }
    DiffViewModal > #diff-container {
        width: 90%;
        max-width: 100;
        max-height: 85%;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def __init__(self, working_dir: str = ".") -> None:
        super().__init__()
        self._working_dir = working_dir

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="diff-container"):
            try:
                # Get branch
                branch_result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    text=True,
                    cwd=self._working_dir,
                    timeout=5,
                )
                branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "?"

                # Get stat
                stat = subprocess.run(
                    ["git", "diff", "--stat"],
                    capture_output=True,
                    text=True,
                    cwd=self._working_dir,
                    timeout=10,
                )

                # Get full diff
                diff = subprocess.run(
                    ["git", "diff"],
                    capture_output=True,
                    text=True,
                    cwd=self._working_dir,
                    timeout=10,
                )

                yield Static(f"[bold]Git Changes[/bold]  [dim]{branch}[/dim]\n")

                if stat.stdout.strip():
                    yield Static(stat.stdout.strip() + "\n")
                else:
                    yield Static("[dim]No uncommitted changes[/dim]\n")

                # Also show staged changes
                staged = subprocess.run(
                    ["git", "diff", "--cached", "--stat"],
                    capture_output=True,
                    text=True,
                    cwd=self._working_dir,
                    timeout=10,
                )
                if staged.stdout.strip():
                    yield Static(f"\n[bold]Staged[/bold]\n{staged.stdout.strip()}\n")

                if diff.stdout.strip():
                    yield Static(f"\n{_colorize_diff(diff.stdout)}")

            except Exception as e:
                yield Static(f"[bold]Git Changes[/bold]\n\n[red]Error: {e}[/red]")

            yield Static("\n[dim]Esc or q to close[/dim]")

    def action_dismiss(self) -> None:
        self.dismiss(None)

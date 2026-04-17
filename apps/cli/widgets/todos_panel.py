"""Todos display widget for the side panel."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

_STATUS_GLYPHS = {
    "pending": "○",
    "in_progress": "◐",
    "completed": "✓",
}

_STATUS_COLORS = {
    "pending": "",
    "in_progress": "bold",
    "completed": "dim",
}


class TodosWidget(Widget):
    """Displays the current TODO list."""

    DEFAULT_CSS = """
    TodosWidget {
        height: auto;
        padding: 1;
        border: tall $surface-lighten-2;
    }
    """

    todos: reactive[list[Any]] = reactive(list, always_update=True)

    def compose(self) -> ComposeResult:
        yield Static("[bold]TODOs[/bold]", id="todos-title")
        yield Static("", id="todos-list")

    def watch_todos(self, todos: list[Any]) -> None:
        content = self.query_one("#todos-list", Static)
        if not todos:
            content.update("[dim]No tasks yet[/dim]")
            return

        lines = []
        for todo in todos:
            status = getattr(todo, "status", "pending")
            text = getattr(todo, "content", str(todo))
            glyph = _STATUS_GLYPHS.get(status, "○")
            style = _STATUS_COLORS.get(status, "")
            if style:
                lines.append(f"[{style}]  {glyph} {text}[/{style}]")
            else:
                lines.append(f"  {glyph} {text}")

        content.update("\n".join(lines))

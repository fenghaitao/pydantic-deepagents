"""Optional side panel showing TODOs and subagents.

Visible only when terminal width >= 120 and there is content to show.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from apps.cli.widgets.subagents_panel import SubagentsWidget
from apps.cli.widgets.todos_panel import TodosWidget


class SidePanel(Vertical):
    """Right-side panel with TODOs and subagent status."""

    DEFAULT_CSS = """
    SidePanel {
        width: 32;
        display: none;
        padding: 0 1;
        border-left: tall $surface-lighten-2;
    }
    SidePanel.visible {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield TodosWidget()
        yield SubagentsWidget()

    def show_if_needed(self, width: int, has_content: bool) -> None:
        """Show or hide based on terminal width and content availability."""
        if width >= 120 and has_content:
            self.add_class("visible")
        else:
            self.remove_class("visible")

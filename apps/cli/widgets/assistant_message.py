"""Assistant message widget — container for tool calls and streaming text."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.markdown import Markdown

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from apps.cli.widgets.tool_call import ToolCallWidget


class AssistantMessage(Widget):
    """Container widget for a single assistant response turn.

    Holds tool calls (ToolCallWidget instances) and accumulated text.
    Uses a simple Static for text (not a separate StreamingText widget)
    to avoid mount-timing issues.
    """

    DEFAULT_CSS = """
    AssistantMessage {
        height: auto;
        padding: 0 0;
        margin: 1 0 0 0;
    }
    AssistantMessage .assistant-label {
        padding: 0 2;
    }
    AssistantMessage .assistant-text {
        padding: 0 2;
        height: auto;
    }
    """

    def __init__(self, timestamp: datetime | None = None) -> None:
        super().__init__()
        self._timestamp = timestamp or datetime.now()
        self._tool_widgets: dict[str, ToolCallWidget] = {}
        self._text: str = ""
        self._text_widget: Static | None = None
        self._label_widget: Static | None = None

    def compose(self) -> ComposeResult:
        time_str = self._timestamp.strftime("%H:%M")
        self._label_widget = Static(
            f"[bold green]Assistant[/bold green]  [dim]{time_str}[/dim]",
            classes="assistant-label",
        )
        yield self._label_widget
        self._text_widget = Static("", classes="assistant-text")
        yield self._text_widget

    def add_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        call_id: str,
        *,
        is_subagent_tool: bool = False,
    ) -> ToolCallWidget:
        """Add a new tool call widget to this message."""
        widget = ToolCallWidget(
            tool_name=tool_name,
            args=args,
            call_id=call_id,
            is_subagent_tool=is_subagent_tool,
        )
        self._tool_widgets[call_id] = widget

        # Mount before text widget if it exists
        if self._text_widget is not None:
            self.mount(widget, before=self._text_widget)
        else:
            self.mount(widget)
        return widget

    def complete_tool_call(
        self,
        call_id: str,
        result: str,
        elapsed: float,
        error: bool = False,
    ) -> None:
        """Mark a tool call as completed."""
        widget = self._tool_widgets.get(call_id)
        if widget:
            widget.complete(result, elapsed, error)

    def append_text(self, delta: str) -> None:
        """Append streaming text delta — renders immediately for real-time feel."""
        self._text += delta
        self._render_text()

    def finalize_text(self) -> None:
        """Final render — called when streaming is done."""
        self._render_text()

    def _render_text(self) -> None:
        """Re-render the accumulated text as Markdown."""
        if self._text_widget is None:
            return
        text = self._text.strip()
        if text:
            self._text_widget.update(Markdown(text))
        else:
            self._text_widget.update("")

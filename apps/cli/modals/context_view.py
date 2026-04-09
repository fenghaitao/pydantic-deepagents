"""Context usage modal — /context command."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from apps.cli.widgets.status_bar import _context_bar, _format_tokens


class ContextViewModal(ModalScreen[str | None]):
    """Shows context window usage with progress bar, stats, and compact button."""

    DEFAULT_CSS = """
    ContextViewModal {
        align: center middle;
    }
    ContextViewModal > #ctx-container {
        width: 55;
        height: auto;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    ContextViewModal > #ctx-container > Button {
        margin: 1 0 0 0;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    def __init__(
        self,
        pct: float = 0.0,
        current: int = 0,
        maximum: int = 0,
        message_count: int = 0,
    ) -> None:
        super().__init__()
        self._pct = pct
        self._current = current
        self._max = maximum
        self._msg_count = message_count

    def compose(self) -> ComposeResult:
        threshold = int(self._max * 0.9) if self._max else 0

        with Vertical(id="ctx-container"):
            yield Static("[bold]Context Usage[/bold]\n")
            yield Static(f"  {_context_bar(self._pct, width=24)}\n")
            yield Static(
                f"  Current tokens:   {_format_tokens(self._current)}\n"
                f"  Max tokens:       {_format_tokens(self._max)}\n"
                f"  Compression at:   90% ({_format_tokens(threshold)} tokens)\n"
                f"  Messages:         {self._msg_count}"
            )

            if self._pct >= 0.7:
                yield Button("Compact now", variant="warning", id="btn-compact")
            else:
                yield Button("Compact now", variant="default", id="btn-compact")

            yield Static("\n[dim]Esc to close[/dim]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-compact":
            self.dismiss("compact")

    def action_dismiss(self) -> None:
        self.dismiss(None)

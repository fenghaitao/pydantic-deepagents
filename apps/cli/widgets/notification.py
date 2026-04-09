"""Toast notification system — non-blocking notifications in the top-right."""

from __future__ import annotations

# Uses Textual's built-in notify() system.
# We provide typed helpers so the app can call:
#   self.notify_info("...")
#   self.notify_success("...")
#   self.notify_warning("...")
#   self.notify_error("...")


def notify_info(app: object, message: str) -> None:
    """Show an info notification."""
    app.notify(message, severity="information", timeout=4)


def notify_success(app: object, message: str) -> None:
    """Show a success notification."""
    app.notify(message, severity="information", timeout=4)


def notify_warning(app: object, message: str) -> None:
    """Show a warning notification."""
    app.notify(message, severity="warning", timeout=5)


def notify_error(app: object, message: str) -> None:
    """Show an error notification."""
    app.notify(message, severity="error", timeout=6)

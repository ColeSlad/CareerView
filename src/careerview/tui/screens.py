from __future__ import annotations

from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from careerview.models import Listing


def _format_date(ts: int | None) -> str:
    if not ts:
        return "?"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class DetailScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss_screen", "Close"), ("enter", "dismiss_screen", "Close")]

    CSS = """
    DetailScreen {
        align: center middle;
    }
    #detail-box {
        background: $panel;
        border: thick $primary;
        padding: 1 2;
        width: 80%;
        max-width: 100;
        height: auto;
    }
    """

    def __init__(self, listing: Listing, status: str, note: str | None) -> None:
        super().__init__()
        self.listing = listing
        self.status = status
        self.note = note

    def compose(self) -> ComposeResult:
        listing = self.listing
        lines = [
            f"[b]{listing.company}[/b] — {listing.title}",
            "",
            f"Status:      {self.status.capitalize()}",
            f"Source:      {listing.source}",
            f"Category:    {listing.category}",
            f"Locations:   {', '.join(listing.locations) or '?'}",
            f"Terms:       {', '.join(listing.terms) or '?'}",
            f"Posted:      {_format_date(listing.date_posted)}",
            f"First seen:  {_format_date(listing.first_seen)}",
            f"URL:         {listing.url}",
            "",
            f"Note: {self.note or '(none — press n to add one)'}",
            "",
            "[dim]Escape or Enter to close[/dim]",
        ]
        with Vertical(id="detail-box"):
            yield Static("\n".join(lines))

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)


class NoteScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "Cancel")]

    CSS = """
    NoteScreen {
        align: center middle;
    }
    #note-box {
        background: $panel;
        border: thick $primary;
        padding: 1 2;
        width: 60%;
        max-width: 80;
        height: auto;
    }
    """

    def __init__(self, initial: str) -> None:
        super().__init__()
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="note-box"):
            yield Static("Note (Enter to save, Escape to cancel):")
            yield Input(value=self.initial, id="note-input")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)

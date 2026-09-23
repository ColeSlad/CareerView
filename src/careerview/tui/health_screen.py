from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from careerview import health, store


class HealthScreen(ModalScreen[None]):
    BINDINGS = [("escape", "dismiss_screen", "Close"), ("h", "dismiss_screen", "Close"),
                ("r", "refresh_health", "Sync"), ("/", "focus_search", "Search")]
    CSS = """
    HealthScreen { align: center middle; }
    #health-box { width: 95%; height: 95%; background: $panel; border: thick $primary; padding: 0 1; }
    #health-title { height: 1; text-style: bold; }
    #health-summary { height: auto; }
    #health-summary.warning { color: $warning; }
    #health-search { height: 3; }
    #health-sources { height: 1fr; min-height: 3; }
    #health-source-detail { height: auto; max-height: 6; overflow-y: auto; }
    #health-help { height: 1; color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="health-box"):
            yield Static("Polling health", id="health-title")
            yield Static("", id="health-summary", markup=False)
            yield Input(placeholder="Search company or source... (/)", id="health-search")
            yield DataTable(id="health-sources", cursor_type="row", zebra_stripes=True)
            yield Static("", id="health-source-detail", markup=False)
            yield Static("Failures first | r Sync saved results | / Search | Esc Close", id="health-help")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Status", "Company / feed", "Source", "Listings", "Last success", "Fetch time")
        self.refresh_health()
        table.focus()
        self.set_interval(30, self.update_summary)

    def update_summary(self) -> None:
        config = self.app.config
        meta = self.app.poll_meta
        now = store.now_ts()
        widget = self.query_one("#health-summary", Static)
        message = health.details(meta, now, config.poll_cadence_minutes, config.poll_stale_after_minutes)
        if self.app.sync_error:
            message += "\nSync failed: showing the local snapshot. Press r to retry."
        widget.update(message)
        widget.set_class(bool(self.app.sync_error) or health.needs_attention(
            meta, now, config.poll_stale_after_minutes), "warning")

    def refresh_health(self) -> None:
        self.update_summary()
        table = self.query_one(DataTable)
        table.clear()
        query = self.query_one(Input).value
        now = store.now_ts()
        for row in health.sorted_sources(self.app.poll_meta, query):
            table.add_row(
                Text("FAILED" if row["error"] else "OK", style="bold red" if row["error"] else "green"),
                Text(row["company"]), Text(row["source"]),
                "—" if row["listing_count"] is None else str(row["listing_count"]),
                health.age(row["last_success_at"], now), f"{row['duration_seconds']:.1f}s", key=row["key"],
            )
        if not table.row_count:
            message = "No matching sources." if self.app.poll_meta.get("poll_health") else "No per-source history yet."
            self.query_one("#health-source-detail", Static).update(message)
        else:
            self.show_source(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    def show_source(self, key: str) -> None:
        row = next((row for row in self.app.poll_meta.get("poll_health", {}).get("sources", [])
                    if row["key"] == key), None)
        if row is None:
            return
        now = store.now_ts()
        self.query_one("#health-source-detail", Static).update(
            f"{row['company']} | {row['key']}\n"
            f"Last check: {health.timestamp_label(row['checked_at'], now)} | "
            f"Last success: {health.timestamp_label(row['last_success_at'], now)}\n"
            + (f"{row['error']} | {row['consecutive_failures']} consecutive failure(s)"
               if row["error"] else "Fetch succeeded. Zero listings is a valid result.")
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        self.show_source(event.row_key.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.refresh_health()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.query_one(DataTable).focus()

    def action_focus_search(self) -> None:
        self.query_one(Input).focus()

    def action_refresh_health(self) -> None:
        self.app.action_refresh_now()
        self.refresh_health()

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

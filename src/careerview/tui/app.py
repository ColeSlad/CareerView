from __future__ import annotations

import subprocess
import time
import webbrowser

from textual.app import App, ComposeResult
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Footer, Header, Input, Static

from careerview import status_store, store
from careerview.config import load_config
from careerview.filters import locations_pass, title_matches
from careerview.tui.screens import DetailScreen, NoteScreen

STATUS_CYCLE = ("all", "new", "interested", "applied", "skipped")


def _relative_time(ts: int | None, now: int) -> str:
    if not ts:
        return "?"
    delta = now - ts
    if delta < 0:
        return "future"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    if delta < 86400 * 30:
        return f"{delta // 86400}d ago"
    if delta < 86400 * 365:
        return f"{delta // (86400 * 30)}mo ago"
    return f"{delta // (86400 * 365)}y ago"


def _is_recent(first_seen: int | None, now: int, window: int = 48 * 3600) -> bool:
    return bool(first_seen and (now - first_seen) <= window)


class CareerViewApp(App):
    CSS = """
    #search { dock: top; height: 3; }
    #filter-line { dock: top; height: 1; color: $text-muted; padding: 0 1; }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        ("o", "open_url", "Open"),
        ("a", "mark_applied", "Applied"),
        ("i", "mark_interested", "Interested"),
        ("s", "mark_skipped", "Skip"),
        ("n", "edit_note", "Note"),
        ("/", "focus_search", "Search"),
        ("1", "toggle_active", "Active"),
        ("2", "toggle_relevant", "Relevant"),
        ("3", "toggle_us_remote", "US/Remote"),
        ("4", "cycle_status_filter", "Status"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.db = status_store.connect()
        self.listings: dict = {}
        self.statuses: dict = {}
        self.search_text = ""
        self.active_only = True
        self.relevant_only = True
        self.us_remote_only = True
        self.status_filter = "all"
        self._visible_uids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search company or title... (press / to focus)", id="search")
        yield Static("", id="filter-line")
        yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._git_pull_best_effort()
        self.listings = store.load_listings()
        self.statuses = status_store.load_all(self.db)

        table = self.query_one(DataTable)
        table.add_columns("Posted", "Status", "New", "Company", "Role", "Location", "Term", "Source")
        self.refresh_table()
        table.focus()

    def _git_pull_best_effort(self) -> None:
        try:
            result = subprocess.run(
                ["git", "pull", "--quiet"], capture_output=True, timeout=20, check=False, text=True
            )
            if result.returncode != 0:
                self.notify(f"git pull failed, showing local data: {result.stderr.strip()[:200]}", severity="warning")
        except Exception as exc:
            self.notify(f"git pull failed, showing local data: {exc}", severity="warning")

    def _matching_uids(self) -> list[str]:
        search = self.search_text.lower().strip()
        relevance = self.config.relevance
        result = []
        for uid, listing in self.listings.items():
            if self.active_only and not listing.active:
                continue
            if self.relevant_only:
                if relevance.categories and listing.category not in relevance.categories:
                    continue
                if not title_matches(listing.title, relevance.include_title_keywords, relevance.exclude_title_keywords):
                    continue
            if self.us_remote_only and not locations_pass(listing, "us_remote"):
                continue
            record = self.statuses.get(uid)
            current_status = record.status if record else "new"
            if self.status_filter != "all" and current_status != self.status_filter:
                continue
            if search and search not in listing.company.lower() and search not in listing.title.lower():
                continue
            result.append(uid)
        result.sort(key=lambda u: self.listings[u].date_posted or self.listings[u].first_seen or 0, reverse=True)
        return result

    def refresh_table(self) -> None:
        table = self.query_one(DataTable)
        previous_uid = self._current_uid()
        self._visible_uids = self._matching_uids()
        table.clear()
        now = int(time.time())
        for uid in self._visible_uids:
            listing = self.listings[uid]
            record = self.statuses.get(uid)
            status_label = (record.status if record else "new").capitalize()
            new_badge = "NEW" if _is_recent(listing.first_seen, now) else ""
            table.add_row(
                _relative_time(listing.date_posted, now),
                status_label,
                new_badge,
                listing.company,
                listing.title,
                ", ".join(listing.locations) or "?",
                ", ".join(listing.terms) or "-",
                listing.source,
                key=uid,
            )
        self._update_filter_line()
        if previous_uid and previous_uid in self._visible_uids:
            table.cursor_coordinate = Coordinate(self._visible_uids.index(previous_uid), 0)

    def _update_filter_line(self) -> None:
        line = self.query_one("#filter-line", Static)
        parts = [
            f"[1] Active:{'ON' if self.active_only else 'off'}",
            f"[2] Relevant:{'ON' if self.relevant_only else 'off'}",
            f"[3] US/Remote:{'ON' if self.us_remote_only else 'off'}",
            f"[4] Status:{self.status_filter}",
            f"({len(self._visible_uids)} shown)",
        ]
        line.update("  ".join(parts))

    def _current_uid(self) -> str | None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._visible_uids):
            return self._visible_uids[row]
        return None

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.search_text = event.value
            self.refresh_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        uid = event.row_key.value
        if not uid or uid not in self.listings:
            return
        listing = self.listings[uid]
        record = self.statuses.get(uid)
        status_value = record.status if record else "new"
        note = record.note if record else None
        self.push_screen(DetailScreen(listing, status_value, note))

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_toggle_active(self) -> None:
        self.active_only = not self.active_only
        self.refresh_table()

    def action_toggle_relevant(self) -> None:
        self.relevant_only = not self.relevant_only
        self.refresh_table()

    def action_toggle_us_remote(self) -> None:
        self.us_remote_only = not self.us_remote_only
        self.refresh_table()

    def action_cycle_status_filter(self) -> None:
        idx = STATUS_CYCLE.index(self.status_filter)
        self.status_filter = STATUS_CYCLE[(idx + 1) % len(STATUS_CYCLE)]
        self.refresh_table()

    def action_open_url(self) -> None:
        uid = self._current_uid()
        if uid and self.listings[uid].url:
            webbrowser.open(self.listings[uid].url)

    def action_mark_applied(self) -> None:
        self._set_status("applied")

    def action_mark_interested(self) -> None:
        self._set_status("interested")

    def action_mark_skipped(self) -> None:
        self._set_status("skipped")

    def _set_status(self, status: str) -> None:
        uid = self._current_uid()
        if not uid:
            return
        status_store.set_status(self.db, uid, status)
        self.statuses = status_store.load_all(self.db)
        self.refresh_table()

    def action_edit_note(self) -> None:
        uid = self._current_uid()
        if not uid:
            return
        record = self.statuses.get(uid)
        initial = record.note if record and record.note else ""

        def handle_result(result: str | None) -> None:
            if result is not None:
                status_store.set_note(self.db, uid, result)
                self.statuses = status_store.load_all(self.db)
                self.refresh_table()

        self.push_screen(NoteScreen(initial), handle_result)


def run() -> None:
    CareerViewApp().run()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import DataTable, Input, Static

from careerview import status_store
from careerview.config import load_config
from careerview.inbox import Inbox
from careerview.models import Listing
from careerview.tui.app import CareerViewApp
from careerview.tui.screens import DetailScreen


ROOT = Path(__file__).resolve().parents[1]


def listing(uid, *, company="Acme", first_seen=None):
    return Listing(
        uid=uid,
        source="test",
        company=company,
        title="Software Engineering Intern",
        category="Software",
        locations=["Remote"],
        terms=["Summer 2027"],
        url=f"https://example.invalid/{uid}",
        first_seen=first_seen,
    )


class TuiInboxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = status_store.connect(Path(self.temp.name) / "status.db")
        self.addCleanup(self.db.close)
        self.listings = {"existing": listing("existing", first_seen=100)}
        config = load_config(ROOT / "config.yaml", ROOT / "companies.yaml")
        for mock in (
            patch("careerview.tui.app.status_store.connect", return_value=self.db),
            patch("careerview.tui.app.load_config", return_value=config),
            patch("careerview.tui.app.store.load_listings", side_effect=lambda: self.listings.copy()),
            patch.object(CareerViewApp, "_git_pull_best_effort"),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    async def test_first_visit_refresh_and_relaunch(self):
        app = CareerViewApp()
        async with app.run_test(size=(140, 35)) as pilot:
            self.assertEqual(app.inbox.new_uids, set())
            self.assertEqual(app.query_one(DataTable).row_count, 1)
            self.listings["arrival"] = listing("arrival", first_seen=1)
            await pilot.press("r", "5")
            self.assertEqual(app.inbox_filter, "new")
            self.assertEqual(app._visible_uids, ["arrival"])
            self.assertEqual(app.query_one(DataTable).get_row("arrival")[0], "New")
            await pilot.press("r")
            self.assertEqual(app._visible_uids, ["arrival"])
        self.listings["later"] = listing("later")
        next_visit = CareerViewApp()
        async with next_visit.run_test(size=(140, 35)) as pilot:
            await pilot.press("5")
            self.assertEqual(next_visit._visible_uids, ["later"])
            await pilot.press("5")
            self.assertEqual(set(next_visit._visible_uids), {"arrival", "later"})

    async def test_details_mark_reviewed_without_changing_application_status(self):
        Inbox(self.db).observe(["existing"])
        self.listings["arrival"] = listing("arrival")
        app = CareerViewApp()
        async with app.run_test(size=(140, 35)) as pilot:
            await pilot.press("5", "5", "enter")
            self.assertIsInstance(app.screen, DetailScreen)
            self.assertEqual(app.screen.listing.uid, "arrival")
            self.assertEqual(app.inbox.unread_uids, set())
            self.assertEqual(status_store.load_all(self.db), {})
            await pilot.press("escape")
            self.assertEqual(app.query_one(DataTable).row_count, 0)
            await pilot.press("5", "5")
            self.assertEqual(app._visible_uids, ["arrival"])
            self.assertEqual(app.query_one(DataTable).get_row("arrival")[0], "New · read")

    async def test_mark_shown_respects_search_and_preserves_hidden_unread(self):
        Inbox(self.db).observe(["existing"])
        self.listings["acme"] = listing("acme")
        self.listings["other"] = listing("other", company="Other")
        app = CareerViewApp()
        async with app.run_test(size=(140, 35)) as pilot:
            await pilot.press("5", "5")
            app.query_one(Input).value = "Acme"
            await pilot.pause()
            self.assertEqual(app._visible_uids, ["acme"])
            self.assertIn("1 unread", str(app.query_one("#inbox-line", Static).render()))
            await pilot.press("M")
            self.assertEqual(app.inbox.unread_uids, {"other"})
            self.assertEqual(app.query_one(DataTable).row_count, 0)
            self.assertEqual(status_store.load_all(self.db), {})
            app.query_one(Input).value = ""
            await pilot.pause()
            self.assertEqual(app._visible_uids, ["other"])
            await pilot.press("m")
            self.assertEqual(app.inbox.unread_uids, set())

    async def test_apply_action_updates_both_status_and_review_state(self):
        Inbox(self.db).observe(["existing"])
        self.listings["arrival"] = listing("arrival")
        app = CareerViewApp()
        async with app.run_test(size=(140, 35)) as pilot:
            await pilot.press("5", "5", "a")
            self.assertEqual(status_store.load_all(self.db)["arrival"].status, "applied")
            self.assertEqual(app.inbox.unread_uids, set())
            self.assertEqual(app.query_one(DataTable).row_count, 0)

    async def test_details_do_not_apply_actions_to_the_next_unread_listing(self):
        Inbox(self.db).observe(["existing"])
        self.listings["arrival"] = listing("arrival", first_seen=2)
        self.listings["other"] = listing("other", first_seen=1)
        app = CareerViewApp()
        async with app.run_test(size=(140, 35)) as pilot:
            await pilot.press("5", "5", "enter")
            self.assertEqual(app.screen.listing.uid, "arrival")
            self.assertEqual(app._visible_uids, ["other"])
            await pilot.press("a")
            self.assertEqual(status_store.load_all(self.db), {})
            self.assertEqual(app.inbox.unread_uids, {"other"})
            await pilot.press("escape", "a")
            statuses = status_store.load_all(self.db)
            self.assertEqual(set(statuses), {"other"})
            self.assertEqual(statuses["other"].status, "applied")

    async def test_search_typing_does_not_invoke_review_shortcuts(self):
        Inbox(self.db).observe(["existing"])
        self.listings["arrival"] = listing("arrival")
        app = CareerViewApp()
        async with app.run_test() as pilot:
            await pilot.press("/", "m", "M", "5")
            self.assertEqual(app.query_one(Input).value, "mM5")
            self.assertEqual(app.inbox.unread_uids, {"arrival"})
            self.assertEqual(app.inbox_filter, "all")


if __name__ == "__main__":
    unittest.main()

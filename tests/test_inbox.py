import tempfile
import unittest
from pathlib import Path

from careerview import status_store
from careerview.inbox import Inbox


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "status.db"
        self.db = status_store.connect(self.path)
        self.addCleanup(self.db.close)

    def test_first_nonempty_snapshot_is_a_reviewed_baseline(self):
        inbox = Inbox(self.db)
        inbox.observe([])
        inbox.observe(["existing"])
        self.assertEqual(inbox.new_uids, set())
        self.assertEqual(inbox.unread_uids, set())
        inbox.observe(["existing", "arrival"])
        self.assertEqual(inbox.new_uids, {"arrival"})
        self.assertEqual(inbox.unread_uids, {"arrival"})

    def test_new_arrivals_persist_as_unread_across_visits(self):
        first = Inbox(self.db)
        first.observe(["existing"])
        first.observe(["existing", "arrival"])
        with status_store.connect(self.path) as reopened:
            self.addCleanup(reopened.close)
            second = Inbox(reopened)
            second.observe(["existing", "arrival", "later"])
            self.assertEqual(second.new_uids, {"later"})
            self.assertEqual(second.unread_uids, {"arrival", "later"})
            self.assertEqual(second.mark_reviewed(["arrival", "arrival", "absent"]), 1)
        third = Inbox(self.db)
        third.observe(["existing", "arrival", "later"])
        self.assertEqual(third.new_uids, set())
        self.assertEqual(third.unread_uids, {"later"})

    def test_refresh_preserves_visit_markers_and_review_state(self):
        Inbox(self.db).observe(["existing"])
        inbox = Inbox(self.db)
        inbox.observe(["existing", "arrival"])
        inbox.mark_reviewed(["arrival"])
        inbox.observe(["existing", "arrival", "later"])
        self.assertEqual(inbox.new_uids, {"arrival", "later"})
        self.assertEqual(inbox.unread_uids, {"later"})

    def test_disappearing_listings_retain_their_history(self):
        first = Inbox(self.db)
        first.observe(["existing"])
        first.observe(["existing", "arrival"])
        first.observe([])
        self.assertEqual(first.new_uids, set())
        self.assertEqual(first.unread_uids, set())
        second = Inbox(self.db)
        second.observe(["existing", "arrival"])
        self.assertEqual(second.new_uids, set())
        self.assertEqual(second.unread_uids, {"arrival"})

    def test_review_history_does_not_change_statuses_or_notes(self):
        status_store.set_status(self.db, "existing", "applied")
        status_store.set_note(self.db, "existing", "Follow up next week")
        before = status_store.load_all(self.db)
        inbox = Inbox(self.db)
        inbox.observe(["existing"])
        inbox.observe(["existing", "arrival"])
        inbox.mark_reviewed(["existing", "arrival"])
        self.assertEqual(status_store.load_all(self.db), before)
        self.assertEqual(self.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()

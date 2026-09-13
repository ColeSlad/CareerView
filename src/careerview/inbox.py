from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable


class Inbox:
    """Local discovery and review history, independent of application status.

    Each instance represents one visit. Listing IDs, rather than posting dates,
    identify arrivals so late imports and missing dates still work.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS listing_reviews (
                    uid TEXT PRIMARY KEY,
                    reviewed_at INTEGER
                )
                """
            )
        self._known_at_visit: set[str] | None = None
        self.new_uids: set[str] = set()
        self.unread_uids: set[str] = set()

    def observe(self, uids: Iterable[str]) -> None:
        """Record a loaded snapshot without marking unread listings reviewed.

        The first nonempty snapshot establishes a baseline, avoiding an unread
        backlog on installation. Refreshes keep this visit's original baseline.
        History survives listings temporarily disappearing from the snapshot.
        """
        current = set(uids)
        with self.conn:
            reviews = dict(self.conn.execute("SELECT uid, reviewed_at FROM listing_reviews"))
            if self._known_at_visit is None and (reviews or current):
                self._known_at_visit = set(reviews) if reviews else current.copy()
            reviewed_at = int(time.time()) if not reviews else None
            self.conn.executemany(
                "INSERT OR IGNORE INTO listing_reviews (uid, reviewed_at) VALUES (?, ?)",
                ((uid, reviewed_at) for uid in current - reviews.keys()),
            )
            self.unread_uids = {
                uid
                for (uid,) in self.conn.execute("SELECT uid FROM listing_reviews WHERE reviewed_at IS NULL")
                if uid in current
            }
        self.new_uids = current - (self._known_at_visit or set())

    def mark_reviewed(self, uids: Iterable[str]) -> int:
        to_review = set(uids) & self.unread_uids
        now = int(time.time())
        with self.conn:
            self.conn.executemany(
                "UPDATE listing_reviews SET reviewed_at = ? WHERE uid = ? AND reviewed_at IS NULL",
                ((now, uid) for uid in to_review),
            )
        self.unread_uids.difference_update(to_review)
        return len(to_review)

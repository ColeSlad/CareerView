from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "careerview" / "status.db"

STATUSES = ("new", "interested", "applied", "skipped")


@dataclass
class StatusRecord:
    uid: str
    status: str
    note: str | None
    applied_at: int | None
    updated_at: int | None


def connect(path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS statuses (
            uid TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'new',
            note TEXT,
            applied_at INTEGER,
            updated_at INTEGER
        )
        """
    )
    conn.commit()
    return conn


def load_all(conn: sqlite3.Connection) -> dict[str, StatusRecord]:
    rows = conn.execute("SELECT uid, status, note, applied_at, updated_at FROM statuses").fetchall()
    return {row[0]: StatusRecord(*row) for row in rows}


def set_status(conn: sqlite3.Connection, uid: str, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    now = int(time.time())
    existing = conn.execute("SELECT applied_at FROM statuses WHERE uid = ?", (uid,)).fetchone()
    applied_at = existing[0] if existing else None
    if status == "applied" and not applied_at:
        applied_at = now
    conn.execute(
        """
        INSERT INTO statuses (uid, status, applied_at, updated_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(uid) DO UPDATE SET
            status = excluded.status,
            applied_at = excluded.applied_at,
            updated_at = excluded.updated_at
        """,
        (uid, status, applied_at, now),
    )
    conn.commit()


def set_note(conn: sqlite3.Connection, uid: str, note: str) -> None:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO statuses (uid, note, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(uid) DO UPDATE SET
            note = excluded.note,
            updated_at = excluded.updated_at
        """,
        (uid, note, now),
    )
    conn.commit()

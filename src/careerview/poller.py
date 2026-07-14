from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from careerview import store
from careerview.models import Listing
from careerview.sources.base import Source


@dataclass
class PollResult:
    all_listings: dict[str, Listing]
    new_listings: list[Listing]  # empty on the first run by design (silent seed)
    is_first_run: bool
    fetched_count: int


def dedup(listings: list[Listing]) -> list[Listing]:
    """Collapse the same req reported by multiple feeds, keeping the earliest-dated copy."""
    best: dict[str, Listing] = {}
    for listing in listings:
        key = listing.dedup_key()
        existing = best.get(key)
        if existing is None:
            best[key] = listing
            continue
        existing_ts = existing.date_posted or 0
        new_ts = listing.date_posted or 0
        if new_ts and (not existing_ts or new_ts < existing_ts):
            best[key] = listing
    return list(best.values())


def run_poll(sources: list[Source], listings_path: Path | str = store.DEFAULT_LISTINGS_PATH) -> PollResult:
    known = store.load_listings(listings_path)
    is_first_run = len(known) == 0

    fetched: list[Listing] = []
    for source in sources:
        fetched.extend(source.fetch())
    fetched = dedup(fetched)

    now = store.now_ts()
    merged: dict[str, Listing] = {}
    new_listings: list[Listing] = []

    for listing in fetched:
        prior = known.get(listing.uid)
        if prior is None:
            listing.first_seen = now
            listing.emailed = is_first_run
            if not is_first_run:
                new_listings.append(listing)
        else:
            listing.first_seen = prior.first_seen
            listing.emailed = prior.emailed
        merged[listing.uid] = listing

    return PollResult(
        all_listings=merged,
        new_listings=new_listings,
        is_first_run=is_first_run,
        fetched_count=len(fetched),
    )

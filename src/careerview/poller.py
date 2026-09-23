from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, urlsplit

from careerview import store
from careerview.health import SourceCheck, error_summary, source_identity
from careerview.models import Listing
from careerview.sources.base import Source, fetch_with_retry


@dataclass
class PollResult:
    all_listings: dict[str, Listing]
    new_listings: list[Listing]  # empty on the first run by design (silent seed)
    is_first_run: bool
    fetched_count: int
    source_checks: list[SourceCheck] = field(default_factory=list)
    started_at: int = 0
    finished_at: int = 0
    duration_seconds: float = 0
    retained_uids: set[str] = field(default_factory=set)


def _job_identity(listing: Listing) -> str | None:
    """Recognize the same ATS posting linked by different community feeds."""
    url = urlsplit(listing.url)
    host = (url.hostname or "").lower()
    parts = url.path.strip("/").split("/")
    if host in {"jobs.ashbyhq.com", "jobs.lever.co", "jobs.eu.lever.co"} and len(parts) >= 2:
        # /company/id and /company/id/application or /apply are the same job;
        # query parameters such as embed=true do not identify a different role.
        return f"{host}:{parts[0].casefold()}:{parts[1]}"
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io"}:
        region = "eu" if ".eu." in host else "us"
        if len(parts) >= 3 and parts[-2] == "jobs" and parts[-1].isdigit():
            return f"greenhouse:{region}:{parts[-1]}"
        if url.path == "/embed/job_app":
            token = parse_qs(url.query).get("token", [""])[0]
            if token.isdigit():
                return f"greenhouse:{region}:{token}"
    return None


def dedup(listings: list[Listing]) -> list[Listing]:
    """Collapse copies of a posting, retaining distinct ATS requisition IDs."""
    best: dict[str, Listing] = {}
    for listing in listings:
        key = _job_identity(listing) or f"text:{listing.dedup_key()}"
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
    started_at = store.now_ts()
    started = monotonic()
    known = store.load_listings(listings_path)
    is_first_run = len(known) == 0
    known_by_posting: dict[str, Listing] = {}
    for prior in known.values():
        identity = _job_identity(prior)
        if identity and (identity not in known_by_posting or prior.emailed):
            known_by_posting[identity] = prior

    def fetch_source(source: Source) -> tuple[list[Listing], SourceCheck]:
        label, company, board = source_identity(source)
        source_started = monotonic()
        error = None
        try:
            source_listings = fetch_with_retry(source)
        except Exception as exc:
            error = error_summary(exc)
            print(f"  warning: {label} fetch failed, skipping ({error})", flush=True)
            source_listings = []
        else:
            print(f"  {label}: {len(source_listings)} listings", flush=True)
        return source_listings, SourceCheck(
            key=label, company=company, source=source.name, board=board,
            checked_at=store.now_ts(), duration_seconds=round(monotonic() - source_started, 3),
            listing_count=None if error else len(source_listings), error=error,
        )

    fetched: list[Listing] = []
    checks: list[SourceCheck] = []
    # Preserve configured source order for deterministic deduplication while
    # avoiding a serial request for every company in the expanded watchlist.
    with ThreadPoolExecutor(max_workers=8) as pool:
        for source_listings, check in pool.map(fetch_source, sources):
            fetched.extend(source_listings)
            checks.append(check)
    fetched = dedup(fetched)

    now = store.now_ts()
    merged: dict[str, Listing] = {}
    new_listings: list[Listing] = []

    for listing in fetched:
        identity = _job_identity(listing)
        alias = known_by_posting.get(identity) if identity else None
        prior = known.get(listing.uid) or alias
        if prior is None:
            listing.first_seen = now
            listing.emailed = is_first_run
            if not is_first_run:
                new_listings.append(listing)
        else:
            listing.first_seen = prior.first_seen
            listing.emailed = prior.emailed or bool(alias and alias.emailed)
        merged[listing.uid] = listing

    # A failed fetch is not evidence that the source's listings disappeared.
    # Keep its last snapshot and alert history, but don't email stale rows.
    failed_prefixes = tuple(
        f"{source.name}:" + (f"{getattr(source, 'slug', getattr(source, 'tenant', ''))}:"
                            if hasattr(source, 'slug') or hasattr(source, 'tenant') else "")
        for source, check in zip(sources, checks) if check.error
    )
    fetched_identities = {_job_identity(listing) for listing in fetched}
    retained = set()
    for uid, listing in known.items():
        identity = _job_identity(listing)
        if (not sources or uid.startswith(failed_prefixes)) and uid not in merged:
            if identity is None or identity not in fetched_identities:
                merged[uid] = listing
                retained.add(uid)

    return PollResult(
        all_listings=merged,
        new_listings=new_listings,
        is_first_run=is_first_run,
        fetched_count=len(fetched),
        source_checks=checks,
        started_at=started_at,
        finished_at=store.now_ts(),
        duration_seconds=round(monotonic() - started, 3),
        retained_uids=retained,
    )

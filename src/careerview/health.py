"""Persisted polling diagnostics shared by the CLI and terminal UI."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

import httpx

from careerview.sources.base import Source


@dataclass
class SourceCheck:
    key: str
    company: str
    source: str
    board: str
    checked_at: int
    duration_seconds: float
    listing_count: int | None
    error: str | None = None


def source_identity(source: Source) -> tuple[str, str, str]:
    board = getattr(source, "slug", "")
    if hasattr(source, "tenant"):
        board = ":".join(str(getattr(source, attr)) for attr in ("tenant", "wd", "dc", "site")
                         if getattr(source, attr, None))
    elif hasattr(source, "repo"):
        board = f"{source.repo}@{source.branch}"
    board = board or getattr(source, "country", "feed")
    return f"{source.name}:{board}", getattr(source, "company_name", source.name.capitalize()), board


def error_summary(exc: Exception) -> str:
    # Request URLs can contain API credentials; never persist exception messages.
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "Request timed out after retry"
    if isinstance(exc, httpx.TransportError):
        return "Connection failed after retry"
    return f"{type(exc).__name__}: could not fetch or parse source"


def build_health(previous: dict, checks: list[SourceCheck], started_at: int,
                 finished_at: int, duration_seconds: float) -> dict:
    prior = previous.get("poll_health", {})
    prior_sources = {row["key"]: row for row in prior.get("sources", [])}
    rows = []
    for check in checks:
        old = prior_sources.get(check.key, {})
        rows.append({
            **asdict(check),
            "last_success_at": old.get("last_success_at") if check.error else check.checked_at,
            "consecutive_failures": old.get("consecutive_failures", 0) + 1 if check.error else 0,
        })
    failures = sum(row["error"] is not None for row in rows)
    status = "healthy"
    if not rows:
        status = "no_sources"
    elif failures:
        status = "failed" if failures == len(rows) else "partial"
    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "status": status,
        "last_success_at": finished_at if status == "healthy" else prior.get("last_success_at"),
        "sources": rows,
    }


def age(timestamp: int | None, now: int) -> str:
    if timestamp is None:
        return "not recorded"
    seconds = max(0, now - timestamp)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m ago"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h ago"


def timestamp_label(timestamp: int | None, now: int) -> str:
    if timestamp is None:
        return "not recorded"
    return f"{datetime.fromtimestamp(timestamp).astimezone():%Y-%m-%d %H:%M %Z} ({age(timestamp, now)})"


def is_stale(meta: dict, now: int, stale_minutes: int) -> bool:
    finished = meta.get("poll_health", {}).get("finished_at", meta.get("last_run"))
    return finished is not None and now - finished >= stale_minutes * 60


def needs_attention(meta: dict, now: int, stale_minutes: int) -> bool:
    health = meta.get("poll_health", {})
    return (is_stale(meta, now, stale_minutes) or health.get("status") != "healthy"
            or health.get("email_status") == "failed")


def summary(meta: dict, now: int, stale_minutes: int) -> str:
    health = meta.get("poll_health", {})
    last = health.get("finished_at", meta.get("last_run"))
    if not health:
        message = f"Health not recorded | Last saved poll: {age(last, now)}"
    else:
        rows = health.get("sources", [])
        failed = sum(row.get("error") is not None for row in rows)
        label = {"healthy": "Healthy", "partial": "Partial failure", "failed": "Poll failed",
                 "no_sources": "No sources checked"}.get(health.get("status"), "Unknown")
        message = f"{label} | Last poll: {age(last, now)} | {len(rows) - failed}/{len(rows)} sources OK"
        if failed:
            message += f" | {failed} failed"
        if health.get("email_status") == "failed":
            message += " | Email failed"
    return f"STALE — {message}" if is_stale(meta, now, stale_minutes) else message


def details(meta: dict, now: int, cadence_minutes: int, stale_minutes: int) -> str:
    health = meta.get("poll_health", {})
    lines = [summary(meta, now, stale_minutes),
             f"Last saved poll: {timestamp_label(health.get('finished_at', meta.get('last_run')), now)}",
             f"All sources last succeeded: {timestamp_label(health.get('last_success_at'), now)}",
             f"Target: every {cadence_minutes}m | Stale after {stale_minutes}m"
             + (f" | Fetch: {health['duration_seconds']:.1f}s" if health else "")]
    if not health:
        lines.append("Per-source results will appear after the next poll with health tracking enabled.")
    if is_stale(meta, now, stale_minutes):
        lines.append("Stale snapshot. Press r to sync; if still stale, check cloud runs.")
    if health.get("email_status") == "failed":
        lines.append("Email delivery failed; pending listings remain eligible for a later alert.")
    return "\n".join(lines)


def sorted_sources(meta: dict, search: str = "") -> list[dict]:
    rows = meta.get("poll_health", {}).get("sources", [])
    query = search.casefold().strip()
    return sorted((row for row in rows if query in
                   f"{row['company']} {row['source']} {row['board']}".casefold()),
                  key=lambda row: (row.get("error") is None, row["company"].casefold(), row["key"]))

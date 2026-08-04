from __future__ import annotations

import re
import time

import httpx

from careerview.filters import title_matches
from careerview.models import Listing
from careerview.sources.base import Source

_URL = "https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
_PAGE_SIZE = 20
_MAX_OFFSET = 500

_POSTED_RE = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.IGNORECASE)


def _parse_posted_on(text: str | None, now: int) -> int | None:
    """Workday only exposes a relative bucket like "Posted 30+ Days Ago", not an exact
    timestamp. "30+" is treated as exactly 30 (a floor), so we only ever understate
    a listing's age, never overstate its freshness."""
    if not text:
        return None
    match = _POSTED_RE.search(text)
    if not match:
        return None
    token = match.group(1).lower()
    if token == "today":
        return now
    if token == "yesterday":
        return now - 86400
    return now - int(match.group(2)) * 86400


class WorkdaySource(Source):
    """Workday's career-site search endpoint (the same JSON API the site's own frontend
    calls) only accepts one free-text search term at a time, so this queries once per
    include keyword and merges results by job path, then re-filters everything through
    the shared title_matches() for word-boundary precision."""

    name = "workday"

    def __init__(
        self,
        tenant: str,
        wd: str,
        site: str,
        company_name: str,
        include_keywords: list[str],
        exclude_keywords: list[str],
        timeout: float = 20.0,
    ):
        self.tenant = tenant
        self.wd = wd
        self.site = site
        self.company_name = company_name
        self.include_keywords = include_keywords
        self.exclude_keywords = exclude_keywords
        self.timeout = timeout

    def fetch(self) -> list[Listing]:
        url = _URL.format(tenant=self.tenant, wd=self.wd, site=self.site)
        postings_by_path: dict[str, dict] = {}

        for term in self.include_keywords or [""]:
            offset = 0
            while True:
                resp = httpx.post(
                    url,
                    json={"limit": _PAGE_SIZE, "offset": offset, "searchText": term},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                postings = resp.json().get("jobPostings", [])
                for posting in postings:
                    path = posting.get("externalPath")
                    if path:
                        postings_by_path[path] = posting
                if len(postings) < _PAGE_SIZE or offset > _MAX_OFFSET:
                    break
                offset += _PAGE_SIZE

        now = int(time.time())
        listings = []
        for path, posting in postings_by_path.items():
            title = posting.get("title", "")
            if not title_matches(title, self.include_keywords, self.exclude_keywords):
                continue

            listings.append(
                Listing(
                    uid=f"workday:{self.tenant}:{path}",
                    source=self.name,
                    company=self.company_name,
                    title=title,
                    category="Software",
                    locations=[posting["locationsText"]] if posting.get("locationsText") else [],
                    terms=[],
                    url=f"https://{self.tenant}.{self.wd}.myworkdayjobs.com/{self.site}{path}",
                    active=True,
                    date_posted=_parse_posted_on(posting.get("postedOn"), now),
                )
            )
        return listings

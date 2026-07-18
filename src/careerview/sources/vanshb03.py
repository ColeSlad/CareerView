from __future__ import annotations

import httpx

from careerview.models import Listing
from careerview.sources.base import Source

_RAW_URL = "https://raw.githubusercontent.com/{repo}/{branch}/.github/scripts/listings.json"


class Vanshb03Source(Source):
    """This feed has no `category` field (unlike Simplify/PittCSC) but is itself
    scoped to software/tech internships, so every listing is tagged "Software" to
    match the existing category relevance filter. It also uses `season` (e.g.
    "Summer") instead of `terms` (e.g. "Summer 2026") since it carries no year."""

    name = "vanshb03"

    def __init__(self, repo: str, branch: str, timeout: float = 20.0):
        self.repo = repo
        self.branch = branch
        self.timeout = timeout

    def fetch(self) -> list[Listing]:
        url = _RAW_URL.format(repo=self.repo, branch=self.branch)
        resp = httpx.get(url, timeout=self.timeout)
        resp.raise_for_status()
        raw = resp.json()

        listings = []
        for entry in raw:
            if not entry.get("is_visible", True):
                continue
            season = entry.get("season")
            listings.append(
                Listing(
                    uid=f"vanshb03:{entry['id']}",
                    source=self.name,
                    company=entry.get("company_name", ""),
                    title=entry.get("title", ""),
                    category="Software",
                    locations=entry.get("locations", []),
                    terms=[season] if season else [],
                    url=entry.get("url", ""),
                    sponsorship=entry.get("sponsorship"),
                    active=entry.get("active", True),
                    date_posted=entry.get("date_posted"),
                )
            )
        return listings

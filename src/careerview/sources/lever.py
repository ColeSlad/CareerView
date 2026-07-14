from __future__ import annotations

import httpx

from careerview.filters import title_matches
from careerview.models import Listing
from careerview.sources.base import Source

_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


class LeverSource(Source):
    name = "lever"

    def __init__(
        self,
        slug: str,
        company_name: str,
        include_keywords: list[str],
        exclude_keywords: list[str],
        timeout: float = 20.0,
    ):
        self.slug = slug
        self.company_name = company_name
        self.include_keywords = include_keywords
        self.exclude_keywords = exclude_keywords
        self.timeout = timeout

    def fetch(self) -> list[Listing]:
        resp = httpx.get(_URL.format(slug=self.slug), timeout=self.timeout)
        resp.raise_for_status()
        postings = resp.json()

        listings = []
        for posting in postings:
            title = posting.get("text", "")
            if not title_matches(title, self.include_keywords, self.exclude_keywords):
                continue

            categories = posting.get("categories", {})
            locations = categories.get("allLocations") or (
                [categories["location"]] if categories.get("location") else []
            )

            created_ms = posting.get("createdAt")
            date_posted = int(created_ms / 1000) if created_ms else None

            listings.append(
                Listing(
                    uid=f"lever:{self.slug}:{posting['id']}",
                    source=self.name,
                    company=self.company_name,
                    title=title,
                    category="Software",
                    locations=locations,
                    terms=[],
                    url=posting.get("applyUrl") or posting.get("hostedUrl", ""),
                    active=True,  # Lever's postings API only lists currently-open jobs
                    date_posted=date_posted,
                )
            )
        return listings

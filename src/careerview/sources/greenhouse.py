from __future__ import annotations

import httpx
from dateutil import parser as dateparser

from careerview.filters import title_matches
from careerview.models import Listing
from careerview.sources.base import Source

_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


class GreenhouseSource(Source):
    name = "greenhouse"

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
        jobs = resp.json().get("jobs", [])

        listings = []
        for job in jobs:
            title = job.get("title", "")
            if not title_matches(title, self.include_keywords, self.exclude_keywords):
                continue

            posted_raw = job.get("first_published") or job.get("updated_at")
            date_posted = int(dateparser.isoparse(posted_raw).timestamp()) if posted_raw else None

            location = job.get("location", {}).get("name", "")
            listings.append(
                Listing(
                    uid=f"greenhouse:{self.slug}:{job['id']}",
                    source=self.name,
                    company=job.get("company_name") or self.company_name,
                    title=title,
                    category="Software",
                    locations=[location] if location else [],
                    terms=[],
                    url=job.get("absolute_url", ""),
                    active=True,  # Greenhouse's board API only lists currently-open jobs
                    date_posted=date_posted,
                )
            )
        return listings

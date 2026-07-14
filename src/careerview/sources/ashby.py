from __future__ import annotations

import httpx
from dateutil import parser as dateparser

from careerview.filters import title_matches
from careerview.models import Listing
from careerview.sources.base import Source

_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


class AshbySource(Source):
    name = "ashby"

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

            locations = []
            if job.get("location"):
                locations.append(job["location"])
            for secondary in job.get("secondaryLocations") or []:
                loc = secondary.get("location") if isinstance(secondary, dict) else secondary
                if loc:
                    locations.append(loc)

            posted_raw = job.get("publishedAt")
            date_posted = int(dateparser.isoparse(posted_raw).timestamp()) if posted_raw else None

            listings.append(
                Listing(
                    uid=f"ashby:{self.slug}:{job['id']}",
                    source=self.name,
                    company=self.company_name,
                    title=title,
                    category="Software",
                    locations=locations,
                    terms=[],
                    url=job.get("applyUrl") or job.get("jobUrl", ""),
                    active=job.get("isListed", True),
                    date_posted=date_posted,
                )
            )
        return listings

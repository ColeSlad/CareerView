from __future__ import annotations

import httpx
from dateutil import parser as dateparser

from careerview.filters import title_matches
from careerview.models import Listing
from careerview.sources.base import Source

_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


class AdzunaSource(Source):
    name = "adzuna"

    def __init__(
        self,
        app_id: str,
        app_key: str,
        country: str,
        keywords: str,
        locations: list[str],
        include_keywords: list[str],
        exclude_keywords: list[str],
        results_per_page: int = 50,
        timeout: float = 20.0,
    ):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country
        self.keywords = keywords
        self.locations = locations
        self.include_keywords = include_keywords
        self.exclude_keywords = exclude_keywords
        self.results_per_page = results_per_page
        self.timeout = timeout

    def fetch(self) -> list[Listing]:
        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "what": self.keywords,
            "results_per_page": self.results_per_page,
            "content-type": "application/json",
        }
        if self.locations:
            params["where"] = self.locations[0]

        resp = httpx.get(_URL.format(country=self.country), params=params, timeout=self.timeout)
        resp.raise_for_status()
        results = resp.json().get("results", [])

        listings = []
        for job in results:
            title = job.get("title", "")
            if not title_matches(title, self.include_keywords, self.exclude_keywords):
                continue

            created_raw = job.get("created")
            date_posted = int(dateparser.isoparse(created_raw).timestamp()) if created_raw else None

            location_name = (job.get("location") or {}).get("display_name", "")
            listings.append(
                Listing(
                    uid=f"adzuna:{job['id']}",
                    source=self.name,
                    company=(job.get("company") or {}).get("display_name", ""),
                    title=title,
                    category="Software",
                    locations=[location_name] if location_name else [],
                    terms=[],
                    url=job.get("redirect_url", ""),
                    active=True,  # Adzuna search results only surface currently-live listings
                    date_posted=date_posted,
                )
            )
        return listings

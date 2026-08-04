from __future__ import annotations

import httpx
from dateutil import parser as dateparser

from careerview.filters import title_matches
from careerview.models import Listing
from careerview.sources.base import Source

_URL = "https://{tenant}.fa.{dc}.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
_PAGE_SIZE = 25
_MAX_OFFSET = 500


class OracleCloudSource(Source):
    """Oracle Fusion Recruiting Cloud's public candidate-experience REST API (the same
    one the company's careers site itself calls). Like Workday, it only supports one
    free-text keyword per request, so this queries once per include keyword and merges
    results by requisition id, then re-filters through the shared title_matches()."""

    name = "oraclecloud"

    def __init__(
        self,
        tenant: str,
        dc: str,
        site: str,
        company_name: str,
        include_keywords: list[str],
        exclude_keywords: list[str],
        timeout: float = 20.0,
    ):
        self.tenant = tenant
        self.dc = dc
        self.site = site
        self.company_name = company_name
        self.include_keywords = include_keywords
        self.exclude_keywords = exclude_keywords
        self.timeout = timeout

    def fetch(self) -> list[Listing]:
        url = _URL.format(tenant=self.tenant, dc=self.dc)
        reqs_by_id: dict[str, dict] = {}

        for term in self.include_keywords or [""]:
            offset = 0
            while True:
                finder = f"findReqs;siteNumber={self.site},limit={_PAGE_SIZE},offset={offset},keyword={term}"
                resp = httpx.get(
                    url,
                    params={
                        "onlyData": "true",
                        "expand": "requisitionList.secondaryLocations",
                        "finder": finder,
                    },
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                for req in data["items"][0].get("requisitionList", []):
                    reqs_by_id[req["Id"]] = req
                if not data.get("hasMore") or offset > _MAX_OFFSET:
                    break
                offset += _PAGE_SIZE

        listings = []
        for req_id, req in reqs_by_id.items():
            title = req.get("Title", "")
            if not title_matches(title, self.include_keywords, self.exclude_keywords):
                continue

            locations = [req["PrimaryLocation"]] if req.get("PrimaryLocation") else []
            for secondary in req.get("secondaryLocations") or []:
                loc = secondary.get("Name") if isinstance(secondary, dict) else secondary
                if loc:
                    locations.append(loc)

            posted_raw = req.get("PostedDate")
            date_posted = int(dateparser.isoparse(posted_raw).timestamp()) if posted_raw else None

            listings.append(
                Listing(
                    uid=f"oraclecloud:{self.tenant}:{req_id}",
                    source=self.name,
                    company=self.company_name,
                    title=title,
                    category="Software",
                    locations=locations,
                    terms=[],
                    url=f"https://{self.tenant}.fa.{self.dc}.oraclecloud.com/hcmUI/CandidateExperience/en/sites/{self.site}/job/{req_id}",
                    active=True,
                    date_posted=date_posted,
                )
            )
        return listings

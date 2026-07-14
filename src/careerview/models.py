from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass
class Listing:
    uid: str
    source: str
    company: str
    title: str
    category: str
    locations: list[str]
    terms: list[str]
    url: str
    sponsorship: str | None = None
    active: bool = True
    date_posted: int | None = None
    first_seen: int | None = None
    emailed: bool = False

    def dedup_key(self) -> str:
        """Cross-source key for collapsing the same role posted via multiple feeds.

        Includes location so postings that share a company+title but are genuinely
        different reqs (e.g. the same role open in five different cities) don't collapse.
        """
        norm_company = re.sub(r"[^a-z0-9]", "", self.company.lower())
        norm_title = re.sub(r"[^a-z0-9]", "", self.title.lower())
        norm_locations = ",".join(sorted(re.sub(r"[^a-z0-9]", "", loc.lower()) for loc in self.locations))
        return f"{norm_company}:{norm_title}:{norm_locations}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Listing":
        return cls(**data)

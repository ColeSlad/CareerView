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
        """Cross-source key for collapsing the same role posted via multiple feeds."""
        norm_company = re.sub(r"[^a-z0-9]", "", self.company.lower())
        norm_title = re.sub(r"[^a-z0-9]", "", self.title.lower())
        return f"{norm_company}:{norm_title}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Listing":
        return cls(**data)

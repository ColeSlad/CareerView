from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class RelevanceConfig:
    terms: list[str]
    categories: list[str]
    locations_mode: str
    include_title_keywords: list[str]
    exclude_title_keywords: list[str]


@dataclass
class Config:
    simplify_repo: str
    simplify_branch: str
    relevance: RelevanceConfig
    adzuna_country: str
    adzuna_keywords: str
    adzuna_locations: list[str]
    poll_cadence_minutes: int
    companies: dict[str, list[str]]


def load_config(
    config_path: Path | str = "config.yaml",
    companies_path: Path | str = "companies.yaml",
) -> Config:
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    with open(companies_path) as f:
        companies = yaml.safe_load(f) or {}

    relevance_raw = raw["relevance"]
    return Config(
        simplify_repo=raw["simplify"]["repo"],
        simplify_branch=raw["simplify"]["branch"],
        relevance=RelevanceConfig(
            terms=relevance_raw.get("terms", []),
            categories=relevance_raw.get("categories", []),
            locations_mode=relevance_raw.get("locations_mode", "all"),
            include_title_keywords=relevance_raw.get("include_title_keywords", []),
            exclude_title_keywords=relevance_raw.get("exclude_title_keywords", []),
        ),
        adzuna_country=raw["adzuna"]["country"],
        adzuna_keywords=raw["adzuna"]["keywords"],
        adzuna_locations=raw["adzuna"].get("locations", []),
        poll_cadence_minutes=raw["poll"]["cadence_minutes"],
        companies=companies,
    )

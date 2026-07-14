from __future__ import annotations

import re

from careerview.config import RelevanceConfig
from careerview.models import Listing

_US_STATE_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}


def _is_us_or_remote(location: str) -> bool:
    loc = location.lower()
    if "remote" in loc:
        return True
    if "united states" in loc or "usa" in loc or loc.strip() == "us":
        return True
    match = re.search(r",\s*([a-zA-Z]{2})$", location.strip())
    return bool(match and match.group(1).upper() in _US_STATE_ABBR)


def _locations_pass(listing: Listing, mode: str) -> bool:
    if mode == "all":
        return True
    if not listing.locations:
        return True  # unknown location: don't silently drop a real opportunity
    return any(_is_us_or_remote(loc) for loc in listing.locations)


def _contains_word(text: str, keyword: str) -> bool:
    """Word-boundary match so e.g. 'intern' doesn't false-positive on 'Internal'/
    'International', and 'coop' doesn't match inside 'Cooperative'."""
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def title_matches(title: str, include_keywords: list[str], exclude_keywords: list[str]) -> bool:
    """Shared intern-title heuristic, used both for post-fetch relevance and for ATS
    adapters filtering a company's full job board down to internship-shaped titles."""
    t = title.lower()
    if exclude_keywords and any(_contains_word(t, kw) for kw in exclude_keywords):
        return False
    if include_keywords and not any(_contains_word(t, kw) for kw in include_keywords):
        return False
    return True


def is_relevant(listing: Listing, relevance: RelevanceConfig) -> bool:
    if not listing.active:
        return False

    if relevance.categories and listing.category not in relevance.categories:
        return False

    if listing.terms and relevance.terms:
        if not set(listing.terms) & set(relevance.terms):
            return False

    if not title_matches(listing.title, relevance.include_title_keywords, relevance.exclude_title_keywords):
        return False

    return _locations_pass(listing, relevance.locations_mode)

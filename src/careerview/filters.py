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

# Boards and community feeds often omit the state/country for major US hubs.
# Match complete location segments so names such as London or Toronto stay out.
_US_CITY_NAMES = {
    "san francisco", "sf", "sf bay area", "san francisco bay area", "bay area",
    "new york", "new york city", "nyc", "manhattan", "brooklyn",
    "seattle", "bellevue", "redmond", "boston", "cambridge, ma",
    "san jose", "palo alto", "menlo park", "mountain view", "sunnyvale",
    "san mateo", "redwood city", "cupertino", "santa clara", "foster city",
    "los angeles", "san diego", "irvine", "santa monica",
    "austin", "dallas", "houston", "san antonio", "chicago", "denver",
    "boulder", "atlanta", "pittsburgh", "philadelphia", "washington, dc",
    "washington, d.c.", "washington dc", "washington d.c.", "raleigh",
    "durham", "charlotte", "miami", "salt lake city", "minneapolis",
    "detroit", "phoenix", "scottsdale", "madison", "ann arbor",
}

_US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
}

_SOFTWARE_ROLE = re.compile(
    r"\b(software|programmer|developer|full[- ]?stack|front[- ]?end|back[- ]?end|"
    r"devops|devsecops|sre|firmware|embedded|machine learning|artificial intelligence|"
    r"ai|ml|data (?:science|scientist|engineering|engineer)|computer (?:vision|science)|"
    r"cybersecurity|security engineer(?:ing)?|quantitative (?:research|development)|"
    r"test automation)\b", re.IGNORECASE,
)
_NON_SOFTWARE_ROLE = re.compile(
    r"\b(marketing|sales|revenue enablement|accounting|finance|financial analyst|"
    r"legal|human resources|recruiting|recruitment|talent|communications|public relations|"
    r"supply chain|procurement|buyer|logistics|manufacturing|mechanical|electrical|"
    r"power electronics|hardware|pcb|cad|ewis|propulsion|warhead|aerodynamics|"
    r"structural|chemical|civil|construction|facilities|business operations|"
    r"product manage(?:ment|r)|program manage(?:ment|r)|product design|game design|"
    r"level design|graphic design|tech(?:nical)? art|ux|industrial design)\b", re.IGNORECASE,
)


def internship_category(title: str, department: str = "") -> str:
    """Exclude clearly non-software internships; retain ambiguous engineering roles.

    Explicit software titles take precedence over business-unit names, so a
    Software Engineering Intern on a Finance team is still eligible.
    """
    if _SOFTWARE_ROLE.search(title):
        return "Software"
    if _NON_SOFTWARE_ROLE.search(title) or _NON_SOFTWARE_ROLE.search(department):
        return "Other"
    return "Software"


def _is_us_or_remote(location: str) -> bool:
    loc = location.lower().strip()
    segments = re.split(r"\s*[;|•·]\s*|\s+/\s+", loc)
    if len(segments) > 1:
        return any(_is_us_or_remote(segment) for segment in segments)
    if "remote" in loc:
        return True
    if re.search(r"\b(united states(?: of america)?|usa|u\.s\.?a\.?)\b", loc) or loc == "us":
        return True
    if re.match(r"^us\s*,", loc):
        return True  # Workday formats US locations as "US, <State>, <City>"
    if re.search(r"\bcounty\s*$", loc):
        return True  # Adzuna formats US locations as "City, X County" (ending in "county",
        # unlike e.g. "Madawaska County, NB, Canada" which ends with the country name)
    loc = re.sub(r"^(?:hybrid|on[ -]?site)\s*[-–—:]\s*", "", loc)
    loc = re.sub(r"\s*\((?:hybrid|on[ -]?site)\)$", "", loc)
    match = re.search(r",\s*([a-z]{2})$", loc)
    if match and match.group(1).upper() in _US_STATE_ABBR:
        return True
    if "," in loc and loc.rsplit(",", 1)[1].strip() in _US_STATE_NAMES:
        return True
    loc = re.sub(r"\s+(?:office|hq)$|\s*-\s*sf\d+$", "", loc)
    return loc in _US_CITY_NAMES or all(part.strip() in _US_CITY_NAMES for part in loc.split(","))


def locations_pass(listing: Listing, mode: str) -> bool:
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

    return locations_pass(listing, relevance.locations_mode)

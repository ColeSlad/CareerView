from __future__ import annotations

import json
import time
from pathlib import Path

from careerview.models import Listing

DEFAULT_LISTINGS_PATH = Path("data/listings.json")
DEFAULT_META_PATH = Path("data/meta.json")


def now_ts() -> int:
    return int(time.time())


def load_listings(path: Path | str = DEFAULT_LISTINGS_PATH) -> dict[str, Listing]:
    path = Path(path)
    if not path.exists():
        return {}
    with open(path) as f:
        raw = json.load(f)
    return {entry["uid"]: Listing.from_dict(entry) for entry in raw}


def save_listings(listings: dict[str, Listing], path: Path | str = DEFAULT_LISTINGS_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(listings.values(), key=lambda listing: listing.first_seen or 0, reverse=True)
    with open(path, "w") as f:
        json.dump([listing.to_dict() for listing in ordered], f, indent=2)


def load_meta(path: Path | str = DEFAULT_META_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_meta(meta: dict, path: Path | str = DEFAULT_META_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(meta, f, indent=2)

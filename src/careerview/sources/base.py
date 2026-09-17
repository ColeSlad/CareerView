from __future__ import annotations

from abc import ABC, abstractmethod
import time

import httpx

from careerview.models import Listing


class Source(ABC):
    name: str

    @abstractmethod
    def fetch(self) -> list[Listing]:
        """Fetch and normalize listings from this source. Raises on network/parse failure."""


def fetch_with_retry(source: Source) -> list[Listing]:
    """Retry one transient network/server failure without hiding broken board IDs."""
    try:
        return source.fetch()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code < 500:
            raise
    except httpx.TransportError:
        pass
    time.sleep(1)
    return source.fetch()

from __future__ import annotations

from abc import ABC, abstractmethod

from careerview.models import Listing


class Source(ABC):
    name: str

    @abstractmethod
    def fetch(self) -> list[Listing]:
        """Fetch and normalize listings from this source. Raises on network/parse failure."""

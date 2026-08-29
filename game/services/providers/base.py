from abc import ABC, abstractmethod
from typing import Any


class BaseSportsProvider(ABC):
    """Contract for future external sports-data providers."""

    @abstractmethod
    def fetch_upcoming_matches(self, sport_code: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_live_matches(self, sport_code: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_finished_matches(self, sport_code: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

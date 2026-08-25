import json
import logging
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from game.services.providers.base import BaseSportsProvider

logger = logging.getLogger(__name__)


class NeurokeffProviderError(RuntimeError):
    pass


class NeurokeffSportsProvider(BaseSportsProvider):
    """Football-only Neurokeff API v2 provider for the MVP."""

    def __init__(self) -> None:
        self.base_url = settings.NEUROKEFF_API_BASE_URL.rstrip("/") + "/"
        self.token = settings.NEUROKEFF_API_TOKEN
        self.sport_id = settings.NEUROKEFF_FOOTBALL_SPORT_ID
        self.lang = settings.NEUROKEFF_LANG
        self.page_size = settings.NEUROKEFF_PAGE_SIZE
        self.timeout = settings.NEUROKEFF_API_TIMEOUT

    def fetch_upcoming_matches(self) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        today = timezone.localdate()
        for match_date in self._dates(today, settings.NEUROKEFF_PREMATCH_DAYS_AHEAD):
            matches.extend(self._fetch_matches("prematch", date_value=match_date))
        return matches

    def fetch_live_matches(self) -> list[dict[str, Any]]:
        return self._fetch_matches("live")

    def fetch_finished_matches(self) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        days = settings.NEUROKEFF_FINISHED_DAYS_BACK
        first_date = timezone.localdate() - timedelta(days=max(days - 1, 0))
        for match_date in self._dates(first_date, days):
            matches.extend(self._fetch_matches("finished", date_value=match_date))
        return matches

    def _fetch_matches(
        self,
        endpoint: str,
        *,
        date_value: date | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "sport_id": self.sport_id,
            "lang": self.lang,
            "page_size": self.page_size,
            "paginate": "true",
        }
        if date_value is not None:
            params["date"] = date_value.isoformat()
        return self._get_paginated(endpoint, params)

    def _get_paginated(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page = 1

        while page <= settings.NEUROKEFF_MAX_PAGES:
            payload = self._request(endpoint, {**params, "page": page})
            if isinstance(payload, list):
                results.extend(payload)
                return results

            page_results = payload.get("results", [])
            if not isinstance(page_results, list):
                raise NeurokeffProviderError(f"Unexpected Neurokeff payload for {endpoint}")

            results.extend(page_results)
            if not payload.get("next"):
                return results
            page += 1

        logger.warning("Neurokeff pagination stopped by max page limit for %s", endpoint)
        return results

    def _request(self, endpoint: str, params: dict[str, Any]) -> Any:
        if not self.token:
            raise NeurokeffProviderError("NEUROKEFF_API_TOKEN is not configured")

        url = urljoin(self.base_url, endpoint.lstrip("/"))
        request = Request(
            f"{url}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Token {self.token}",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise NeurokeffProviderError(
                f"Neurokeff HTTP {exc.code} for {endpoint}: {body[:300]}"
            ) from exc
        except URLError as exc:
            raise NeurokeffProviderError(f"Neurokeff request failed for {endpoint}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise NeurokeffProviderError(f"Neurokeff returned invalid JSON for {endpoint}") from exc

    @staticmethod
    def _dates(start: date, count: int) -> list[date]:
        return [start + timedelta(days=offset) for offset in range(max(count, 1))]

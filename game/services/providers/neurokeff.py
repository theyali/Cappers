import json
import logging
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
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

    def fetch_matches_for_scope(
        self,
        scope: str,
        *,
        date_value: date | None = None,
    ) -> list[dict[str, Any]]:
        if scope not in {"prematch", "live", "finished"}:
            raise NeurokeffProviderError(f"Unsupported match scope: {scope}")
        return self._fetch_matches(scope, date_value=date_value)

    def fetch_matches_info(self, ids: list[int]) -> list[dict[str, Any]]:
        """Fetch exact game records by provider ids."""
        normalized_ids = []
        for item in ids:
            try:
                normalized_ids.append(int(item))
            except (TypeError, ValueError):
                continue
        if not normalized_ids:
            return []

        results: list[dict[str, Any]] = []
        batch_size = max(
            int(getattr(settings, "NEUROKEFF_GAME_INFO_BATCH_SIZE", 20)),
            1,
        )
        endpoint = getattr(settings, "NEUROKEFF_GAME_INFO_ENDPOINT", "/api/v1/games/info")

        for offset in range(0, len(normalized_ids), batch_size):
            batch = normalized_ids[offset:offset + batch_size]
            payload = self._request(endpoint, {"ids": ",".join(map(str, batch))})
            results.extend(self._normalize_info_payload(payload))
        return results

    def fetch_game_predictions(self, external_id: int) -> dict[str, Any]:
        endpoint = getattr(
            settings,
            "NEUROKEFF_GAME_PREDICTIONS_ENDPOINT",
            "games/predictions",
        )
        payload = self._request(endpoint, {"game_id": int(external_id)})
        if not isinstance(payload, dict):
            raise NeurokeffProviderError("Unexpected Neurokeff game predictions payload")
        return payload

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

        url = self._endpoint_url(endpoint)
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

    def _endpoint_url(self, endpoint: str) -> str:
        if endpoint.startswith(("http://", "https://")):
            return endpoint
        if endpoint.startswith("/"):
            parsed = urlparse(self.base_url)
            return f"{parsed.scheme}://{parsed.netloc}{endpoint}"
        return urljoin(self.base_url, endpoint)

    @staticmethod
    def _normalize_info_payload(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            raise NeurokeffProviderError("Unexpected Neurokeff game info payload")

        for key in ("results", "games", "matches", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        dict_items = [
            item for item in payload.values()
            if isinstance(item, dict) and item.get("id") is not None
        ]
        if dict_items:
            return dict_items
        if payload.get("id") is not None:
            return [payload]
        return []

    @staticmethod
    def _dates(start: date, count: int) -> list[date]:
        return [start + timedelta(days=offset) for offset in range(max(count, 1))]

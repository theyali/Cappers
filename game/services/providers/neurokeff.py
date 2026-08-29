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
    """Neurokeff API v2 provider for all configured sports."""

    def __init__(self, sports: list[dict[str, Any]] | None = None) -> None:
        self.base_url = settings.NEUROKEFF_API_BASE_URL.rstrip("/") + "/"
        self.token = settings.NEUROKEFF_API_TOKEN
        self.sports = self._configured_sports(sports)
        self.lang = settings.NEUROKEFF_LANG
        self.page_size = settings.NEUROKEFF_PAGE_SIZE
        self.timeout = settings.NEUROKEFF_API_TIMEOUT

    def fetch_upcoming_matches(self) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        today = timezone.localdate()
        for sport in self.sports:
            for match_date in self._dates(today, settings.NEUROKEFF_PREMATCH_DAYS_AHEAD):
                matches.extend(self._fetch_matches("prematch", sport=sport, date_value=match_date))
        return matches

    def fetch_live_matches(self) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for sport in self.sports:
            matches.extend(self._fetch_matches("live", sport=sport))
        return matches

    def fetch_finished_matches(self) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        days = settings.NEUROKEFF_FINISHED_DAYS_BACK
        first_date = timezone.localdate() - timedelta(days=max(days - 1, 0))
        for sport in self.sports:
            for match_date in self._dates(first_date, days):
                matches.extend(self._fetch_matches("finished", sport=sport, date_value=match_date))
        return matches

    def fetch_matches_for_scope(
        self,
        scope: str,
        *,
        date_value: date | None = None,
        sport_code: str | None = None,
    ) -> list[dict[str, Any]]:
        if scope not in {"prematch", "live", "finished"}:
            raise NeurokeffProviderError(f"Unsupported match scope: {scope}")
        matches: list[dict[str, Any]] = []
        for sport in self._sports_for_code(sport_code):
            matches.extend(self._fetch_matches(scope, sport=sport, date_value=date_value))
        return matches

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
            results.extend(
                self._with_sport_meta(item)
                for item in self._normalize_info_payload(payload)
            )
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
        sport: dict[str, Any],
        date_value: date | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "sport_id": sport["id"],
            "lang": self.lang,
            "page_size": self.page_size,
            "paginate": "true",
        }
        if date_value is not None:
            params["date"] = date_value.isoformat()
        return [self._with_sport_meta(item, sport) for item in self._get_paginated(endpoint, params)]

    def _get_paginated(self, endpoint: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page = 1
        seen_next_urls: set[str] = set()

        while True:
            payload = self._request(endpoint, {**params, "page": page})
            if isinstance(payload, list):
                results.extend(payload)
                return results

            page_results = payload.get("results", [])
            if not isinstance(page_results, list):
                raise NeurokeffProviderError(f"Unexpected Neurokeff payload for {endpoint}")

            results.extend(page_results)
            next_url = payload.get("next")
            if not next_url:
                return results
            next_url = str(next_url)
            if next_url in seen_next_urls:
                logger.warning("Neurokeff pagination stopped by repeated next URL for %s", endpoint)
                return results
            seen_next_urls.add(next_url)
            page += 1

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
    def _configured_sports(sports: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        source = sports if sports is not None else getattr(settings, "NEUROKEFF_SPORTS", [])
        normalized = []
        for item in source:
            if not isinstance(item, dict):
                continue
            try:
                sport_id = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            normalized.append(
                {
                    "code": str(item.get("code") or sport_id),
                    "id": sport_id,
                    "name": str(item.get("name") or item.get("code") or sport_id),
                    "name_ru": str(item.get("name_ru") or item.get("name") or item.get("code") or sport_id),
                }
            )
        return normalized

    def _sports_for_code(self, sport_code: str | None) -> list[dict[str, Any]]:
        if not sport_code:
            return self.sports
        sport_code = sport_code.strip().lower()
        return [sport for sport in self.sports if str(sport.get("code")).lower() == sport_code]

    def _with_sport_meta(
        self,
        payload: dict[str, Any],
        sport: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return payload
        sport = sport or self._sport_by_payload(payload)
        if not sport:
            return payload
        return {**payload, "_sport_meta": sport}

    def _sport_by_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        sport_id = payload.get("sport_id")
        sport_payload = payload.get("sport")
        if isinstance(sport_payload, dict):
            sport_id = sport_id or sport_payload.get("id")
        try:
            normalized_id = int(sport_id)
        except (TypeError, ValueError):
            return None
        return next((sport for sport in self.sports if sport["id"] == normalized_id), None)

    @staticmethod
    def _dates(start: date, count: int) -> list[date]:
        return [start + timedelta(days=offset) for offset in range(max(count, 1))]

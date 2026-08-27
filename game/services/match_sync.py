import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from game.models import Country, League, LeagueSeason, Match, MatchOdds, Provider, Sport, Team, Venue
from game.services.odds import has_odds_payload, match_odds_defaults
from game.services.providers import NeurokeffSportsProvider

logger = logging.getLogger(__name__)


class MatchSyncService:
    """Provider-independent match synchronization facade."""

    PREMATCH_TIME_STATUSES = {"0"}
    LIVE_TIME_STATUSES = {"1", "2"}
    TERMINAL_TIME_STATUSES = {"3", "4", "5", "6", "7", "8"}

    def __init__(self, provider: NeurokeffSportsProvider | None = None) -> None:
        self.provider = provider or NeurokeffSportsProvider()

    def sync_upcoming(self) -> dict:
        result = self._sync_scope(
            Match.SyncScope.PREMATCH,
            self.provider.fetch_upcoming_matches(),
        )
        result["expired"] = self._expire_past_prematches()
        return result

    def sync_live(self) -> dict:
        return self._sync_scope(
            Match.SyncScope.LIVE,
            self.provider.fetch_live_matches(),
            derive_scope_from_payload=True,
        )

    def sync_finished(self) -> dict:
        return self._sync_scope(
            Match.SyncScope.FINISHED,
            self.provider.fetch_finished_matches(),
        )

    def sync_match_predictions(self, match: Match, *, force: bool = False) -> dict:
        if not force and not self._match_predictions_are_stale(match):
            return {"status": "skipped", "reason": "fresh"}

        payload = self.provider.fetch_game_predictions(match.external_id)
        now = timezone.now()
        match.provider_predictions = payload
        match.provider_predictions_updated_at = now
        Match.objects.filter(pk=match.pk).update(
            provider_predictions=payload,
            provider_predictions_updated_at=now,
            updated_at=now,
        )
        return {
            "status": "ok",
            "external_id": match.external_id,
            "available": bool((payload.get("predictions") or {}).get("available")),
        }

    def sync_stuck_live_matches(self) -> dict:
        stale_after = timedelta(
            minutes=max(
                int(getattr(settings, "NEUROKEFF_STUCK_LIVE_AFTER_MINUTES", 10)),
                1,
            )
        )
        limit = max(int(getattr(settings, "NEUROKEFF_STUCK_LIVE_LIMIT", 500)), 1)
        threshold = timezone.now() - stale_after
        matches = list(
            Match.objects.filter(
                Q(last_seen_at__lt=threshold)
                | Q(time_status__in=self.TERMINAL_TIME_STATUSES),
                provider=Provider.NEUROKEFF,
                sync_scope=Match.SyncScope.LIVE,
            ).order_by("last_seen_at", "id")[:limit]
        )
        external_ids = [match.external_id for match in matches]
        if not external_ids:
            return {
                "status": "ok",
                "checked": 0,
                "fetched": 0,
                "updated": 0,
                "missing": 0,
                "scopes": {},
            }

        payloads = self.provider.fetch_matches_info(external_ids)
        payload_by_id = {
            int(payload["id"]): payload
            for payload in payloads
            if self._to_int(payload.get("id")) is not None
        }
        updated = 0
        missing = 0
        scopes: dict[str, int] = {}
        now = timezone.now()

        with transaction.atomic():
            for match in matches:
                payload = payload_by_id.get(match.external_id)
                if payload is None:
                    missing += 1
                    continue

                scope = self._scope_from_payload(payload, default=Match.SyncScope.LIVE)
                defaults = {
                    **self._match_defaults(payload, scope),
                    "last_seen_at": now,
                }
                for field, value in defaults.items():
                    setattr(match, field, value)
                match.save(update_fields=[*defaults.keys(), "updated_at"])
                self._sync_odds(match, payload.get("odds") or {})
                updated += 1
                scopes[scope] = scopes.get(scope, 0) + 1

        result = {
            "status": "ok",
            "checked": len(matches),
            "fetched": len(payloads),
            "updated": updated,
            "missing": missing,
            "scopes": scopes,
        }
        logger.info("Stuck live match sync completed: %s", result)
        return result

    @transaction.atomic
    def _sync_scope(
        self,
        scope: str,
        payloads: list[dict[str, Any]],
        *,
        derive_scope_from_payload: bool = False,
    ) -> dict:
        scope_value = getattr(scope, "value", scope)
        created = 0
        updated = 0
        skipped = 0
        scopes: dict[str, int] = {}
        now = timezone.now()

        for payload in payloads:
            external_id = payload.get("id")
            if external_id is None:
                skipped += 1
                logger.warning("Skipping Neurokeff match without id: %s", payload)
                continue

            match_scope = (
                self._scope_from_payload(payload, default=scope_value)
                if derive_scope_from_payload
                else scope_value
            )
            match, was_created = Match.objects.update_or_create(
                provider=Provider.NEUROKEFF,
                external_id=external_id,
                defaults={**self._match_defaults(payload, match_scope), "last_seen_at": now},
            )
            self._sync_odds(match, payload.get("odds") or {})
            scopes[match_scope] = scopes.get(match_scope, 0) + 1
            if was_created:
                created += 1
            else:
                updated += 1

        result = {
            "status": "ok",
            "scope": scope_value,
            "fetched": len(payloads),
            "created": created,
            "updated": updated,
            "skipped": skipped,
        }
        if derive_scope_from_payload:
            result["scopes"] = scopes
        logger.info("Match sync completed: %s", result)
        return result

    def _expire_past_prematches(self) -> int:
        return Match.objects.filter(
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at__lt=timezone.now(),
        ).update(sync_scope=Match.SyncScope.FINISHED)

    def _match_predictions_are_stale(self, match: Match) -> bool:
        if not isinstance(match.provider_predictions, dict) or not match.provider_predictions:
            return True
        if not match.provider_predictions_updated_at:
            return True
        stale_seconds = max(
            int(getattr(settings, "NEUROKEFF_GAME_PREDICTIONS_STALE_SECONDS", 3600)),
            1,
        )
        return timezone.now() - match.provider_predictions_updated_at > timedelta(
            seconds=stale_seconds
        )

    def _match_defaults(self, payload: dict[str, Any], scope: str) -> dict[str, Any]:
        league = payload.get("league") or {}
        country = league.get("country") or {}
        teams = payload.get("teams") or {}
        home_team = teams.get("home") or {}
        away_team = teams.get("away") or {}
        venue_payload = payload.get("venue") or {}

        sport = self._sync_sport(payload)
        league_country = self._sync_country(country)
        venue = self._sync_venue(venue_payload)
        league_obj = self._sync_league(league, sport, league_country)
        league_season = self._sync_league_season(league_obj, sport, league.get("season") or {})
        home_team_obj = self._sync_team(home_team, sport, league_country)
        away_team_obj = self._sync_team(away_team, sport, league_country)

        starts_at = parse_datetime(payload.get("game_date_time") or "")
        if starts_at is not None and timezone.is_naive(starts_at):
            starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())

        return {
            "sport": sport,
            "sync_scope": scope,
            "time_status": str(payload.get("time_status") or ""),
            "starts_at": starts_at,
            "league": league_obj,
            "league_season": league_season,
            "home_team": home_team_obj,
            "away_team": away_team_obj,
            "venue": venue,
            "score": str(payload.get("score") or ""),
            "live_minute": self._to_int(payload.get("live_minute")),
            "live_minute_label": str(payload.get("live_minute_str") or ""),
            "raw_data": payload,
        }

    def _sync_sport(self, payload: dict[str, Any]) -> Sport:
        sport_id = self._to_int(payload.get("sport_id"), default=2)
        sport, _ = Sport.objects.update_or_create(
            provider=Provider.NEUROKEFF,
            external_id=sport_id,
            defaults={
                "code": "football",
                "name": "Football",
                "name_ru": "Футбол",
                "raw_data": {"sport_id": sport_id},
            },
        )
        return sport

    def _sync_country(self, payload: dict[str, Any]) -> Country | None:
        external_id = self._to_int(payload.get("id"))
        if external_id is None:
            return None

        country, _ = Country.objects.update_or_create(
            provider=Provider.NEUROKEFF,
            external_id=external_id,
            defaults={
                "code": str(payload.get("code") or ""),
                "name": self._localized(payload.get("name"), "en"),
                "name_ru": self._localized(payload.get("name"), "ru"),
                "logo": str(payload.get("logo") or ""),
                "raw_data": payload,
            },
        )
        return country

    def _sync_venue(self, payload: dict[str, Any]) -> Venue | None:
        external_id = self._to_int(payload.get("id"))
        if external_id is None:
            return None

        venue, _ = Venue.objects.update_or_create(
            provider=Provider.NEUROKEFF,
            external_id=external_id,
            defaults={
                "name": self._localized(payload.get("name"), "en"),
                "name_ru": self._localized(payload.get("name"), "ru"),
                "city": self._localized(payload.get("city"), "en"),
                "city_ru": self._localized(payload.get("city"), "ru"),
                "capacity": self._to_int(payload.get("capacity")),
                "logo": str(payload.get("logo") or ""),
                "address": str(payload.get("address") or ""),
                "address_ru": str(payload.get("address_ru") or ""),
                "surface": str(payload.get("surface") or ""),
                "surface_ru": str(payload.get("surface_ru") or ""),
                "raw_data": payload,
            },
        )
        return venue

    def _sync_league(
        self,
        payload: dict[str, Any],
        sport: Sport,
        country: Country | None,
    ) -> League | None:
        external_id = self._to_int(payload.get("id"))
        if external_id is None:
            return None

        league, _ = League.objects.update_or_create(
            provider=Provider.NEUROKEFF,
            external_id=external_id,
            defaults={
                "sport": sport,
                "country": country,
                "name": self._localized(payload.get("name"), "en"),
                "name_ru": self._localized(payload.get("name"), "ru"),
                "logo": str(payload.get("logo") or ""),
                "gender": str(payload.get("gender") or ""),
                "age_group": str(payload.get("age_group") or ""),
                "raw_data": payload,
            },
        )
        return league

    def _sync_league_season(
        self,
        league: League | None,
        sport: Sport,
        payload: dict[str, Any],
    ) -> LeagueSeason | None:
        year = self._to_int(payload.get("year"))
        if league is None or year is None:
            return None

        round_updated_at = parse_datetime(payload.get("round_updated_at") or "")
        if round_updated_at is not None and timezone.is_naive(round_updated_at):
            round_updated_at = timezone.make_aware(round_updated_at, timezone.get_current_timezone())

        season, _ = LeagueSeason.objects.update_or_create(
            league=league,
            year=year,
            defaults={
                "sport": sport,
                "start_date": parse_date(payload.get("start_date") or ""),
                "end_date": parse_date(payload.get("end_date") or ""),
                "is_current": bool(payload.get("is_current")),
                "round_name": str(payload.get("round_name") or ""),
                "round_name_ru": str(payload.get("round_name_ru") or ""),
                "round_updated_at": round_updated_at,
                "raw_data": payload,
            },
        )
        return season

    def _sync_team(
        self,
        payload: dict[str, Any],
        sport: Sport,
        country: Country | None,
    ) -> Team | None:
        external_id = self._to_int(payload.get("id"))
        if external_id is None:
            return None

        team, _ = Team.objects.update_or_create(
            provider=Provider.NEUROKEFF,
            external_id=external_id,
            defaults={
                "sport": sport,
                "country": country,
                "name": self._localized(payload.get("name"), "en"),
                "name_ru": self._localized(payload.get("name"), "ru"),
                "logo": str(payload.get("logo") or ""),
                "gender": str(payload.get("gender") or ""),
                "age_group": str(payload.get("age_group") or ""),
                "raw_data": payload,
            },
        )
        return team

    def _sync_odds(self, match: Match, payload: dict[str, Any]) -> None:
        if not has_odds_payload(payload):
            return
        MatchOdds.objects.update_or_create(
            match=match,
            defaults=match_odds_defaults(payload),
        )

    @classmethod
    def _scope_from_payload(cls, payload: dict[str, Any], default: str) -> str:
        for value in cls._status_values(payload):
            scope = cls._scope_from_status(value)
            if scope is not None:
                return scope
        return default

    @staticmethod
    def _status_values(payload: dict[str, Any]) -> list[Any]:
        values = []
        for key in (
            "sync_scope",
            "scope",
            "status",
            "game_status",
            "time_status",
            "status_short",
            "short_status",
            "state",
            "phase",
        ):
            value = payload.get(key)
            values.append(value)
            if isinstance(value, dict):
                values.extend(
                    value.get(nested_key)
                    for nested_key in ("short", "long", "name", "code", "type")
                )
        return values

    @staticmethod
    def _scope_from_status(value: Any) -> str | None:
        if value in (None, ""):
            return None
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in MatchSyncService.PREMATCH_TIME_STATUSES:
            return Match.SyncScope.PREMATCH
        if normalized in MatchSyncService.LIVE_TIME_STATUSES:
            return Match.SyncScope.LIVE
        if normalized in MatchSyncService.TERMINAL_TIME_STATUSES:
            return Match.SyncScope.FINISHED

        if normalized in {
            "prematch",
            "pre_match",
            "upcoming",
            "scheduled",
            "not_started",
            "notstarted",
            "ns",
        }:
            return Match.SyncScope.PREMATCH
        if normalized in {
            "live",
            "inplay",
            "in_play",
            "playing",
            "started",
            "first_half",
            "second_half",
            "1h",
            "2h",
            "ht",
            "et",
            "p",
        }:
            return Match.SyncScope.LIVE
        if normalized in {
            "finished",
            "finish",
            "ended",
            "closed",
            "completed",
            "fulltime",
            "full_time",
            "ft",
            "aet",
            "ap",
        }:
            return Match.SyncScope.FINISHED
        return None

    @staticmethod
    def _localized(value: Any, preferred: str = "ru") -> str:
        if isinstance(value, dict):
            fallback = "en" if preferred == "ru" else "ru"
            return str(
                value.get(preferred)
                or value.get(fallback)
                or next(iter(value.values()), "")
                or ""
            )
        return str(value or "")

    @staticmethod
    def _to_int(value: Any, default: int | None = None) -> int | None:
        if value in (None, ""):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

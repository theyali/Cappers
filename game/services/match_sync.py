import logging
from typing import Any

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from game.models import Country, League, LeagueSeason, Match, MatchOdds, Provider, Sport, Team, Venue
from game.services.odds import match_odds_defaults
from game.services.providers import NeurokeffSportsProvider

logger = logging.getLogger(__name__)


class MatchSyncService:
    """Provider-independent match synchronization facade."""

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
        )

    def sync_finished(self) -> dict:
        return self._sync_scope(
            Match.SyncScope.FINISHED,
            self.provider.fetch_finished_matches(),
        )

    @transaction.atomic
    def _sync_scope(self, scope: str, payloads: list[dict[str, Any]]) -> dict:
        scope_value = getattr(scope, "value", scope)
        created = 0
        updated = 0
        skipped = 0
        now = timezone.now()

        for payload in payloads:
            external_id = payload.get("id")
            if external_id is None:
                skipped += 1
                logger.warning("Skipping Neurokeff match without id: %s", payload)
                continue

            match, was_created = Match.objects.update_or_create(
                provider=Provider.NEUROKEFF,
                external_id=external_id,
                defaults={**self._match_defaults(payload, scope_value), "last_seen_at": now},
            )
            self._sync_odds(match, payload.get("odds") or {})
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
        logger.info("Match sync completed: %s", result)
        return result

    def _expire_past_prematches(self) -> int:
        return Match.objects.filter(
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at__lt=timezone.now(),
        ).update(sync_scope=Match.SyncScope.FINISHED)

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
        MatchOdds.objects.update_or_create(
            match=match,
            defaults=match_odds_defaults(payload),
        )

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

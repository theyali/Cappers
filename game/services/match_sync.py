import hashlib
import json
import logging
from decimal import Decimal, InvalidOperation
from functools import partial
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import F, Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from game.models import (
    Country,
    League,
    LeagueSeason,
    Match,
    MatchEvent,
    MatchEventParticipant,
    MatchOdds,
    MatchStatistic,
    Provider,
    Sport,
    Team,
    Venue,
    country_logo_upload_path,
    league_logo_upload_path,
    sport_image_upload_path,
    team_logo_upload_path,
)
from game.services.local_logos import sync_entity_logo
from game.services.odds import has_odds_payload, match_odds_defaults
from game.services.providers import NeurokeffSportsProvider

logger = logging.getLogger(__name__)


STAT_SORT_ORDER = {
    "ball_possession": 10,
    "possession": 10,
    "shots": 20,
    "shots_total": 20,
    "total_shots": 20,
    "shots_on_goal": 30,
    "shots_on_target": 30,
    "corner_kicks": 40,
    "corners": 40,
    "yellow_cards": 50,
    "red_cards": 60,
}

STAT_LABELS_RU = {
    "ball_possession": "Владение, %",
    "possession": "Владение, %",
    "shots": "Удары",
    "shots_total": "Удары",
    "total_shots": "Удары",
    "shots_on_goal": "Удары в створ",
    "shots_on_target": "Удары в створ",
    "corner_kicks": "Угловые",
    "corners": "Угловые",
    "yellow_cards": "Жёлтые карточки",
    "red_cards": "Красные карточки",
}


class MatchSyncService:
    """Provider-independent match synchronization facade."""

    PREMATCH_TIME_STATUSES = {"0"}
    LIVE_TIME_STATUSES = {"1", "2"}
    FINISHED_TIME_STATUSES = {"3"}
    POSTPONED_TIME_STATUSES = {"4"}
    CANCELED_TIME_STATUSES = {"5"}
    FORFEIT_TIME_STATUSES = {"6"}
    INTERRUPTED_TIME_STATUSES = {"7"}
    ABANDONED_TIME_STATUSES = {"8"}
    TERMINAL_TIME_STATUSES = (
        FINISHED_TIME_STATUSES
        | POSTPONED_TIME_STATUSES
        | CANCELED_TIME_STATUSES
        | FORFEIT_TIME_STATUSES
        | INTERRUPTED_TIME_STATUSES
        | ABANDONED_TIME_STATUSES
    )

    def __init__(self, provider: NeurokeffSportsProvider | None = None) -> None:
        self.provider = provider or NeurokeffSportsProvider()
        self._sport_cache: dict[tuple[str, int | str], Sport] = {}

    def sync_upcoming(self, sport_code: str | None = None) -> dict:
        payloads = (
            self.provider.fetch_upcoming_matches(sport_code=sport_code)
            if sport_code
            else self.provider.fetch_upcoming_matches()
        )
        result = self._sync_scope(
            Match.SyncScope.PREMATCH,
            payloads,
            derive_scope_from_payload=True,
        )
        result["expired"] = self._expire_past_prematches()
        if sport_code:
            result["sport"] = sport_code
        return result

    def sync_live(self, sport_code: str | None = None) -> dict:
        payloads = (
            self.provider.fetch_live_matches(sport_code=sport_code)
            if sport_code
            else self.provider.fetch_live_matches()
        )
        result = self._sync_scope(
            Match.SyncScope.LIVE,
            payloads,
            derive_scope_from_payload=True,
        )
        if sport_code:
            result["sport"] = sport_code
        return result

    def sync_finished(self, sport_code: str | None = None) -> dict:
        payloads = (
            self.provider.fetch_finished_matches(sport_code=sport_code)
            if sport_code
            else self.provider.fetch_finished_matches()
        )
        result = self._sync_scope(
            Match.SyncScope.FINISHED,
            payloads,
            derive_scope_from_payload=True,
        )
        if sport_code:
            result["sport"] = sport_code
        return result

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

    def sync_match_statistics(self, match: Match) -> dict:
        if match.sync_scope == Match.SyncScope.PREMATCH:
            return {"status": "skipped", "reason": "prematch", "external_id": match.external_id}

        embedded = self._embedded_statistics_payload(match.raw_data)
        if embedded is not None:
            return self._sync_statistics_payload(match, {"statistics": embedded})

        payload = self.provider.fetch_game_statistics(match.external_id)
        return self._sync_statistics_payload(match, payload)

    def sync_match_events(self, match: Match) -> dict:
        if match.sync_scope == Match.SyncScope.PREMATCH:
            return {
                "status": "skipped",
                "reason": "prematch",
                "external_id": match.external_id,
                "available": match.events_available,
                "rows": MatchEvent.objects.filter(match=match).count(),
            }

        # A direct refresh must always read the provider. ``raw_data.events`` is
        # only a snapshot from an earlier sync and may be stale for a live match.
        payload = self.provider.fetch_game_events(match.external_id)
        return self._sync_events_payload(match, payload)

    def sync_live_statistics(self, *, limit: int | None = None) -> dict:
        limit = max(
            int(limit or getattr(settings, "NEUROKEFF_LIVE_STATISTICS_LIMIT", 80)),
            1,
        )
        matches = list(
            Match.objects.filter(
                provider=Provider.NEUROKEFF,
                sync_scope=Match.SyncScope.LIVE,
            )
            .annotate(last_stats_fetched=Max("statistics_rows__fetched_at"))
            .order_by("last_stats_fetched", "last_seen_at", "id")[:limit]
        )
        updated = 0
        skipped = 0
        errors = 0
        for match in matches:
            try:
                result = self.sync_match_statistics(match)
            except Exception:
                errors += 1
                logger.exception("Failed to sync Neurokeff statistics for match %s", match.pk)
                continue
            if result.get("status") == "ok":
                updated += 1
            else:
                skipped += 1
        return {
            "status": "ok",
            "checked": len(matches),
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

    def sync_live_events(self, *, limit: int | None = None) -> dict:
        limit = max(
            int(limit or getattr(settings, "NEUROKEFF_LIVE_EVENTS_LIMIT", 80)),
            1,
        )
        matches = list(
            Match.objects.filter(
                provider=Provider.NEUROKEFF,
                sync_scope=Match.SyncScope.LIVE,
            )
            .order_by(
                F("events_fetched_at").asc(nulls_first=True),
                "last_seen_at",
                "id",
            )[:limit]
        )
        updated = 0
        skipped = 0
        errors = 0
        for match in matches:
            try:
                result = self.sync_match_events(match)
            except Exception:
                errors += 1
                logger.exception("Failed to sync Neurokeff events for match %s", match.pk)
                continue
            if result.get("status") == "ok":
                updated += 1
            else:
                skipped += 1
        return {
            "status": "ok",
            "checked": len(matches),
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
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
            Match.objects.select_related("sport").filter(
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
                    **self._match_defaults(payload, scope, sport_fallback=match.sport),
                    "last_seen_at": now,
                }
                for field, value in defaults.items():
                    setattr(match, field, value)
                match.save(update_fields=[*defaults.keys(), "updated_at"])
                self._sync_odds(match, payload.get("odds") or {})
                self._sync_embedded_statistics(match, payload)
                self._sync_embedded_events(match, payload)
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
            self._sync_embedded_statistics(match, payload)
            self._sync_embedded_events(match, payload)
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
        ).update(sync_scope=Match.SyncScope.LIVE)

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

    @transaction.atomic
    def _sync_events_payload(self, match: Match, payload: dict[str, Any]) -> dict:
        events = payload.get("events") if isinstance(payload, dict) else None
        now = timezone.now()
        if not isinstance(events, dict) or events.get("available") is not True:
            self._record_events_sync_state(
                match,
                events=events,
                fetched_at=now,
                available=False,
            )
            return {
                "status": "skipped",
                "reason": "unavailable",
                "external_id": match.external_id,
                "available": False,
                "rows": MatchEvent.objects.filter(match=match).count(),
            }

        items = events.get("items")
        if not isinstance(items, list):
            self._record_events_sync_state(
                match,
                events=events,
                fetched_at=now,
                available=None,
            )
            return {
                "status": "skipped",
                "reason": "invalid_items",
                "external_id": match.external_id,
                "available": True,
                "rows": MatchEvent.objects.filter(match=match).count(),
            }

        rows = self._normalize_event_rows(match, events)
        if not rows:
            # An explicit empty list is an authoritative snapshot and may clear
            # rows. A malformed non-empty list must never destroy known events.
            if items:
                self._record_events_sync_state(
                    match,
                    events=events,
                    fetched_at=now,
                    available=None,
                )
                return {
                    "status": "skipped",
                    "reason": "invalid_items",
                    "external_id": match.external_id,
                    "available": True,
                    "rows": MatchEvent.objects.filter(match=match).count(),
                }

            with transaction.atomic():
                existing_events = MatchEvent.objects.filter(match=match)
                deleted = existing_events.count()
                existing_events.delete()
                self._record_events_sync_state(
                    match,
                    events=events,
                    fetched_at=now,
                    available=True,
                )
            return {
                "status": "ok",
                "reason": "empty",
                "external_id": match.external_id,
                "available": True,
                "rows": 0,
                "deleted": deleted,
            }

        active_keys = {row["event_key"] for row in rows}
        with transaction.atomic():
            for row in rows:
                participants = row.pop("participants")
                event, _ = MatchEvent.objects.update_or_create(
                    match=match,
                    event_key=row["event_key"],
                    defaults={
                        **row,
                        "provider": Provider.NEUROKEFF,
                        "fetched_at": now,
                    },
                )
                event.participants_rows.all().delete()
                MatchEventParticipant.objects.bulk_create(
                    [
                        MatchEventParticipant(
                            event=event,
                            role=participant["role"],
                            player_external_id=participant["player_external_id"],
                            player_name=participant["player_name"],
                            player_name_ru=participant["player_name_ru"],
                            raw_data=participant["raw_data"],
                        )
                        for participant in participants
                    ]
                )

            stale_events = MatchEvent.objects.filter(match=match).exclude(
                event_key__in=active_keys,
            )
            deleted = stale_events.count()
            stale_events.delete()
            self._record_events_sync_state(
                match,
                events=events,
                fetched_at=now,
                available=True,
            )
        return {
            "status": "ok",
            "external_id": match.external_id,
            "available": True,
            "rows": len(rows),
            "deleted": deleted,
        }

    @staticmethod
    def _record_events_sync_state(
        match: Match,
        *,
        events: dict[str, Any] | None,
        fetched_at: datetime,
        available: bool | None,
    ) -> None:
        locked_match = Match.objects.select_for_update().get(pk=match.pk)
        raw_data = locked_match.raw_data if isinstance(locked_match.raw_data, dict) else {}
        if isinstance(events, dict):
            raw_data = {**raw_data, "events": events}

        match.raw_data = raw_data
        match.events_fetched_at = fetched_at
        match.events_available = available
        locked_match.raw_data = raw_data
        locked_match.events_fetched_at = fetched_at
        locked_match.events_available = available
        locked_match.updated_at = fetched_at
        locked_match.save(
            update_fields=(
                "raw_data",
                "events_fetched_at",
                "events_available",
                "updated_at",
            )
        )

    def _sync_embedded_events(self, match: Match, payload: dict[str, Any]) -> dict | None:
        events = self._embedded_events_payload(payload)
        if events is None:
            return None
        return self._sync_events_payload(match, {"events": events})

    @staticmethod
    def _embedded_events_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        section = payload.get("events")
        if isinstance(section, dict) and "available" in section:
            return section
        data = payload.get("data")
        if isinstance(data, dict):
            section = data.get("events")
            if isinstance(section, dict) and "available" in section:
                return section
        return None

    def _normalize_event_rows(self, match: Match, events: dict[str, Any]) -> list[dict[str, Any]]:
        items = events.get("items")
        if not isinstance(items, list):
            return []

        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue

            external_id = self._to_int(item.get("id"))
            uid = self._to_int(item.get("uid"))
            seq = self._to_int(item.get("seq"))
            event_key = self._event_key(item, external_id=external_id, uid=uid, seq=seq)
            event_type = item.get("type") if isinstance(item.get("type"), dict) else {}
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            time_payload = item.get("time") if isinstance(item.get("time"), dict) else {}
            team_payload = item.get("team") if isinstance(item.get("team"), dict) else {}
            player = item.get("player") if isinstance(item.get("player"), dict) else {}
            assist = item.get("assist") if isinstance(item.get("assist"), dict) else {}
            team_external_id = self._to_int(team_payload.get("id"))
            team_side = str(team_payload.get("side") or "").strip().lower()
            team = self._event_team(match, team_external_id=team_external_id, side=team_side)

            rows.append(
                {
                    "event_key": event_key,
                    "external_id": external_id,
                    "uid": uid,
                    "seq": seq,
                    "event_type_code": str(event_type.get("code") or "").strip(),
                    "event_type_name": str(event_type.get("name") or "").strip(),
                    "event_type_name_ru": str(event_type.get("name_ru") or "").strip(),
                    "detail_code": str(detail.get("code") or "").strip(),
                    "detail_name": str(detail.get("name") or "").strip(),
                    "detail_name_ru": str(detail.get("name_ru") or "").strip(),
                    "minute": self._to_int(time_payload.get("minute")),
                    "extra_minute": self._to_int(time_payload.get("extra")),
                    "team": team,
                    "team_external_id": team_external_id,
                    "team_name": str(team_payload.get("name") or "").strip(),
                    "team_name_ru": str(team_payload.get("name_ru") or "").strip(),
                    "team_side": team_side,
                    "player_external_id": self._to_int(player.get("id")),
                    "player_name": str(player.get("name") or "").strip(),
                    "player_name_ru": str(player.get("name_ru") or "").strip(),
                    "assist_external_id": self._to_int(assist.get("id")),
                    "assist_name": str(assist.get("name") or "").strip(),
                    "assist_name_ru": str(assist.get("name_ru") or "").strip(),
                    "participants": self._normalize_event_participants(item),
                    "raw_data": item,
                }
            )
        return rows

    @staticmethod
    def _event_key(
        item: dict[str, Any],
        *,
        external_id: int | None,
        uid: int | None,
        seq: int | None,
    ) -> str:
        if external_id is not None:
            return f"id:{external_id}"
        if uid is not None:
            return f"uid:{uid}"
        if seq is not None:
            return f"seq:{seq}"
        event_type = item.get("type") if isinstance(item.get("type"), dict) else {}
        detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
        time_payload = item.get("time") if isinstance(item.get("time"), dict) else {}
        team_payload = item.get("team") if isinstance(item.get("team"), dict) else {}
        player = item.get("player") if isinstance(item.get("player"), dict) else {}
        assist = item.get("assist") if isinstance(item.get("assist"), dict) else {}
        identity = {
            "type": event_type.get("code"),
            "detail": detail.get("code"),
            "minute": time_payload.get("minute"),
            "extra": time_payload.get("extra"),
            "team_id": team_payload.get("id"),
            "team_side": team_payload.get("side"),
            "player_id": player.get("id"),
            "player_name": player.get("name"),
            "assist_id": assist.get("id"),
        }
        digest = hashlib.sha256(
            json.dumps(identity, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:32]
        return f"fallback:{digest}"

    def _event_team(
        self,
        match: Match,
        *,
        team_external_id: int | None,
        side: str,
    ) -> Team | None:
        for team in (match.home_team, match.away_team):
            if team is not None and team_external_id is not None and team.external_id == team_external_id:
                return team
        if side == "home":
            return match.home_team
        if side == "away":
            return match.away_team
        return None

    def _normalize_event_participants(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        participants = item.get("participants")
        if not isinstance(participants, list):
            return []

        rows = []
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            player = participant.get("player") if isinstance(participant.get("player"), dict) else {}
            rows.append(
                {
                    "role": str(participant.get("role") or "").strip(),
                    "player_external_id": self._to_int(player.get("id")),
                    "player_name": str(player.get("name") or "").strip(),
                    "player_name_ru": str(player.get("name_ru") or "").strip(),
                    "raw_data": participant,
                }
            )
        return rows

    def _sync_statistics_payload(self, match: Match, payload: dict[str, Any]) -> dict:
        statistics = payload.get("statistics") if isinstance(payload, dict) else None
        if not isinstance(statistics, dict) or not statistics.get("available"):
            embedded = self._embedded_statistics_payload(match.raw_data)
            if embedded is None:
                MatchStatistic.objects.filter(match=match).delete()
                return {
                    "status": "skipped",
                    "reason": "unavailable",
                    "external_id": match.external_id,
                }
            statistics = embedded

        rows = self._normalize_statistics_rows(statistics)
        now = timezone.now()
        if not rows:
            MatchStatistic.objects.filter(match=match).delete()
            return {
                "status": "skipped",
                "reason": "empty",
                "external_id": match.external_id,
            }

        active_keys = {(row["period_code"], row["stat_code"]) for row in rows}
        with transaction.atomic():
            for row in rows:
                MatchStatistic.objects.update_or_create(
                    match=match,
                    period_code=row["period_code"],
                    stat_code=row["stat_code"],
                    defaults={
                        "period_name": row["period_name"],
                        "stat_name": row["stat_name"],
                        "stat_name_ru": row["stat_name_ru"],
                        "category": row["category"],
                        "unit": row["unit"],
                        "value_type": row["value_type"],
                        "home_value": row["home_value"],
                        "away_value": row["away_value"],
                        "home_display": row["home_display"],
                        "away_display": row["away_display"],
                        "sort_order": row["sort_order"],
                        "raw_data": row["raw_data"],
                        "fetched_at": now,
                    },
                )
            stale_rows = MatchStatistic.objects.filter(match=match)
            for period_code, stat_code in active_keys:
                stale_rows = stale_rows.exclude(period_code=period_code, stat_code=stat_code)
            stale_rows.delete()

        raw_data = match.raw_data if isinstance(match.raw_data, dict) else {}
        raw_data = {**raw_data, "statistics": statistics}
        Match.objects.filter(pk=match.pk).update(raw_data=raw_data, updated_at=now)
        return {
            "status": "ok",
            "external_id": match.external_id,
            "rows": len(rows),
        }

    def _sync_embedded_statistics(self, match: Match, payload: dict[str, Any]) -> dict | None:
        statistics = self._embedded_statistics_payload(payload)
        if statistics is None:
            return None
        return self._sync_statistics_payload(match, {"statistics": statistics})

    @staticmethod
    def _embedded_statistics_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        for key in ("statistics", "player_statistics", "players"):
            section = payload.get(key)
            if (
                isinstance(section, dict)
                and section.get("available")
                and isinstance(section.get("items"), list)
            ):
                return section
        return None

    def _normalize_statistics_rows(self, statistics: dict[str, Any]) -> list[dict[str, Any]]:
        items = statistics.get("items")
        if not isinstance(items, list):
            return []

        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for side_item in items:
            if not isinstance(side_item, dict):
                continue
            side = str(side_item.get("side") or "").strip().lower()
            if side not in {"home", "away"}:
                continue
            team = side_item.get("team") if isinstance(side_item.get("team"), dict) else {}
            stats = side_item.get("stats")
            if not isinstance(stats, list):
                continue
            for stat in stats:
                if not isinstance(stat, dict):
                    continue
                stat_type = stat.get("type") if isinstance(stat.get("type"), dict) else {}
                stat_code = str(stat_type.get("code") or "").strip()
                if not stat_code:
                    continue
                period_code = str(stat.get("period_code") or "").strip()
                period = stat.get("period") if isinstance(stat.get("period"), dict) else {}
                key = (period_code, stat_code)
                row = merged.setdefault(
                    key,
                    {
                        "period_code": period_code,
                        "period_name": str(period.get("name_ru") or period.get("name") or ""),
                        "stat_code": stat_code,
                        "stat_name": str(stat_type.get("name") or ""),
                        "stat_name_ru": self._stat_label_ru(stat_code, stat_type),
                        "category": str(stat_type.get("category") or ""),
                        "unit": str(stat_type.get("unit") or ""),
                        "value_type": str(stat_type.get("value_type") or ""),
                        "home_value": None,
                        "away_value": None,
                        "home_display": "",
                        "away_display": "",
                        "sort_order": STAT_SORT_ORDER.get(stat_code, 100),
                        "raw_data": {
                            "home": {},
                            "away": {},
                            "type": stat_type,
                            "period": period,
                        },
                    },
                )
                value = stat.get("value")
                row[f"{side}_value"] = self._decimal_value(value)
                row[f"{side}_display"] = self._display_value(value)
                row["raw_data"][side] = {
                    "team": team,
                    "stat": stat,
                }

        return [
            row
            for row in merged.values()
            if row["home_display"] != "" and row["away_display"] != ""
        ]

    @staticmethod
    def _stat_label_ru(stat_code: str, stat_type: dict[str, Any]) -> str:
        if stat_code in STAT_LABELS_RU:
            return STAT_LABELS_RU[stat_code]
        name = str(stat_type.get("name_ru") or stat_type.get("name") or stat_code).strip()
        if not name:
            return stat_code
        label = name[:1].upper() + name[1:]
        if stat_type.get("unit") == "percent" and "%" not in label:
            label = f"{label}, %"
        return label

    @staticmethod
    def _decimal_value(value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value).replace("%", "").replace(",", "."))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _display_value(value: Any) -> str:
        if value in (None, ""):
            return ""
        number = MatchSyncService._decimal_value(value)
        if number is None:
            return str(value)
        if number == number.to_integral():
            return str(int(number))
        return str(number.normalize()).replace(".", ",")

    def _match_defaults(
        self,
        payload: dict[str, Any],
        scope: str,
        *,
        sport_fallback: Sport | None = None,
    ) -> dict[str, Any]:
        league = payload.get("league") or {}
        country = league.get("country") or {}
        teams = payload.get("teams") or {}
        home_team = teams.get("home") or {}
        away_team = teams.get("away") or {}
        venue_payload = payload.get("venue") or {}

        sport = self._sync_sport(payload, fallback=sport_fallback)
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

    def _sync_sport(self, payload: dict[str, Any], *, fallback: Sport | None = None) -> Sport:
        meta = self._sport_meta(payload)
        sport_id = self._to_int(meta.get("id") or payload.get("sport_id"))
        if sport_id is None and fallback is not None:
            return fallback

        code = str(
            meta.get("code")
            or getattr(fallback, "code", "")
            or (f"sport-{sport_id}" if sport_id is not None else "football")
        ).lower()
        if sport_id is None and code == "football":
            sport_id = self._configured_sport_id(code) or 2
        name = str(meta.get("name") or getattr(fallback, "name", "") or code.title())
        name_ru = str(meta.get("name_ru") or getattr(fallback, "name_ru", "") or name)
        remote_image_url = str(meta.get("image_url") or "")
        raw_data = {"sport_id": sport_id, **meta}
        cache_key: tuple[str, int | str] = ("id", sport_id) if sport_id is not None else ("code", code)
        cached = self._sport_cache.get(cache_key)
        if cached is not None:
            return cached

        if sport_id is not None:
            sport = Sport.objects.filter(provider=Provider.NEUROKEFF, external_id=sport_id).first()
            if sport is not None:
                update_fields = []
                for field, value in (
                    ("code", code),
                    ("name", name),
                    ("name_ru", name_ru),
                    ("raw_data", raw_data),
                ):
                    if getattr(sport, field) != value:
                        setattr(sport, field, value)
                        update_fields.append(field)
                if remote_image_url and sport.remote_image_url != remote_image_url:
                    sport.remote_image_url = remote_image_url
                    update_fields.append("remote_image_url")
                if update_fields:
                    sport.save(update_fields=update_fields)
                self._schedule_sport_image_download(sport, remote_image_url)
                self._sport_cache[cache_key] = sport
                return sport

        sport = Sport.objects.filter(code=code).first()
        if sport is not None:
            update_fields = []
            if sport.provider != Provider.NEUROKEFF:
                sport.provider = Provider.NEUROKEFF
                update_fields.append("provider")
            if sport_id is not None and sport.external_id != sport_id:
                sport.external_id = sport_id
                update_fields.append("external_id")
            for field, value in (
                ("name", name),
                ("name_ru", name_ru),
                ("raw_data", raw_data),
            ):
                if getattr(sport, field) != value:
                    setattr(sport, field, value)
                    update_fields.append(field)
            if remote_image_url and sport.remote_image_url != remote_image_url:
                sport.remote_image_url = remote_image_url
                update_fields.append("remote_image_url")
            if update_fields:
                sport.save(update_fields=update_fields)
            self._schedule_sport_image_download(sport, remote_image_url)
            self._sport_cache[cache_key] = sport
            return sport

        if sport_id is None:
            sport = Sport.objects.create(
                provider=Provider.NEUROKEFF,
                external_id=None,
                code=code,
                name=name,
                name_ru=name_ru,
                remote_image_url=remote_image_url,
                raw_data=raw_data,
            )
            self._schedule_sport_image_download(sport, remote_image_url)
            self._sport_cache[cache_key] = sport
            return sport

        sport_defaults = {
            "code": code,
            "name": name,
            "name_ru": name_ru,
            "raw_data": raw_data,
        }
        if remote_image_url:
            sport_defaults["remote_image_url"] = remote_image_url
        sport, _ = Sport.objects.update_or_create(
            provider=Provider.NEUROKEFF,
            external_id=sport_id,
            defaults=sport_defaults,
        )
        self._schedule_sport_image_download(sport, remote_image_url)
        self._sport_cache[cache_key] = sport
        return sport

    @staticmethod
    def _schedule_sport_image_download(sport: Sport, remote_image_url: str) -> None:
        if not remote_image_url:
            return
        transaction.on_commit(
            partial(
                sync_entity_logo,
                sport,
                field_name="image",
                remote_url=remote_image_url,
                target_name=sport_image_upload_path(sport, ""),
            )
        )

    def _sport_meta(self, payload: dict[str, Any]) -> dict[str, Any]:
        meta = payload.get("_sport_meta")
        if isinstance(meta, dict):
            return {
                "id": self._to_int(meta.get("id")),
                "code": str(meta.get("code") or ""),
                "name": str(meta.get("name") or ""),
                "name_ru": str(meta.get("name_ru") or meta.get("name") or ""),
                "image_url": str(
                    meta.get("image")
                    or meta.get("logo")
                    or meta.get("icon")
                    or meta.get("image_url")
                    or ""
                ),
            }

        sport_payload = payload.get("sport") or {}
        if not isinstance(sport_payload, dict):
            sport_payload = {}
        sport_id = self._to_int(payload.get("sport_id") or sport_payload.get("id"))
        configured = self._configured_sport_meta(sport_id=sport_id)
        code = (
            configured.get("code")
            or sport_payload.get("code")
            or payload.get("sport_code")
            or sport_payload.get("slug")
            or ""
        )
        name = configured.get("name") or self._localized(sport_payload.get("name"), "en")
        name_ru = configured.get("name_ru") or self._localized(sport_payload.get("name"), "ru")
        image_url = (
            configured.get("image")
            or configured.get("logo")
            or configured.get("icon")
            or sport_payload.get("image")
            or sport_payload.get("logo")
            or sport_payload.get("icon")
            or ""
        )
        return {
            "id": sport_id,
            "code": str(code or ""),
            "name": str(name or ""),
            "name_ru": str(name_ru or name or ""),
            "image_url": str(image_url or ""),
        }

    @staticmethod
    def _configured_sport_meta(*, sport_id: int | None) -> dict[str, Any]:
        if sport_id is None:
            return {}
        for sport in getattr(settings, "NEUROKEFF_SPORTS", []):
            if not isinstance(sport, dict):
                continue
            try:
                configured_id = int(sport.get("id"))
            except (TypeError, ValueError):
                continue
            if configured_id == sport_id:
                return sport
        return {}

    @staticmethod
    def _configured_sport_id(code: str) -> int | None:
        for sport in getattr(settings, "NEUROKEFF_SPORTS", []):
            if not isinstance(sport, dict) or str(sport.get("code") or "").lower() != code:
                continue
            return MatchSyncService._to_int(sport.get("id"))
        return None

    def _sync_country(self, payload: dict[str, Any]) -> Country | None:
        external_id = self._to_int(payload.get("id"))
        if external_id is None:
            return None

        remote_logo_url = str(payload.get("logo") or "")
        country, _ = Country.objects.update_or_create(
            provider=Provider.NEUROKEFF,
            external_id=external_id,
            defaults={
                "code": str(payload.get("code") or ""),
                "name": self._localized(payload.get("name"), "en"),
                "name_ru": self._localized(payload.get("name"), "ru"),
                "remote_logo_url": remote_logo_url,
                "raw_data": payload,
            },
        )
        transaction.on_commit(
            partial(
                sync_entity_logo,
                country,
                field_name="logo",
                remote_url=remote_logo_url,
                target_name=country_logo_upload_path(country, ""),
            )
        )
        return country

    def _sync_venue(self, payload: dict[str, Any]) -> Venue | None:
        external_id = self._to_int(payload.get("id"))
        if external_id is None:
            return None

        remote_logo_url = str(payload.get("logo") or "")
        venue, _ = Venue.objects.update_or_create(
            provider=Provider.NEUROKEFF,
            external_id=external_id,
            defaults={
                "name": self._localized(payload.get("name"), "en"),
                "name_ru": self._localized(payload.get("name"), "ru"),
                "city": self._localized(payload.get("city"), "en"),
                "city_ru": self._localized(payload.get("city"), "ru"),
                "capacity": self._to_int(payload.get("capacity")),
                "remote_logo_url": remote_logo_url,
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

        remote_logo_url = str(payload.get("logo") or "")
        league, _ = League.objects.update_or_create(
            provider=Provider.NEUROKEFF,
            external_id=external_id,
            defaults={
                "sport": sport,
                "country": country,
                "name": self._localized(payload.get("name"), "en"),
                "name_ru": self._localized(payload.get("name"), "ru"),
                "remote_logo_url": remote_logo_url,
                "gender": str(payload.get("gender") or ""),
                "age_group": str(payload.get("age_group") or ""),
                "raw_data": payload,
            },
        )
        transaction.on_commit(
            partial(
                sync_entity_logo,
                league,
                field_name="logo",
                remote_url=remote_logo_url,
                target_name=league_logo_upload_path(league, ""),
            )
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

        remote_logo_url = str(payload.get("logo") or "")
        team, _ = Team.objects.update_or_create(
            provider=Provider.NEUROKEFF,
            external_id=external_id,
            defaults={
                "sport": sport,
                "country": country,
                "name": self._localized(payload.get("name"), "en"),
                "name_ru": self._localized(payload.get("name"), "ru"),
                "remote_logo_url": remote_logo_url,
                "gender": str(payload.get("gender") or ""),
                "age_group": str(payload.get("age_group") or ""),
                "raw_data": payload,
            },
        )
        transaction.on_commit(
            partial(
                sync_entity_logo,
                team,
                field_name="logo",
                remote_url=remote_logo_url,
                target_name=team_logo_upload_path(team, ""),
            )
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
        if normalized in MatchSyncService.FINISHED_TIME_STATUSES:
            return Match.SyncScope.FINISHED
        if normalized in MatchSyncService.POSTPONED_TIME_STATUSES:
            return Match.SyncScope.POSTPONED
        if normalized in MatchSyncService.CANCELED_TIME_STATUSES:
            return Match.SyncScope.CANCELED
        if normalized in MatchSyncService.FORFEIT_TIME_STATUSES:
            return Match.SyncScope.FORFEIT
        if normalized in MatchSyncService.INTERRUPTED_TIME_STATUSES:
            return Match.SyncScope.INTERRUPTED
        if normalized in MatchSyncService.ABANDONED_TIME_STATUSES:
            return Match.SyncScope.ABANDONED

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
        if normalized in {
            "postponed",
            "postpone",
            "delayed",
            "suspended",
            "pst",
        }:
            return Match.SyncScope.POSTPONED
        if normalized in {
            "canceled",
            "cancelled",
            "cancel",
            "cncl",
            "canc",
        }:
            return Match.SyncScope.CANCELED
        if normalized in {
            "forfeit",
            "walkover",
            "technical_win",
            "technical_victory",
            "wo",
        }:
            return Match.SyncScope.FORFEIT
        if normalized in {
            "interrupted",
            "abandoned_temporarily",
            "paused",
            "stopped",
        }:
            return Match.SyncScope.INTERRUPTED
        if normalized in {
            "abandoned",
            "interrupted_final",
            "interrupted_and_not_resumed",
            "not_resumed",
        }:
            return Match.SyncScope.ABANDONED
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

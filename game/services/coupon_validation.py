from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from game.models import Match, MatchOdds, Provider
from game.services.match_sync import MatchSyncService
from game.services.odds import has_odds_payload, match_odds_defaults
from game.services.providers import NeurokeffSportsProvider
from game.services.providers.neurokeff import NeurokeffProviderError


class CouponMatchVerificationError(RuntimeError):
    """Raised when the current provider state cannot be confirmed safely."""


@dataclass
class CouponMatchVerificationSummary:
    remote_checked: bool = False
    cache_used: bool = False


def verify_matches_for_coupon(matches: list[Match]) -> CouponMatchVerificationSummary:
    """Ensure every coupon match is still prematch.

    Fresh DB rows are trusted. Stale rows are checked against Neurokeff by exact
    provider ids, so publishing a coupon does not scan prematch/live/finished
    lists across every configured sport.
    """

    summary = CouponMatchVerificationSummary()
    stale_matches: list[Match] = []
    for match in matches:
        if match.sync_scope != Match.SyncScope.PREMATCH:
            raise ValidationError(
                f"Матч «{match.home_team_name} — {match.away_team_name}» уже не является предстоящим."
            )

        if _is_stale(match):
            stale_matches.append(match)

    if not stale_matches:
        return summary

    payloads, from_cache = _fetch_remote_matches_info(stale_matches)
    summary.remote_checked = True
    summary.cache_used = from_cache

    by_external_id = _payloads_by_external_id(payloads)
    for match in stale_matches:
        payload = by_external_id.get(match.external_id)

        if payload is None:
            raise CouponMatchVerificationError(
                f"Не удалось подтвердить актуальный статус матча «{match.home_team_name} — {match.away_team_name}». Попробуйте ещё раз."
            )

        scope = MatchSyncService._scope_from_payload(
            payload,
            default=Match.SyncScope.PREMATCH,
        )
        _refresh_local_match_state(match, scope, payload)
        if scope != Match.SyncScope.PREMATCH:
            raise ValidationError(
                f"Матч «{match.home_team_name} — {match.away_team_name}» уже начался или завершён. Обновите купон."
            )

    return summary


def _is_stale(match: Match) -> bool:
    stale_seconds = max(int(getattr(settings, "COUPON_MATCH_STALE_SECONDS", 60)), 1)
    if not match.last_seen_at:
        return True
    return timezone.now() - match.last_seen_at > timedelta(seconds=stale_seconds)


def _fetch_remote_matches_info(matches: list[Match]) -> tuple[list[dict[str, Any]], bool]:
    external_ids = sorted(
        {
            int(match.external_id)
            for match in matches
            if match.external_id not in (None, "")
        }
    )
    if len(external_ids) != len({match.pk for match in matches}):
        raise CouponMatchVerificationError(
            "Не удалось подтвердить актуальный статус одного из матчей. Попробуйте ещё раз."
        )

    cache_seconds = max(int(getattr(settings, "COUPON_MATCH_STATE_CACHE_SECONDS", 10)), 1)
    ids_key = ",".join(map(str, external_ids))
    cache_key = f"coupon:match-info:{Provider.NEUROKEFF}:{ids_key}"

    cached: Any = None
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None

    if isinstance(cached, list):
        return cached, True

    provider = NeurokeffSportsProvider()
    try:
        payloads = provider.fetch_matches_info(external_ids)
    except NeurokeffProviderError as exc:
        raise CouponMatchVerificationError("Сервис спортивных данных временно недоступен.") from exc

    try:
        cache.set(cache_key, payloads, timeout=cache_seconds)
    except Exception:
        pass

    return payloads, False


def _payloads_by_external_id(payloads: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    by_external_id: dict[int, dict[str, Any]] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        try:
            external_id = int(payload.get("id"))
        except (TypeError, ValueError):
            continue
        by_external_id[external_id] = payload
    return by_external_id


def _refresh_local_match_state(match: Match, scope: str, payload: dict[str, Any]) -> None:
    now = timezone.now()
    match.sync_scope = scope
    match.time_status = str(payload.get("time_status") or "")
    match.score = str(payload.get("score") or "")
    match.raw_data = payload
    match.last_seen_at = now

    live_minute = payload.get("live_minute")
    try:
        match.live_minute = int(live_minute) if live_minute not in (None, "") else None
    except (TypeError, ValueError):
        match.live_minute = None
    match.live_minute_label = str(payload.get("live_minute_str") or "")

    Match.objects.filter(pk=match.pk).update(
        sync_scope=match.sync_scope,
        time_status=match.time_status,
        score=match.score,
        raw_data=match.raw_data,
        last_seen_at=match.last_seen_at,
        live_minute=match.live_minute,
        live_minute_label=match.live_minute_label,
        updated_at=now,
    )
    _refresh_match_odds(match, payload.get("odds") or {})


def _refresh_match_odds(match: Match, payload: dict[str, Any]) -> None:
    if not has_odds_payload(payload):
        return
    MatchOdds.objects.update_or_create(
        match=match,
        defaults=match_odds_defaults(payload),
    )

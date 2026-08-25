from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from game.models import Match, MatchOdds, Provider
from game.services.odds import match_odds_defaults
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

    Fresh DB rows are trusted. Stale rows are checked against Neurokeff. Provider
    list responses are cached for a short period so several coupon saves do not
    fan out into identical external API requests.
    """

    summary = CouponMatchVerificationSummary()
    for match in matches:
        if match.sync_scope != Match.SyncScope.PREMATCH:
            raise ValidationError(
                f"Матч «{match.home_team_name} — {match.away_team_name}» уже не является предстоящим."
            )

        if not _is_stale(match):
            continue

        remote = _find_remote_match(match)
        summary.remote_checked = True
        summary.cache_used = summary.cache_used or remote[2]
        scope, payload, _ = remote

        if payload is None:
            raise CouponMatchVerificationError(
                f"Не удалось подтвердить актуальный статус матча «{match.home_team_name} — {match.away_team_name}». Попробуйте ещё раз."
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


def _find_remote_match(match: Match) -> tuple[str, dict[str, Any] | None, bool]:
    provider = NeurokeffSportsProvider()
    match_date = _match_local_date(match)
    cache_used = False

    lookups = (
        (Match.SyncScope.PREMATCH, match_date),
        (Match.SyncScope.LIVE, None),
        (Match.SyncScope.FINISHED, match_date),
    )

    for scope, date_value in lookups:
        payloads, from_cache = _provider_scope_payload(provider, scope, date_value)
        cache_used = cache_used or from_cache
        for payload in payloads:
            try:
                external_id = int(payload.get("id"))
            except (TypeError, ValueError, AttributeError):
                continue
            if external_id == match.external_id:
                return scope, payload, cache_used

    return Match.SyncScope.PREMATCH, None, cache_used


def _provider_scope_payload(
    provider: NeurokeffSportsProvider,
    scope: str,
    date_value: date | None,
) -> tuple[list[dict[str, Any]], bool]:
    cache_seconds = max(int(getattr(settings, "COUPON_MATCH_STATE_CACHE_SECONDS", 10)), 1)
    date_key = date_value.isoformat() if date_value else "all"
    cache_key = f"coupon:match-state:{Provider.NEUROKEFF}:{scope}:{date_key}"

    cached: Any = None
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None

    if isinstance(cached, list):
        return cached, True

    try:
        payloads = provider.fetch_matches_for_scope(scope, date_value=date_value)
    except NeurokeffProviderError as exc:
        raise CouponMatchVerificationError("Сервис спортивных данных временно недоступен.") from exc

    try:
        cache.set(cache_key, payloads, timeout=cache_seconds)
    except Exception:
        pass

    return payloads, False


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
    MatchOdds.objects.update_or_create(
        match=match,
        defaults=match_odds_defaults(payload),
    )


def _match_local_date(match: Match) -> date:
    if match.starts_at:
        return timezone.localtime(match.starts_at).date()
    return timezone.localdate()

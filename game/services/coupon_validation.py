from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from game.models import Match, MatchOdds, Provider
from game.services.bet_options import bet_option_key, match_bet_options
from game.services.match_sync import MatchSyncService
from game.services.match_timing import prediction_window_open
from game.services.odds import has_odds_payload, match_odds_defaults
from game.services.providers import NeurokeffSportsProvider
from game.services.providers.neurokeff import NeurokeffProviderError


MAX_COUPON_ITEMS = 20
PREDICTION_STAKE_MIN_COINS = Decimal("100")
PREDICTION_STAKE_MAX_COINS = Decimal("1000000")
MIN_ALLOWED_COEFFICIENT = Decimal("1.01")
MAX_ALLOWED_COEFFICIENT = Decimal("1000")
# PredictionCoupon.possible_payout is DecimalField(max_digits=12, decimal_places=2):
# the maximum stake multiplied by this value must still fit into it.
MAX_TOTAL_COEFFICIENT = Decimal("9999")


class CouponMatchVerificationError(RuntimeError):
    """Raised when the current provider state cannot be confirmed safely."""


class CouponMatchClosedError(ValidationError):
    """A coupon match has already started or has no kickoff time."""


class CouponOddsChangedError(ValidationError):
    """The coefficients the user saw differ from the current line."""

    def __init__(self, changes: list[dict[str, Any]]):
        super().__init__(
            "Коэффициенты изменились. Проверьте купон и опубликуйте прогноз ещё раз."
        )
        self.changes = changes


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


def extract_match_ids(items: list) -> list[int]:
    match_ids: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("Некорректная игра в прогнозе.")
        match_id = _positive_int(item.get("match_id"))
        if match_id is None:
            raise ValidationError("Матч не найден.")
        match_ids.append(match_id)
    return match_ids


def parse_stake(value, *, required: bool) -> Decimal:
    """Parse a coupon stake in coins.

    A published coupon needs a whole stake within the limits. Draft autosave
    keeps whatever valid amount the user is typing and stores 0 otherwise.
    """
    raw = str(value or "").replace(",", ".").strip()
    try:
        stake = Decimal(raw) if raw else None
    except (InvalidOperation, ValueError):
        stake = None
    if stake is not None and not stake.is_finite():
        stake = None

    if not required:
        if stake is None or stake <= 0 or stake > PREDICTION_STAKE_MAX_COINS:
            return Decimal("0")
        return stake

    if not raw:
        raise ValidationError("Укажите сумму ставки.")
    if stake is None:
        raise ValidationError("Укажите корректную сумму ставки.")
    if stake <= 0:
        raise ValidationError("Сумма ставки должна быть больше нуля.")
    if stake != stake.to_integral_value():
        raise ValidationError("Сумма прогноза должна быть целым числом коинов.")
    if stake < PREDICTION_STAKE_MIN_COINS:
        raise ValidationError(
            f"Минимальная сумма прогноза — {int(PREDICTION_STAKE_MIN_COINS)} коинов."
        )
    if stake > PREDICTION_STAKE_MAX_COINS:
        raise ValidationError(
            f"Максимальная сумма прогноза — {_format_int(PREDICTION_STAKE_MAX_COINS)} коинов."
        )
    return stake


def parse_confidence(value) -> int:
    try:
        confidence = int(value if value not in (None, "") else 50)
    except (TypeError, ValueError):
        raise ValidationError("Укажите уверенность от 0 до 100%.")
    if not 0 <= confidence <= 100:
        raise ValidationError("Уверенность должна быть от 0 до 100%.")
    return confidence


def validate_match_timing(matches: Iterable[Match]) -> None:
    for match in matches:
        if prediction_window_open(match):
            continue
        title = _match_title(match)
        if not match.starts_at:
            raise CouponMatchClosedError(
                f"Для матча «{title}» не указано время начала. Ставка временно недоступна."
            )
        raise CouponMatchClosedError(
            f"Матч «{title}» уже начался или скоро начнется. Добавить ставку больше нельзя."
        )


def resolve_coupon_items(
    items: list,
    matches: dict[int, Match],
    *,
    accept_changed_odds: bool,
) -> list[dict[str, Any]]:
    """Check every coupon position against the current line of its match.

    The market and selection must be an outcome the site offers for the match,
    and the coefficient always comes from MatchOdds. When the user saw a
    different coefficient, publishing is rejected with CouponOddsChangedError
    so the user can confirm the new price; draft autosave silently takes the
    current one.
    """
    odds_by_match_id = {
        odds.match_id: odds
        for odds in MatchOdds.objects.filter(match_id__in=list(matches))
    }
    options_by_match_id: dict[int, dict] = {}
    resolved: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("Некорректная игра в прогнозе.")
        match = matches.get(_positive_int(item.get("match_id")))
        if match is None:
            raise ValidationError("Матч не найден.")

        market = str(item.get("market") or "").strip()
        selection = str(item.get("selection") or "").strip()
        if not market:
            raise ValidationError("Выберите тип ставки.")
        if not selection:
            raise ValidationError("Выберите исход.")

        if match.id not in options_by_match_id:
            options_by_match_id[match.id] = match_bet_options(
                match,
                odds=odds_by_match_id.get(match.id),
            )
        option = options_by_match_id[match.id].get(bet_option_key(market, selection))
        if option is None:
            raise ValidationError(
                f"Исход «{selection[:60]}» на матч «{_match_title(match)}» сейчас недоступен. "
                "Обновите страницу и выберите ставку заново."
            )

        coefficient = option.coefficient
        if coefficient < MIN_ALLOWED_COEFFICIENT:
            raise ValidationError(
                "Коэффициент 1.00 нельзя добавлять в прогноз. Выберите доступный коэффициент выше 1.00."
            )
        if coefficient > MAX_ALLOWED_COEFFICIENT:
            raise ValidationError(
                f"Коэффициент выше {_format_int(MAX_ALLOWED_COEFFICIENT)} не принимается."
            )

        client_coefficient = _client_coefficient(item.get("coefficient"))
        if client_coefficient != coefficient:
            changes.append(
                {
                    "match_id": match.id,
                    "market": option.market,
                    "selection": option.selection,
                    "coefficient": str(coefficient),
                    "previous": str(client_coefficient) if client_coefficient is not None else "",
                }
            )

        resolved.append(
            {
                "match": match,
                "market": option.market,
                "selection": option.selection,
                "coefficient": coefficient,
            }
        )

    if changes and not accept_changed_odds:
        raise CouponOddsChangedError(changes)

    if coupon_total_coefficient(resolved) > MAX_TOTAL_COEFFICIENT:
        raise ValidationError(
            f"Общий коэффициент прогноза не может быть больше {_format_int(MAX_TOTAL_COEFFICIENT)}."
        )
    return resolved


def coupon_total_coefficient(items: list[dict[str, Any]]) -> Decimal:
    total = Decimal("1")
    for item in items:
        total *= item["coefficient"]
    return total


def _client_coefficient(value) -> Decimal | None:
    try:
        coefficient = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None
    if not coefficient.is_finite():
        return None
    return coefficient.quantize(Decimal("0.01"))


def _positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _match_title(match: Match) -> str:
    return f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}"


def _format_int(value: Decimal) -> str:
    return f"{int(value):,}".replace(",", " ")

from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon
from game.prediction_constraints import (
    MIN_ALLOWED_COEFFICIENT,
    PREDICTION_STAKE_MAX_RUB,
    PREDICTION_STAKE_MIN_RUB,
)
from game.services.coupon_validation import verify_matches_for_coupon
from game.services.match_timing import prediction_window_open
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant, TournamentPredictionEntry
from tournaments.services.join import get_active_participant
from tournaments.services.rules import TournamentRuleError, validate_tournament_coupon
from wallets.services import InsufficientBalance, charge_prediction_stake, copy_published_coupon


class TournamentCouponCreateError(ValidationError):
    pass


def create_tournament_coupon(
    *,
    user: User,
    tournament: Tournament,
    payload: dict,
) -> tuple[PredictionCoupon, TournamentCoupon]:
    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Войдите, чтобы сделать прогноз в турнире.")
    if user.role != User.Role.ANALYST:
        raise PermissionDenied("Прогнозы могут создавать только капперы.")
    if not isinstance(payload, dict):
        raise TournamentCouponCreateError("Некорректный JSON.")
    if payload.get("autosave"):
        raise TournamentCouponCreateError("Черновики турнирных прогнозов пока недоступны.")

    participant = get_active_participant(user, tournament)
    if participant is None:
        raise TournamentCouponCreateError("Подключитесь к турниру, чтобы сделать прогноз.")

    items = payload.get("items")
    if not isinstance(items, list):
        raise TournamentCouponCreateError("Передайте список матчей.")
    if not 1 <= len(items) <= 20:
        raise TournamentCouponCreateError("В прогнозе должно быть от 1 до 20 игр.")

    limits_error = _validate_payload_limits(payload)
    if limits_error:
        raise TournamentCouponCreateError(limits_error)

    timing_error = _validate_match_timing(payload)
    if timing_error:
        raise TournamentCouponCreateError(timing_error)

    match_ids = _extract_match_ids(items)
    if len(set(match_ids)) != len(items):
        raise TournamentCouponCreateError("Один матч нельзя добавить дважды.")

    matches = {
        match.id: match
        for match in Match.objects.filter(id__in=match_ids).select_related(
            "sport",
            "home_team",
            "away_team",
        )
    }
    if len(matches) != len(items):
        raise TournamentCouponCreateError("Один из матчей не найден.")

    non_prematch = [
        match for match in matches.values() if match.sync_scope != Match.SyncScope.PREMATCH
    ]
    if non_prematch:
        match = non_prematch[0]
        raise TournamentCouponCreateError(
            f"Матч «{match.home_team_name} — {match.away_team_name}» уже начался или завершен."
        )

    verify_matches_for_coupon(list(matches.values()))

    stake = _parse_stake(payload.get("stake"))
    confidence = _parse_confidence(payload.get("confidence"))
    normalized_items = [_normalize_prediction_item(item, matches) for item in items]
    validate_tournament_coupon(
        tournament,
        participant,
        confidence=confidence,
        items=normalized_items,
    )

    total_coefficient = Decimal("1")
    for item in normalized_items:
        total_coefficient *= item["coefficient"]
    possible_payout = stake * total_coefficient
    coupon_type = (
        PredictionCoupon.CouponType.EXPRESS
        if len(normalized_items) > 1
        else PredictionCoupon.CouponType.SINGLE
    )

    try:
        with transaction.atomic():
            participant = TournamentParticipant.objects.select_for_update().get(pk=participant.pk)
            validate_tournament_coupon(
                tournament,
                participant,
                confidence=confidence,
                items=normalized_items,
            )

            coupon = PredictionCoupon.objects.create(
                author=user,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                state_status=PredictionCoupon.StateStatus.PENDING,
                coupon_type=coupon_type,
                total_stake=stake,
                possible_payout=possible_payout,
                confidence=confidence,
                audience=PredictionCoupon.Audience.FREE,
                published_at=timezone.now(),
            )
            charge_prediction_stake(user, coupon, stake)

            predictions = Prediction.objects.bulk_create(
                [
                    Prediction(
                        coupon=coupon,
                        match=item["match"],
                        market=item["market"],
                        selection=item["selection"],
                        coefficient=item["coefficient"],
                        stake=stake,
                    )
                    for item in normalized_items
                ]
            )
            tournament_coupon = TournamentCoupon.objects.create(
                tournament=tournament,
                participant=participant,
                coupon=coupon,
            )
            TournamentPredictionEntry.objects.bulk_create(
                [
                    TournamentPredictionEntry(
                        tournament=tournament,
                        participant=participant,
                        tournament_coupon=tournament_coupon,
                        prediction=prediction,
                        match=prediction.match,
                    )
                    for prediction in predictions
                ]
            )
            copy_published_coupon(coupon)
    except IntegrityError as exc:
        raise TournamentCouponCreateError(
            "В рамках турнира на один матч можно сделать только один прогноз."
        ) from exc
    except TournamentRuleError:
        raise
    except InsufficientBalance:
        raise

    return coupon, tournament_coupon


def _validate_match_timing(payload: dict) -> str:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return ""

    match_ids = []
    for item in items:
        if not isinstance(item, dict):
            continue
        match_id = _to_positive_int(item.get("match_id"))
        if match_id:
            match_ids.append(match_id)

    if not match_ids:
        return ""

    matches = Match.objects.filter(id__in=set(match_ids)).select_related(
        "home_team",
        "away_team",
    )
    for match in matches:
        if prediction_window_open(match):
            continue
        title = f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}"
        if not match.starts_at:
            return f"Для матча «{title}» не указано время начала. Ставка временно недоступна."
        return f"Матч «{title}» уже начался или скоро начнется. Добавить ставку больше нельзя."
    return ""


def _validate_payload_limits(payload: dict) -> str:
    raw_stake = str(payload.get("stake") or "").replace(",", ".").strip()
    if raw_stake:
        try:
            stake = Decimal(raw_stake)
        except (InvalidOperation, ValueError):
            stake = None
        if stake is not None:
            if stake < PREDICTION_STAKE_MIN_RUB:
                return f"Минимальная сумма прогноза — {int(PREDICTION_STAKE_MIN_RUB)} ₽."
            if stake > PREDICTION_STAKE_MAX_RUB:
                return f"Максимальная сумма прогноза — {int(PREDICTION_STAKE_MAX_RUB):,} ₽.".replace(",", " ")

    items = payload.get("items")
    if not isinstance(items, list):
        return ""

    for item in items:
        if not isinstance(item, dict):
            continue
        raw_coefficient = str(item.get("coefficient") or "").replace(",", ".").strip()
        if not raw_coefficient:
            continue
        try:
            coefficient = Decimal(raw_coefficient)
        except (InvalidOperation, ValueError):
            continue
        if coefficient < MIN_ALLOWED_COEFFICIENT:
            return "Коэффициент 1.00 нельзя добавлять в прогноз. Выберите доступный коэффициент выше 1.00."
    return ""


def _extract_match_ids(items: list[dict]) -> list[int]:
    match_ids: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            raise TournamentCouponCreateError("Некорректная игра в прогнозе.")
        match_id = _to_positive_int(item.get("match_id"))
        if match_id is None:
            raise TournamentCouponCreateError("Матч не найден.")
        match_ids.append(match_id)
    return match_ids


def _parse_stake(value) -> Decimal:
    raw = str(value or "").replace(",", ".").strip()
    if not raw:
        raise TournamentCouponCreateError("Укажите сумму ставки.")
    try:
        stake = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise TournamentCouponCreateError("Укажите корректную сумму ставки.")
    if stake <= 0:
        raise TournamentCouponCreateError("Сумма ставки должна быть больше нуля.")
    return stake


def _parse_confidence(value) -> int:
    try:
        confidence = int(value if value not in (None, "") else 50)
    except (TypeError, ValueError):
        raise TournamentCouponCreateError("Укажите уверенность от 0 до 100%.")
    if not 0 <= confidence <= 100:
        raise TournamentCouponCreateError("Уверенность должна быть от 0 до 100%.")
    return confidence


def _normalize_prediction_item(item: dict, matches: dict[int, Match]) -> dict:
    if not isinstance(item, dict):
        raise TournamentCouponCreateError("Некорректная игра в прогнозе.")

    match_id = _to_positive_int(item.get("match_id"))
    if match_id is None or match_id not in matches:
        raise TournamentCouponCreateError("Матч не найден.")

    market = str(item.get("market") or "").strip()
    selection = str(item.get("selection") or "").strip()
    coefficient_raw = str(item.get("coefficient") or "").replace(",", ".").strip()

    if not market:
        raise TournamentCouponCreateError("Выберите тип ставки.")
    if not selection:
        raise TournamentCouponCreateError("Выберите исход.")

    try:
        coefficient = Decimal(coefficient_raw)
    except (InvalidOperation, ValueError):
        raise TournamentCouponCreateError("Укажите коэффициент.")

    if coefficient <= 0:
        raise TournamentCouponCreateError("Коэффициент должен быть больше нуля.")

    return {
        "match": matches[match_id],
        "market": market[:80],
        "selection": selection[:120],
        "coefficient": coefficient,
    }


def _to_positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon
from game.services.coupon_validation import (
    MAX_COUPON_ITEMS,
    coupon_total_coefficient,
    extract_match_ids,
    parse_confidence,
    parse_stake,
    resolve_coupon_items,
    validate_match_timing,
    verify_matches_for_coupon,
)
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant, TournamentPredictionEntry
from tournaments.services.join import get_active_participant
from tournaments.services.rules import TournamentRuleError, validate_tournament_coupon
from wallets.services import InsufficientCoins, charge_prediction_stake


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
    if not 1 <= len(items) <= MAX_COUPON_ITEMS:
        raise TournamentCouponCreateError(f"В прогнозе должно быть от 1 до {MAX_COUPON_ITEMS} игр.")

    match_ids = extract_match_ids(items)
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

    stake = parse_stake(payload.get("stake"), required=True)
    confidence = parse_confidence(payload.get("confidence"))
    validate_match_timing(matches.values())
    verify_matches_for_coupon(list(matches.values()))

    normalized_items = resolve_coupon_items(items, matches, accept_changed_odds=False)
    validate_tournament_coupon(
        tournament,
        participant,
        confidence=confidence,
        items=normalized_items,
    )

    possible_payout = stake * coupon_total_coefficient(normalized_items)
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
                        outcome_code=item["outcome_code"],
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
    except IntegrityError as exc:
        raise TournamentCouponCreateError(
            "В рамках турнира на один матч можно сделать только один прогноз."
        ) from exc
    except TournamentRuleError:
        raise
    except InsufficientCoins:
        raise

    return coupon, tournament_coupon

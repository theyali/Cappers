"""Tournament predictions go through the shared coupon: the capper picks a tournament in the coupon,
the coupon is checked against the tournament's rules and is published as a rich prediction."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from game.models import PredictionCoupon
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant, TournamentPredictionEntry
from tournaments.services.rules import TournamentRuleError, validate_tournament_coupon


TOURNAMENT_QUICK_PUBLISH_MESSAGE = (
    "В турнирах публикуются только расширенные прогнозы с названием и описанием. "
    "Откройте расширенный прогноз."
)


class TournamentCouponCreateError(ValidationError):
    pass


def predictable_tournaments(user) -> list[Tournament]:
    """Live published tournaments where the user is an active participant."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_analyst", False):
        return []
    now = timezone.now()
    return list(
        Tournament.objects.filter(
            status=Tournament.Status.PUBLISHED,
            starts_at__lte=now,
            ends_at__gte=now,
            participants__user=user,
            participants__status=TournamentParticipant.Status.ACTIVE,
        )
        .prefetch_related("allowed_sports")
        .order_by("ends_at", "id")
        .distinct()
    )


def tournament_rules(user, tournaments: list[Tournament] | None = None) -> list[dict]:
    """What the coupon needs to filter matches and mark positions for each of the user's tournaments."""
    tournaments = predictable_tournaments(user) if tournaments is None else tournaments
    used = {}
    for tournament_id, match_id in TournamentPredictionEntry.objects.filter(
        tournament__in=tournaments,
        participant__user=user,
        tournament_coupon__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).values_list("tournament_id", "match_id"):
        used.setdefault(tournament_id, []).append(match_id)
    return [
        {
            "id": tournament.pk,
            "title": tournament.title,
            "sports": [sport.code for sport in tournament.allowed_sports.all()],
            "sport_names": [sport.name_ru or sport.name for sport in tournament.allowed_sports.all()],
            "min_coefficient": float(tournament.min_coefficient or 0),
            "min_confidence": tournament.min_confidence or 0,
            "coupon_type": tournament.coupon_type_rule,
            "ends_at": tournament.ends_at.isoformat(),
            "used_match_ids": used.get(tournament.pk, []),
        }
        for tournament in tournaments
    ]


def resolve_tournament_choice(user, value) -> Tournament | None:
    """The tournament chosen in the coupon, if the user may still predict in it."""
    if value in (None, ""):
        return None
    try:
        tournament_id = int(value)
    except (TypeError, ValueError) as exc:
        raise TournamentCouponCreateError("Выберите турнир из списка.") from exc
    tournament = next((item for item in predictable_tournaments(user) if item.pk == tournament_id), None)
    if tournament is None:
        raise TournamentCouponCreateError("Этот турнир недоступен: вы не участвуете в нём или он не идёт.")
    return tournament


def attach_coupon_to_tournament(coupon: PredictionCoupon, tournament: Tournament) -> TournamentCoupon:
    """Check a coupon being published against the tournament's rules and enter it; call inside the publish
    transaction so a refused coupon is not published either."""
    participant = (
        TournamentParticipant.objects.select_for_update()
        .filter(tournament=tournament, user_id=coupon.author_id, status=TournamentParticipant.Status.ACTIVE)
        .first()
    )
    if participant is None:
        raise TournamentRuleError("Подключитесь к турниру, чтобы сделать прогноз.")
    predictions = list(coupon.predictions.select_related("match__sport", "match__home_team", "match__away_team"))
    validate_tournament_coupon(
        tournament,
        participant,
        confidence=coupon.confidence,
        items=[{"match": prediction.match, "coefficient": prediction.coefficient} for prediction in predictions],
    )
    try:
        with transaction.atomic():
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
    return tournament_coupon

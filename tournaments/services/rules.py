from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.utils import timezone

from game.models import Match, PredictionCoupon
from tournaments.models import Tournament, TournamentParticipant, TournamentPredictionEntry


class TournamentRuleError(ValidationError):
    pass


def validate_participant_can_predict(
    tournament: Tournament,
    participant: TournamentParticipant,
) -> None:
    if tournament.status != Tournament.Status.PUBLISHED:
        raise TournamentRuleError("Турнир недоступен для прогнозов.")
    now = timezone.now()
    if now < tournament.starts_at:
        raise TournamentRuleError("Турнир ещё не начался.")
    if now > tournament.ends_at:
        raise TournamentRuleError("Турнир уже завершён.")
    if participant.tournament_id != tournament.id:
        raise TournamentRuleError("Участник относится к другому турниру.")
    if participant.status != TournamentParticipant.Status.ACTIVE:
        raise TournamentRuleError("Подключитесь к турниру, чтобы сделать прогноз.")


def validate_tournament_coupon(
    tournament: Tournament,
    participant: TournamentParticipant,
    *,
    confidence: int,
    items: list[dict],
) -> None:
    validate_participant_can_predict(tournament, participant)

    if confidence < tournament.min_confidence:
        raise TournamentRuleError(
            f"Минимальная уверенность для турнира — {tournament.min_confidence}%."
        )

    if tournament.coupon_type_rule == Tournament.CouponTypeRule.SINGLE and len(items) != 1:
        raise TournamentRuleError("В этом турнире доступны только одиночные прогнозы.")
    if tournament.coupon_type_rule == Tournament.CouponTypeRule.EXPRESS and len(items) < 2:
        raise TournamentRuleError("В этом турнире доступны только экспрессы.")

    _validate_min_coefficients(tournament, items)
    _validate_allowed_sports(tournament, items)
    _validate_match_not_used(tournament, participant, items)


def _validate_min_coefficients(tournament: Tournament, items: list[dict]) -> None:
    min_coefficient = Decimal(tournament.min_coefficient or 0)
    if min_coefficient <= 0:
        return

    for item in items:
        coefficient = Decimal(item["coefficient"])
        if coefficient < min_coefficient:
            raise TournamentRuleError(
                f"Минимальный коэффициент для турнира — {min_coefficient}."
            )


def _validate_allowed_sports(tournament: Tournament, items: list[dict]) -> None:
    allowed_sport_ids = set(tournament.allowed_sports.values_list("id", flat=True))
    if not allowed_sport_ids:
        return

    for item in items:
        match = item["match"]
        if match.sport_id not in allowed_sport_ids:
            sport_name = match.sport.name_ru or match.sport.name if match.sport else "этот спорт"
            raise TournamentRuleError(f"В этом турнире недоступен {sport_name}.")


def _validate_match_not_used(
    tournament: Tournament,
    participant: TournamentParticipant,
    items: list[dict],
) -> None:
    match_ids = [item["match"].id for item in items]
    used_match_ids = set(
        TournamentPredictionEntry.objects.filter(
            tournament=tournament,
            participant=participant,
            match_id__in=match_ids,
            tournament_coupon__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        ).values_list("match_id", flat=True)
    )
    if not used_match_ids:
        return

    used_matches: QuerySet[Match] = Match.objects.filter(id__in=used_match_ids).select_related(
        "home_team",
        "away_team",
    )
    used_titles = [
        f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}"
        for match in used_matches
    ]
    raise TournamentRuleError(
        "В рамках турнира на один матч можно сделать только один прогноз: "
        + ", ".join(used_titles)
        + "."
    )

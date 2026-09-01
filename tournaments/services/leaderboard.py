from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from game.models import PredictionCoupon
from tournaments.models import (
    Tournament,
    TournamentAchievement,
    TournamentCoupon,
    TournamentParticipant,
    TournamentResult,
)
from wallets.models import RealBalanceTransaction
from wallets.services import credit_real_balance


MONEY_STEP = Decimal("0.01")
PERCENT_STEP = Decimal("0.01")


def tournament_leaderboard(tournament: Tournament) -> list[dict]:
    rows = _empty_rows(tournament)
    coupons = (
        TournamentCoupon.objects.filter(
            tournament=tournament,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related(
            "participant__user",
            "coupon",
        )
        .order_by("created_at", "id")
    )

    for tournament_coupon in coupons:
        participant_id = tournament_coupon.participant_id
        if participant_id not in rows:
            rows[participant_id] = _empty_row(tournament_coupon.participant)
        _apply_coupon(rows[participant_id], tournament_coupon.coupon)

    normalized_rows = []
    for row in rows.values():
        row["total_stake"] = _money(row["total_stake"])
        row["profit"] = _money(row["profit"])
        row["roi_percent"] = _percent(row["profit"], row["total_stake"])
        normalized_rows.append(row)

    ordered = sorted(
        normalized_rows,
        key=lambda row: (
            row["profit"],
            row["roi_percent"],
            row["wins_count"],
            row["coupons_count"],
            -row["participant"].joined_at.timestamp(),
        ),
        reverse=True,
    )
    for index, row in enumerate(ordered, start=1):
        row["rank"] = index
    return ordered


@transaction.atomic
def finalize_tournament_results(tournament: Tournament) -> list[TournamentResult]:
    if timezone.now() <= tournament.ends_at:
        raise ValidationError("Итоги можно зафиксировать только после окончания турнира.")

    rows = tournament_leaderboard(tournament)
    TournamentResult.objects.filter(tournament=tournament).delete()
    results = [
        TournamentResult(
            tournament=tournament,
            participant=row["participant"],
            rank=row["rank"],
            coupons_count=row["coupons_count"],
            wins_count=row["wins_count"],
            losses_count=row["losses_count"],
            refunds_count=row["refunds_count"],
            pending_count=row["pending_count"],
            total_stake=row["total_stake"],
            profit=row["profit"],
            roi_percent=row["roi_percent"],
            prize_amount=prize_for_rank(tournament, row["rank"]),
            achievement=achievement_for_rank(tournament, row["rank"]),
        )
        for row in rows
    ]
    created_results = list(TournamentResult.objects.bulk_create(results))
    for result in created_results:
        if result.prize_amount <= 0:
            continue
        credit_real_balance(
            result.participant.user,
            result.prize_amount,
            RealBalanceTransaction.Kind.TOURNAMENT_PRIZE,
            related_obj=tournament,
            note=f"{result.rank} место в турнире «{tournament.title}»",
        )
    return created_results


def prize_for_rank(tournament: Tournament, rank: int) -> Decimal:
    if rank == 1:
        return _money(tournament.prize_first)
    if rank == 2:
        return _money(tournament.prize_second)
    if rank == 3:
        return _money(tournament.prize_third)
    return Decimal("0.00")


def achievement_for_rank(tournament: Tournament, rank: int) -> TournamentAchievement | None:
    kind_by_rank = {
        1: TournamentAchievement.Kind.FIRST_PLACE,
        2: TournamentAchievement.Kind.SECOND_PLACE,
        3: TournamentAchievement.Kind.THIRD_PLACE,
    }
    kind = kind_by_rank.get(rank)
    if not kind:
        return None
    return tournament.achievements.filter(kind=kind).order_by("sort_order", "id").first()


def _empty_rows(tournament: Tournament) -> dict[int, dict]:
    participants = (
        TournamentParticipant.objects.filter(tournament=tournament)
        .select_related("user")
        .order_by("joined_at", "id")
    )
    return {participant.id: _empty_row(participant) for participant in participants}


def _empty_row(participant: TournamentParticipant) -> dict:
    return {
        "rank": 0,
        "participant": participant,
        "user": participant.user,
        "coupons_count": 0,
        "wins_count": 0,
        "losses_count": 0,
        "refunds_count": 0,
        "pending_count": 0,
        "total_stake": Decimal("0"),
        "profit": Decimal("0"),
        "roi_percent": Decimal("0"),
    }


def _apply_coupon(row: dict, coupon: PredictionCoupon) -> None:
    row["coupons_count"] += 1
    row["total_stake"] += Decimal(coupon.total_stake or 0)
    if coupon.state_status == PredictionCoupon.StateStatus.WIN:
        row["wins_count"] += 1
        row["profit"] += Decimal(coupon.possible_payout or 0) - Decimal(coupon.total_stake or 0)
    elif coupon.state_status == PredictionCoupon.StateStatus.LOSE:
        row["losses_count"] += 1
        row["profit"] -= Decimal(coupon.total_stake or 0)
    elif coupon.state_status == PredictionCoupon.StateStatus.REFUND:
        row["refunds_count"] += 1
    else:
        row["pending_count"] += 1


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("0.00")
    return (numerator / denominator * Decimal("100")).quantize(
        PERCENT_STEP,
        rounding=ROUND_HALF_UP,
    )


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)

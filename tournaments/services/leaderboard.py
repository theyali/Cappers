import logging
from decimal import Decimal, ROUND_HALF_UP

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from game.models import PredictionCoupon
from tournaments.models import (
    Tournament,
    TournamentAchievement,
    TournamentCoupon,
    TournamentParticipant,
    TournamentPrize,
    TournamentResult,
)


MONEY_STEP = Decimal("0.01")
PERCENT_STEP = Decimal("0.01")
TOURNAMENT_LEADERBOARD_CACHE_TTL = 60

logger = logging.getLogger(__name__)


def _leaderboard_cache_key(tournament: Tournament) -> str:
    return f"tournaments:leaderboard:v3:{tournament.pk}"


def tournament_leaderboard(
    tournament: Tournament,
    *,
    use_cache: bool = True,
) -> list[dict]:
    if tournament.finalized_at:
        # Finalized results are frozen: later resettlements do not move places or prizes.
        return _final_rows(tournament)

    cache_key = _leaderboard_cache_key(tournament)
    if use_cache:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    rows = _empty_rows(tournament)
    coupons = (
        TournamentCoupon.objects.filter(
            tournament=tournament,
            participant__status=TournamentParticipant.Status.ACTIVE,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related(
            "participant__user",
            "participant__user__analyst_profile",
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

    if use_cache:
        cache.set(cache_key, ordered, TOURNAMENT_LEADERBOARD_CACHE_TTL)
    return ordered


@transaction.atomic
def finalize_tournament_results(tournament: Tournament) -> list[TournamentResult]:
    """Fix places and award prizes once, after every tournament coupon is settled."""
    tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)
    if tournament.finalized_at:
        raise ValidationError("Итоги турнира уже зафиксированы.")
    if timezone.now() <= tournament.ends_at:
        raise ValidationError("Итоги можно зафиксировать только после окончания турнира.")
    pending_count = pending_tournament_coupons(tournament).count()
    if pending_count:
        raise ValidationError(
            f"Не рассчитано турнирных купонов: {pending_count}. "
            "Итоги можно зафиксировать после расчёта всех купонов."
        )

    rows = tournament_leaderboard(tournament, use_cache=False)
    prizes = {row["rank"]: prize_for_rank(tournament, row["rank"]) for row in rows}
    for row in rows:
        if prizes[row["rank"]] > 0 and not row["user"].is_analyst:
            raise ValidationError(
                f"Денежный приз за {row['rank']} место не может получить @{row['user'].username}: "
                "реальный баланс есть только у капперов. Дисквалифицируйте участника "
                "и зафиксируйте итоги снова."
            )
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
            prize_amount=prizes[row["rank"]],
            achievement=achievement_for_rank(tournament, row["rank"]),
        )
        for row in rows
    ]
    created_results = list(TournamentResult.objects.bulk_create(results))
    from tournaments.services.rewards import award_tournament_prizes

    award_tournament_prizes(tournament, results=created_results)
    tournament.finalized_at = timezone.now()
    tournament.save(update_fields=("finalized_at", "updated_at"))
    cache.delete(_leaderboard_cache_key(tournament))
    return created_results


def finalize_finished_tournaments() -> dict:
    """Finalize published tournaments that are over and have no unsettled coupons."""
    finalized = waiting = errors = 0
    tournaments = Tournament.objects.filter(
        status=Tournament.Status.PUBLISHED,
        finalized_at__isnull=True,
        ends_at__lt=timezone.now(),
    ).order_by("ends_at", "id")
    for tournament in tournaments:
        if pending_tournament_coupons(tournament).exists():
            waiting += 1
            continue
        try:
            finalize_tournament_results(tournament)
        except Exception:
            errors += 1
            logger.exception("Failed to finalize tournament #%s.", tournament.pk)
        else:
            finalized += 1
    return {"finalized": finalized, "waiting": waiting, "errors": errors}


def pending_tournament_coupons(tournament: Tournament):
    return TournamentCoupon.objects.filter(
        tournament=tournament,
        participant__status=TournamentParticipant.Status.ACTIVE,
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        coupon__state_status=PredictionCoupon.StateStatus.PENDING,
    )


def prize_for_rank(tournament: Tournament, rank: int) -> Decimal:
    prize = _active_prize_for_rank(tournament, rank)
    if prize is not None:
        return _money(prize.money_amount)
    if rank == 1:
        return _money(tournament.prize_first)
    if rank == 2:
        return _money(tournament.prize_second)
    if rank == 3:
        return _money(tournament.prize_third)
    return Decimal("0.00")


def achievement_for_rank(tournament: Tournament, rank: int) -> TournamentAchievement | None:
    prize = _active_prize_for_rank(tournament, rank)
    if prize is not None and prize.achievement_id:
        return prize.achievement
    kind_by_rank = {
        1: TournamentAchievement.Kind.FIRST_PLACE,
        2: TournamentAchievement.Kind.SECOND_PLACE,
        3: TournamentAchievement.Kind.THIRD_PLACE,
    }
    kind = kind_by_rank.get(rank)
    if not kind:
        return None
    return tournament.achievements.filter(kind=kind).order_by("sort_order", "id").first()


def _active_prize_for_rank(tournament: Tournament, rank: int) -> TournamentPrize | None:
    return (
        TournamentPrize.objects.select_related("achievement")
        .filter(tournament=tournament, place=rank, is_active=True)
        .order_by("sort_order", "id")
        .first()
    )


def _final_rows(tournament: Tournament) -> list[dict]:
    results = (
        TournamentResult.objects.filter(tournament=tournament)
        .select_related("participant__user", "participant__user__analyst_profile")
        .order_by("rank", "id")
    )
    rows = []
    for result in results:
        row = _empty_row(result.participant)
        row.update(
            rank=result.rank,
            coupons_count=result.coupons_count,
            wins_count=result.wins_count,
            losses_count=result.losses_count,
            refunds_count=result.refunds_count,
            pending_count=result.pending_count,
            total_stake=result.total_stake,
            profit=result.profit,
            roi_percent=result.roi_percent,
        )
        rows.append(row)
    return rows


def _empty_rows(tournament: Tournament) -> dict[int, dict]:
    # Disqualified participants and those who left neither rank nor win prizes.
    participants = (
        TournamentParticipant.objects.filter(
            tournament=tournament,
            status=TournamentParticipant.Status.ACTIVE,
        )
        .select_related("user", "user__analyst_profile")
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

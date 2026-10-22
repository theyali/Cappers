import logging
from decimal import Decimal, ROUND_HALF_UP

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from game.models import PredictionCoupon
from tournaments.models import (
    Tournament,
    TournamentAchievement,
    TournamentCoupon,
    TournamentParticipant,
    TournamentPrize,
    TournamentPointAccrual,
    TournamentResult,
)


MONEY_STEP = Decimal("0.01")
PERCENT_STEP = Decimal("0.01")
TOURNAMENT_LEADERBOARD_CACHE_TTL = 60

logger = logging.getLogger(__name__)


def _leaderboard_cache_key(tournament: Tournament) -> str:
    return f"tournaments:leaderboard:v6:{tournament.pk}"


def invalidate_tournament_leaderboard(tournament_id):
    key = f"tournaments:leaderboard:v6:{tournament_id}"
    cache.delete(key)
    transaction.on_commit(lambda: cache.delete(key))


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
            # Joining, leaving and disqualification must be visible immediately,
            # even when no coupon has been published yet.
            participant_ids = set(TournamentParticipant.objects.filter(
                tournament=tournament,
                status=TournamentParticipant.Status.ACTIVE,
            ).values_list("pk", flat=True))
            if participant_ids == {row["participant"].pk for row in cached}:
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
    if tournament.uses_points:
        coupons = _with_point_totals(coupons)

    for tournament_coupon in coupons:
        participant_id = tournament_coupon.participant_id
        if participant_id not in rows:
            rows[participant_id] = _empty_row(tournament_coupon.participant)
        _apply_coupon(rows[participant_id], tournament_coupon.coupon)
        _apply_link_points(rows[participant_id], tournament_coupon)

    ordered = _rank_rows(rows, tournament=tournament)

    if use_cache:
        cache.set(cache_key, ordered, TOURNAMENT_LEADERBOARD_CACHE_TTL)
    return ordered


def user_tournament_positions(user, tournament_ids) -> dict:
    """Current positions for several tournament cards in two batched queries."""
    if not tournament_ids:
        return {}
    grouped = {tournament_id: {} for tournament_id in tournament_ids}
    tournaments, saved = {}, {}
    participants = TournamentParticipant.objects.filter(tournament_id__in=tournament_ids).filter(
        Q(status=TournamentParticipant.Status.ACTIVE) | Q(tournament__finalized_at__isnull=False, result__isnull=False),
    ).select_related("user", "user__analyst_profile", "tournament", "result")
    for participant in participants:
        tournaments[participant.tournament_id] = participant.tournament
        grouped[participant.tournament_id][participant.pk] = _empty_row(participant)
        result = getattr(participant, "result", None)
        if participant.tournament.finalized_at and result:
            saved.setdefault(participant.tournament_id, []).append(_row_from_result(result, participant.tournament))
    coupons = TournamentCoupon.objects.filter(
        tournament_id__in=tournament_ids,
        participant__status=TournamentParticipant.Status.ACTIVE,
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).select_related("coupon")
    if any(tournament.uses_points for tournament in tournaments.values()):
        coupons = _with_point_totals(coupons)
    for entry in coupons:
        row = grouped[entry.tournament_id].get(entry.participant_id)
        if row is not None:
            _apply_coupon(row, entry.coupon)
            _apply_link_points(row, entry)
    return {
        tournament_id: row
        for tournament_id, rows in grouped.items()
        for row in (saved.get(tournament_id, []) if tournaments.get(tournament_id) and tournaments[tournament_id].finalized_at
            else _rank_rows(rows, tournament=tournaments.get(tournament_id)))
        if row["user"].pk == user.pk
    }


def _with_point_totals(links):
    return links.annotate(
        base_points_total=Sum("point_accruals__points", filter=Q(point_accruals__kind=TournamentPointAccrual.Kind.BASE)),
        bonus_points_total=Sum("point_accruals__points", filter=~Q(point_accruals__kind=TournamentPointAccrual.Kind.BASE)),
    )


def _apply_link_points(row, link):
    row["base_points"] += getattr(link, "base_points_total", 0) or 0
    row["bonus_points"] += getattr(link, "bonus_points_total", 0) or 0
    row["points"] = row["base_points"] + row["bonus_points"]


def _rank_rows(rows, *, tournament=None):
    normalized_rows = []
    for row in rows.values():
        row["total_stake"] = _money(row["total_stake"])
        row["profit"] = _money(row["profit"])
        row["roi_percent"] = _percent(row["profit"], row["total_stake"])
        normalized_rows.append(row)

    # Places go by ROI, so a single huge stake cannot outweigh steady play; profit breaks ties.
    # Participants without a settled coupon have no result yet and go below everyone who has one,
    # so doing nothing cannot outrank a loss.
    uses_points = bool(tournament and tournament.uses_points)
    for row in normalized_rows:
        row["uses_points"] = uses_points
        row["score_label"] = str(row["points"]) if uses_points else f'{row["roi_percent"]:.2f}%'
        row["score_unit"] = "очков" if uses_points else "ROI"
    ordered = sorted(
        normalized_rows,
        key=lambda row: (
            has_tournament_result(row),
            row["points"] if uses_points else row["roi_percent"],
            0 if uses_points else row["profit"],
            row["wins_count"],
            0 if uses_points else row["coupons_count"],
            -row["participant"].joined_at.timestamp(),
            -row["participant"].pk,
        ),
        reverse=True,
    )
    for index, row in enumerate(ordered, start=1):
        row["rank"] = index

    return ordered


@transaction.atomic
def finalize_tournament_results(tournament: Tournament) -> list[TournamentResult]:
    """Fix places and award prizes once, after every tournament coupon is settled."""
    # The same participant -> tournament order as publication and point recalculation.
    # Inserting results also checks participant foreign keys, so lock them before the tournament.
    list(TournamentParticipant.objects.select_for_update().filter(tournament=tournament).order_by("pk"))
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
    prizes = {
        row["rank"]: prize_for_rank(tournament, row["rank"]) if has_tournament_result(row) else Decimal("0.00")
        for row in rows
    }
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
            base_points=row["base_points"],
            bonus_points=row["bonus_points"],
            points=row["points"],
            prize_amount=prizes[row["rank"]],
            achievement=achievement_for_rank(tournament, row["rank"]) if has_tournament_result(row) else None,
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
    return _money(prize.money_amount) if prize is not None else Decimal("0.00")


def achievement_for_rank(tournament: Tournament, rank: int) -> TournamentAchievement | None:
    prize = _active_prize_for_rank(tournament, rank)
    return prize.achievement if prize is not None else None


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
        rows.append(_row_from_result(result, tournament))
    return rows


def _row_from_result(result, tournament):
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
        base_points=result.base_points,
        bonus_points=result.bonus_points,
        points=result.points,
        uses_points=tournament.uses_points,
        score_label=str(result.points) if tournament.uses_points else f"{result.roi_percent:.2f}%",
        score_unit="очков" if tournament.uses_points else "ROI",
    )
    return row


def has_tournament_result(row: dict) -> bool:
    """A participant places only with at least one settled tournament coupon."""
    return bool(row["wins_count"] or row["losses_count"] or row["refunds_count"])


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
        "base_points": 0,
        "bonus_points": 0,
        "points": 0,
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

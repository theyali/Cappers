"""Points v1: publication order, immutable odds, replaceable per-source accruals."""
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

from django.db import transaction

from game.models import PredictionCoupon
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant, TournamentPointAccrual


def build_point_accruals(tournament, links):
    """Rebuild the complete sequence so late results also correct dependent bonuses.

    Pending coupons interrupt a known winning sequence until resolved. Refunds and
    losses break it; canceled coupons are absent. Every disjoint triple earns once.
    Daily bonuses count published coupons, including pending ones and refunds.
    """
    accruals = []
    streak = 0
    days = defaultdict(list)
    for link in links:
        days[link.published_at.astimezone(ZoneInfo(tournament.scoring_timezone)).date()].append(link)
        state = link.coupon.state_status
        if state == PredictionCoupon.StateStatus.WIN:
            base = int((link.published_coefficient * 10).to_integral_value(rounding=ROUND_DOWN))
            streak += 1
            if tournament.high_odds_bonus_enabled and link.published_coefficient > Decimal("3.00"):
                accruals.append((link, "high_odds", f"high_odds:{link.pk}", tournament.high_odds_bonus_points))
            if streak == 3:
                if tournament.streak_bonus_enabled:
                    accruals.append((link, "streak", f"streak:{link.pk}", tournament.streak_bonus_points))
                streak = 0
        else:
            streak = 0
            base = -5 if state == PredictionCoupon.StateStatus.LOSE else 0
        if state != PredictionCoupon.StateStatus.PENDING:
            accruals.append((link, "base", f"base:{link.pk}", base))
    if tournament.daily_bonus_enabled:
        for day, publications in days.items():
            if len(publications) >= 5:
                accruals.append((publications[4], "daily", f"daily:{day.isoformat()}", tournament.daily_bonus_points))
    return accruals


@transaction.atomic
def sync_participant_points(participant_id):
    participant = TournamentParticipant.objects.select_for_update().filter(pk=participant_id).first()
    if participant is None:
        return
    # Publication, settlement and finalization serialize on the same tournament.
    tournament = Tournament.objects.select_for_update().get(pk=participant.tournament_id)
    if tournament.finalized_at or not tournament.uses_points:
        return
    links = []
    if participant.status == TournamentParticipant.Status.ACTIVE:
        links = list(TournamentCoupon.objects.filter(
            participant=participant, coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        ).select_related("coupon").order_by("published_at", "id"))
    desired = {key: (link, kind, points) for link, kind, key, points in build_point_accruals(tournament, links)}
    existing = {entry.source_key: entry for entry in participant.point_accruals.all()}
    participant.point_accruals.exclude(source_key__in=desired).delete()
    created, changed = [], []
    for key, (link, kind, points) in desired.items():
        entry = existing.get(key)
        if entry is None:
            created.append(TournamentPointAccrual(participant=participant, tournament_coupon=link, kind=kind,
                source_key=key, points=points))
        elif entry.points != points or entry.tournament_coupon_id != link.pk:
            entry.points, entry.tournament_coupon_id = points, link.pk
            changed.append(entry)
    TournamentPointAccrual.objects.bulk_create(created)
    if changed:
        TournamentPointAccrual.objects.bulk_update(changed, ("points", "tournament_coupon"))
    from tournaments.services.leaderboard import invalidate_tournament_leaderboard

    invalidate_tournament_leaderboard(tournament.pk)

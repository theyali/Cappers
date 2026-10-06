from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cabinet.models import UserVipSubscription
from cabinet.referrals import REFERRAL_ACTION_TOURNAMENT, credit_referral_income
from cabinet.vip import extend_vip
from tournaments.models import (
    Tournament,
    TournamentPrize,
    TournamentPrizeAward,
    TournamentResult,
)
from wallets.models import CoinTransaction, RealBalanceTransaction
from wallets.services import credit_coins, credit_real_balance


MONEY_STEP = Decimal("0.01")


@transaction.atomic
def award_tournament_prizes(tournament: Tournament, *, results=None) -> list[TournamentPrizeAward]:
    if timezone.now() <= tournament.ends_at:
        raise ValidationError("Призы можно выдать только после окончания турнира.")

    final_results = _final_results(tournament, results=results)
    if not final_results:
        if results is not None:
            return []
        raise ValidationError("Сначала зафиксируйте итоги турнира.")

    prizes_by_place = {
        prize.place: prize
        for prize in TournamentPrize.objects.select_related("achievement").filter(
            tournament=tournament,
            is_active=True,
        )
    }

    awards = []
    for result in final_results:
        prize = prizes_by_place.get(result.rank)
        snapshot = _award_snapshot(result, prize)
        if not _has_any_award(snapshot):
            continue

        award, created = TournamentPrizeAward.objects.select_related("participant__user").get_or_create(
            tournament=tournament,
            participant=result.participant,
            defaults={
                "prize": prize,
                "money_awarded": snapshot["money_awarded"],
                "coins_awarded": snapshot["coins_awarded"],
                "vip_days_awarded": snapshot["vip_days_awarded"],
                "achievement_awarded": snapshot["achievement_awarded"],
            },
        )
        if created:
            _apply_prize_award(award, result)
        awards.append(award)

    return awards


def _final_results(tournament: Tournament, *, results=None) -> list[TournamentResult]:
    if results is not None:
        return sorted(list(results), key=lambda item: item.rank)
    return list(
        TournamentResult.objects.filter(tournament=tournament)
        .select_related("participant__user", "achievement")
        .order_by("rank", "id")
    )


def _award_snapshot(result: TournamentResult, prize: TournamentPrize | None) -> dict:
    if prize is not None:
        return {
            "money_awarded": _money(prize.money_amount),
            "coins_awarded": int(prize.coins_amount or 0),
            "vip_days_awarded": int(prize.vip_days or 0),
            "achievement_awarded": prize.achievement,
        }
    return {
        "money_awarded": _money(result.prize_amount),
        "coins_awarded": 0,
        "vip_days_awarded": 0,
        "achievement_awarded": result.achievement,
    }


def _has_any_award(snapshot: dict) -> bool:
    return (
        snapshot["money_awarded"] > 0
        or snapshot["coins_awarded"] > 0
        or snapshot["vip_days_awarded"] > 0
        or snapshot["achievement_awarded"] is not None
    )


def _apply_prize_award(award: TournamentPrizeAward, result: TournamentResult) -> None:
    user = award.participant.user
    tournament = award.tournament

    if award.money_awarded > 0:
        credit_real_balance(
            user,
            award.money_awarded,
            RealBalanceTransaction.Kind.TOURNAMENT_PRIZE,
            related_obj=tournament,
            note=f"{result.rank} место в турнире «{tournament.title}»",
        )
        credit_referral_income(
            user,
            award.money_awarded,
            REFERRAL_ACTION_TOURNAMENT,
            related_obj=award,
            note=f"Реферал @{user.username}: приз в турнире «{tournament.title}»",
        )

    if award.coins_awarded > 0:
        credit_coins(
            user,
            award.coins_awarded,
            CoinTransaction.Kind.TOURNAMENT_PRIZE_COINS,
            related_obj=award,
            note=f"{result.rank} место в турнире «{tournament.title}»",
        )

    if award.vip_days_awarded > 0:
        extend_vip(
            user,
            award.vip_days_awarded,
            UserVipSubscription.Source.TOURNAMENT,
        )

    if award.achievement_awarded_id and result.achievement_id != award.achievement_awarded_id:
        result.achievement = award.achievement_awarded
        result.save(update_fields=("achievement",))


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)

from decimal import Decimal

from tournaments.models import TournamentPrize


def create_money_prizes(tournament, *amounts) -> list[TournamentPrize]:
    """Money prizes for places 1, 2, 3… in test fixtures."""
    return TournamentPrize.objects.bulk_create(
        TournamentPrize(tournament=tournament, place=place, money_amount=Decimal(str(amount)))
        for place, amount in enumerate(amounts, start=1)
    )

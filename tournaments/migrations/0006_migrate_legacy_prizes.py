from decimal import Decimal

from django.db import migrations


LEGACY_PRIZES = (
    (1, "prize_first"),
    (2, "prize_second"),
    (3, "prize_third"),
)


def forwards(apps, schema_editor):
    Tournament = apps.get_model("tournaments", "Tournament")
    TournamentPrize = apps.get_model("tournaments", "TournamentPrize")

    prizes_to_create = []
    existing_places = set(
        TournamentPrize.objects.values_list("tournament_id", "place")
    )

    for tournament in Tournament.objects.all().only(
        "id",
        "prize_first",
        "prize_second",
        "prize_third",
    ):
        for place, field_name in LEGACY_PRIZES:
            if (tournament.id, place) in existing_places:
                continue

            amount = getattr(tournament, field_name) or Decimal("0")
            if amount <= 0:
                continue

            prizes_to_create.append(
                TournamentPrize(
                    tournament_id=tournament.id,
                    place=place,
                    money_amount=amount,
                    sort_order=place,
                    is_active=True,
                )
            )
            existing_places.add((tournament.id, place))

    if prizes_to_create:
        TournamentPrize.objects.bulk_create(prizes_to_create)


def backwards(apps, schema_editor):
    # Не удаляем призы при откате: после миграции их могли отредактировать вручную.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tournaments", "0005_tournamentprize"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

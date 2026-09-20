from django.db import transaction

from cabinet.models import (
    AnalystProfile,
    UserLeaguePreference,
    UserSportPreference,
)


@transaction.atomic
def sync_user_sport_league_preferences(
    user,
    sports,
    leagues,
    *,
    profile: AnalystProfile | None = None,
) -> None:
    sports = list(sports)
    leagues = list(leagues)

    UserSportPreference.objects.filter(user=user).delete()
    UserSportPreference.objects.bulk_create(
        [
            UserSportPreference(user=user, sport=sport)
            for sport in sports
        ]
    )

    UserLeaguePreference.objects.filter(user=user).delete()
    UserLeaguePreference.objects.bulk_create(
        [
            UserLeaguePreference(user=user, league=league)
            for league in leagues
        ]
    )

    if profile is None:
        return

    profile.favorite_sports = ", ".join(str(sport) for sport in sports)[:320]
    profile.favorite_leagues = ", ".join(str(league) for league in leagues)[:500]
    profile.save(
        update_fields=[
            "favorite_sports",
            "favorite_leagues",
            "updated_at",
        ]
    )

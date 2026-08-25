import django.db.models.deletion
from django.db import migrations, models
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.text import slugify


PROVIDER_NEUROKEFF = "neurokeff"


def localized(value, preferred="ru"):
    if isinstance(value, dict):
        fallback = "en" if preferred == "ru" else "ru"
        return str(value.get(preferred) or value.get(fallback) or next(iter(value.values()), "") or "")
    return str(value or "")


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def unique_slug(model, value, pk=None):
    base_slug = slugify(value, allow_unicode=False)[:255] or "item"
    slug = base_slug
    counter = 2
    queryset = model.objects.all()
    if pk:
        queryset = queryset.exclude(pk=pk)

    while queryset.filter(slug=slug).exists():
        suffix = f"-{counter}"
        slug = f"{base_slug[:255 - len(suffix)]}{suffix}"
        counter += 1
    return slug


def sync_sport(Sport, sport_id):
    sport_id = sport_id or 2
    sport, _ = Sport.objects.update_or_create(
        provider=PROVIDER_NEUROKEFF,
        external_id=sport_id,
        defaults={
            "code": "football",
            "name": "Football",
            "name_ru": "Футбол",
            "raw_data": {"sport_id": sport_id},
        },
    )
    return sport


def sync_country(Country, payload):
    external_id = to_int(payload.get("id"))
    if external_id is None:
        return None

    country, _ = Country.objects.update_or_create(
        provider=PROVIDER_NEUROKEFF,
        external_id=external_id,
        defaults={
            "code": str(payload.get("code") or ""),
            "name": localized(payload.get("name"), "en"),
            "name_ru": localized(payload.get("name"), "ru"),
            "logo": str(payload.get("logo") or ""),
            "raw_data": payload,
        },
    )
    return country


def sync_venue(Venue, payload):
    external_id = to_int(payload.get("id"))
    if external_id is None:
        return None

    venue, _ = Venue.objects.update_or_create(
        provider=PROVIDER_NEUROKEFF,
        external_id=external_id,
        defaults={
            "name": localized(payload.get("name"), "en"),
            "name_ru": localized(payload.get("name"), "ru"),
            "city": localized(payload.get("city"), "en"),
            "city_ru": localized(payload.get("city"), "ru"),
            "capacity": to_int(payload.get("capacity")),
            "logo": str(payload.get("logo") or ""),
            "address": str(payload.get("address") or ""),
            "address_ru": str(payload.get("address_ru") or ""),
            "surface": str(payload.get("surface") or ""),
            "surface_ru": str(payload.get("surface_ru") or ""),
            "raw_data": payload,
        },
    )
    return venue


def sync_league(League, payload, sport, country):
    external_id = to_int(payload.get("id"))
    if external_id is None:
        return None

    league, _ = League.objects.update_or_create(
        provider=PROVIDER_NEUROKEFF,
        external_id=external_id,
        defaults={
            "sport": sport,
            "country": country,
            "name": localized(payload.get("name"), "en"),
            "name_ru": localized(payload.get("name"), "ru"),
            "logo": str(payload.get("logo") or ""),
            "gender": str(payload.get("gender") or ""),
            "age_group": str(payload.get("age_group") or ""),
            "raw_data": payload,
        },
    )
    if not league.slug:
        league.slug = unique_slug(League, f"{league.name}-{league.external_id}", league.pk)
        league.save(update_fields=["slug"])
    return league


def sync_league_season(LeagueSeason, payload, league, sport):
    year = to_int(payload.get("year"))
    if league is None or year is None:
        return None

    round_updated_at = parse_datetime(payload.get("round_updated_at") or "")
    season, _ = LeagueSeason.objects.update_or_create(
        league=league,
        year=year,
        defaults={
            "sport": sport,
            "start_date": parse_date(payload.get("start_date") or ""),
            "end_date": parse_date(payload.get("end_date") or ""),
            "is_current": bool(payload.get("is_current")),
            "round_name": str(payload.get("round_name") or ""),
            "round_name_ru": str(payload.get("round_name_ru") or ""),
            "round_updated_at": round_updated_at,
            "raw_data": payload,
        },
    )
    return season


def sync_team(Team, payload, sport, country):
    external_id = to_int(payload.get("id"))
    if external_id is None:
        return None

    team, _ = Team.objects.update_or_create(
        provider=PROVIDER_NEUROKEFF,
        external_id=external_id,
        defaults={
            "sport": sport,
            "country": country,
            "name": localized(payload.get("name"), "en"),
            "name_ru": localized(payload.get("name"), "ru"),
            "logo": str(payload.get("logo") or ""),
            "gender": str(payload.get("gender") or ""),
            "age_group": str(payload.get("age_group") or ""),
            "raw_data": payload,
        },
    )
    if not team.slug:
        team.slug = unique_slug(Team, f"{team.name}-{team.external_id}", team.pk)
        team.save(update_fields=["slug"])
    return team


def populate_entities(apps, schema_editor):
    Country = apps.get_model("game", "Country")
    Sport = apps.get_model("game", "Sport")
    Venue = apps.get_model("game", "Venue")
    League = apps.get_model("game", "League")
    LeagueSeason = apps.get_model("game", "LeagueSeason")
    Team = apps.get_model("game", "Team")
    Match = apps.get_model("game", "Match")

    for match in Match.objects.all().iterator():
        raw_data = match.raw_data or {}
        league_payload = raw_data.get("league") or {}
        country_payload = league_payload.get("country") or {}
        teams_payload = raw_data.get("teams") or {}
        venue_payload = raw_data.get("venue") or {}

        sport = sync_sport(Sport, match.sport_external_id or to_int(raw_data.get("sport_id")))
        country = sync_country(Country, country_payload)
        venue = sync_venue(Venue, venue_payload)
        league = sync_league(League, league_payload, sport, country)
        league_season = sync_league_season(LeagueSeason, league_payload.get("season") or {}, league, sport)
        home_team = sync_team(Team, teams_payload.get("home") or {}, sport, country)
        away_team = sync_team(Team, teams_payload.get("away") or {}, sport, country)

        match.sport = sport
        match.league = league
        match.league_season = league_season
        match.home_team = home_team
        match.away_team = away_team
        match.venue = venue
        match.venue_external_id = to_int(venue_payload.get("id"))
        match.save(
            update_fields=[
                "sport",
                "league",
                "league_season",
                "home_team",
                "away_team",
                "venue",
                "venue_external_id",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0006_rename_game_footba_sync_sc_c4a723_idx_game_match_sync_sc_bc0326_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Country",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("neurokeff", "Neurokeff")], default="neurokeff", max_length=32)),
                ("external_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("code", models.CharField(blank=True, db_index=True, max_length=10)),
                ("name", models.CharField(blank=True, max_length=120)),
                ("name_ru", models.CharField(blank=True, max_length=120)),
                ("logo", models.URLField(blank=True, max_length=500)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "verbose_name": "Страна",
                "verbose_name_plural": "Страны",
                "ordering": ["name_ru", "name", "id"],
            },
        ),
        migrations.CreateModel(
            name="Sport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("neurokeff", "Neurokeff")], default="neurokeff", max_length=32)),
                ("external_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("code", models.CharField(db_index=True, max_length=50, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("name_ru", models.CharField(blank=True, max_length=100)),
                ("image", models.URLField(blank=True, max_length=500)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "verbose_name": "Спорт",
                "verbose_name_plural": "Виды спорта",
                "ordering": ["name_ru", "name"],
            },
        ),
        migrations.CreateModel(
            name="Venue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("neurokeff", "Neurokeff")], default="neurokeff", max_length=32)),
                ("external_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("name", models.CharField(blank=True, max_length=150)),
                ("name_ru", models.CharField(blank=True, max_length=150)),
                ("city", models.CharField(blank=True, max_length=150)),
                ("city_ru", models.CharField(blank=True, max_length=150)),
                ("capacity", models.PositiveIntegerField(blank=True, null=True)),
                ("logo", models.URLField(blank=True, max_length=500)),
                ("address", models.CharField(blank=True, max_length=255)),
                ("address_ru", models.CharField(blank=True, max_length=255)),
                ("surface", models.CharField(blank=True, max_length=100)),
                ("surface_ru", models.CharField(blank=True, max_length=100)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "verbose_name": "Стадион",
                "verbose_name_plural": "Стадионы",
                "ordering": ["name_ru", "name", "id"],
            },
        ),
        migrations.RenameField(
            model_name="match",
            old_name="sport",
            new_name="sport_code",
        ),
        migrations.RenameField(
            model_name="match",
            old_name="sport_id",
            new_name="sport_external_id",
        ),
        migrations.RenameField(
            model_name="match",
            old_name="league_id",
            new_name="league_external_id",
        ),
        migrations.RenameField(
            model_name="match",
            old_name="home_team_id",
            new_name="home_team_external_id",
        ),
        migrations.RenameField(
            model_name="match",
            old_name="away_team_id",
            new_name="away_team_external_id",
        ),
        migrations.AddConstraint(
            model_name="country",
            constraint=models.UniqueConstraint(fields=("provider", "external_id"), name="unique_country_provider_external_id"),
        ),
        migrations.AddConstraint(
            model_name="sport",
            constraint=models.UniqueConstraint(fields=("provider", "external_id"), name="unique_sport_provider_external_id"),
        ),
        migrations.AddConstraint(
            model_name="venue",
            constraint=models.UniqueConstraint(fields=("provider", "external_id"), name="unique_venue_provider_external_id"),
        ),
        migrations.CreateModel(
            name="League",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("neurokeff", "Neurokeff")], default="neurokeff", max_length=32)),
                ("external_id", models.PositiveBigIntegerField(db_index=True)),
                ("name", models.CharField(max_length=255)),
                ("name_ru", models.CharField(blank=True, max_length=255)),
                ("logo", models.URLField(blank=True, max_length=500)),
                ("gender", models.CharField(blank=True, max_length=32)),
                ("age_group", models.CharField(blank=True, max_length=32)),
                ("slug", models.SlugField(blank=True, db_index=True, max_length=255, unique=True)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                ("country", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="leagues", to="game.country")),
                ("sport", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="leagues", to="game.sport")),
            ],
            options={
                "verbose_name": "Лига",
                "verbose_name_plural": "Лиги",
                "ordering": ["name_ru", "name"],
            },
        ),
        migrations.CreateModel(
            name="LeagueSeason",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year", models.PositiveIntegerField(db_index=True)),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("is_current", models.BooleanField(db_index=True, default=False)),
                ("round_name", models.CharField(blank=True, max_length=200)),
                ("round_name_ru", models.CharField(blank=True, max_length=200)),
                ("round_updated_at", models.DateTimeField(blank=True, null=True)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                ("league", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="seasons", to="game.league")),
                ("sport", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="seasons", to="game.sport")),
            ],
            options={
                "verbose_name": "Сезон лиги",
                "verbose_name_plural": "Сезоны лиг",
                "ordering": ["-year", "league_id"],
            },
        ),
        migrations.CreateModel(
            name="Team",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("neurokeff", "Neurokeff")], default="neurokeff", max_length=32)),
                ("external_id", models.PositiveBigIntegerField(db_index=True)),
                ("name", models.CharField(max_length=255)),
                ("name_ru", models.CharField(blank=True, max_length=255)),
                ("logo", models.URLField(blank=True, max_length=500)),
                ("gender", models.CharField(blank=True, max_length=32)),
                ("age_group", models.CharField(blank=True, max_length=32)),
                ("founded", models.PositiveIntegerField(blank=True, null=True)),
                ("slug", models.SlugField(blank=True, db_index=True, max_length=255, unique=True)),
                ("squad", models.JSONField(blank=True, default=list)),
                ("squad_updated_at", models.DateTimeField(blank=True, null=True)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                ("country", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="teams", to="game.country")),
                ("sport", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="teams", to="game.sport")),
                ("venue", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="teams", to="game.venue")),
            ],
            options={
                "verbose_name": "Команда",
                "verbose_name_plural": "Команды",
                "ordering": ["name_ru", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="league",
            constraint=models.UniqueConstraint(fields=("provider", "external_id"), name="unique_league_provider_external_id"),
        ),
        migrations.AddConstraint(
            model_name="leagueseason",
            constraint=models.UniqueConstraint(fields=("league", "year"), name="unique_league_season_year"),
        ),
        migrations.AddConstraint(
            model_name="team",
            constraint=models.UniqueConstraint(fields=("provider", "external_id"), name="unique_team_provider_external_id"),
        ),
        migrations.AddIndex(
            model_name="leagueseason",
            index=models.Index(fields=["league", "is_current"], name="game_league_league__71a777_idx"),
        ),
        migrations.AddField(
            model_name="match",
            name="sport",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="matches", to="game.sport"),
        ),
        migrations.AddField(
            model_name="match",
            name="league",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="matches", to="game.league"),
        ),
        migrations.AddField(
            model_name="match",
            name="league_season",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="matches", to="game.leagueseason"),
        ),
        migrations.AddField(
            model_name="match",
            name="home_team",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="home_matches", to="game.team"),
        ),
        migrations.AddField(
            model_name="match",
            name="away_team",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="away_matches", to="game.team"),
        ),
        migrations.AddField(
            model_name="match",
            name="venue_external_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="match",
            name="venue",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="matches", to="game.venue"),
        ),
        migrations.AddIndex(
            model_name="match",
            index=models.Index(fields=["sport", "starts_at"], name="game_match_sport_i_0e55a7_idx"),
        ),
        migrations.AddIndex(
            model_name="match",
            index=models.Index(fields=["league", "starts_at"], name="game_match_league__847db6_idx"),
        ),
        migrations.RunPython(populate_entities, migrations.RunPython.noop),
    ]

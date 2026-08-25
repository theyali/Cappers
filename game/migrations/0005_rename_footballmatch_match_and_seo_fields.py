from django.db import migrations, models
from django.utils.text import slugify


def localized(value, preferred):
    if isinstance(value, dict):
        fallback = "ru" if preferred == "en" else "en"
        return str(value.get(preferred) or value.get(fallback) or next(iter(value.values()), "") or "")
    return str(value or "")


def build_match_slug(match):
    base = "-".join(
        [
            match.home_team_name_en or match.home_team_name or "home",
            "vs",
            match.away_team_name_en or match.away_team_name or "away",
            match.league_name_en or match.league_name or "league",
            str(match.external_id or match.pk),
        ]
    )
    slug = slugify(base)[:320] or f"match-{match.pk}"
    original = slug
    counter = 2
    Match = match.__class__

    while Match.objects.filter(slug=slug).exclude(pk=match.pk).exists():
        suffix = f"-{counter}"
        slug = f"{original[:320 - len(suffix)]}{suffix}"
        counter += 1
    return slug


def populate_match_seo_fields(apps, schema_editor):
    Match = apps.get_model("game", "Match")

    for match in Match.objects.all().iterator():
        raw_data = match.raw_data or {}
        league = raw_data.get("league") or {}
        country = league.get("country") or {}
        teams = raw_data.get("teams") or {}
        home_team = teams.get("home") or {}
        away_team = teams.get("away") or {}

        match.sport = "football"
        match.league_name_en = localized(league.get("name"), "en") or match.league_name
        match.league_country_en = localized(country.get("name"), "en") or match.league_country
        match.home_team_name_en = localized(home_team.get("name"), "en") or match.home_team_name
        match.away_team_name_en = localized(away_team.get("name"), "en") or match.away_team_name
        match.slug = build_match_slug(match)
        match.save(
            update_fields=[
                "sport",
                "league_name_en",
                "league_country_en",
                "home_team_name_en",
                "away_team_name_en",
                "slug",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0004_alter_prediction_comment"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="FootballMatch",
            new_name="Match",
        ),
        migrations.AddField(
            model_name="match",
            name="sport",
            field=models.CharField(
                choices=[("football", "Футбол")],
                db_index=True,
                default="football",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="match",
            name="slug",
            field=models.SlugField(blank=True, db_index=True, max_length=320, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="match",
            name="league_name_en",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="match",
            name="league_country_en",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="match",
            name="home_team_name_en",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="match",
            name="away_team_name_en",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(populate_match_seo_fields, migrations.RunPython.noop),
    ]

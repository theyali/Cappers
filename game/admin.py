from django.contrib import admin

from game.models import Country, League, LeagueSeason, Match, Prediction, PredictionCoupon, Sport, Team, Venue


@admin.register(Sport)
class SportAdmin(admin.ModelAdmin):
    list_display = ("name_ru", "name", "code", "external_id", "provider")
    search_fields = ("name", "name_ru", "code", "=external_id")
    list_filter = ("provider",)


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name_ru", "name", "code", "external_id", "provider")
    search_fields = ("name", "name_ru", "code", "=external_id")
    list_filter = ("provider",)


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name_ru", "name", "city_ru", "city", "external_id", "provider")
    search_fields = ("name", "name_ru", "city", "city_ru", "=external_id")
    list_filter = ("provider",)


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("name_ru", "name", "sport", "country", "external_id", "provider")
    search_fields = ("name", "name_ru", "slug", "=external_id")
    list_filter = ("provider", "sport", "country")
    autocomplete_fields = ("sport", "country")


@admin.register(LeagueSeason)
class LeagueSeasonAdmin(admin.ModelAdmin):
    list_display = ("league", "year", "is_current", "round_name_ru", "start_date", "end_date")
    search_fields = ("league__name", "league__name_ru", "round_name", "round_name_ru")
    list_filter = ("is_current", "sport", "year")
    autocomplete_fields = ("league", "sport")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name_ru", "name", "sport", "country", "external_id", "provider")
    search_fields = ("name", "name_ru", "slug", "=external_id")
    list_filter = ("provider", "sport", "country")
    autocomplete_fields = ("sport", "country", "venue")


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "external_id",
        "sport_code",
        "sync_scope",
        "starts_at",
        "league_name",
        "home_team_name",
        "away_team_name",
        "score",
        "live_minute_label",
        "updated_at",
    )
    list_filter = ("sport_code", "sync_scope", "time_status", "league_country")
    search_fields = (
        "=external_id",
        "slug",
        "league_name",
        "league_name_en",
        "home_team_name",
        "home_team_name_en",
        "away_team_name",
        "away_team_name_en",
    )
    readonly_fields = ("created_at", "updated_at", "last_seen_at", "raw_data")
    autocomplete_fields = ("sport", "league", "league_season", "home_team", "away_team", "venue")


class PredictionInline(admin.TabularInline):
    model = Prediction
    extra = 0
    autocomplete_fields = ("match",)
    fields = ("match", "market", "selection", "stake", "state_status")


@admin.register(PredictionCoupon)
class PredictionCouponAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "published_status", "total_stake", "created_at")
    list_filter = ("published_status", "created_at")
    search_fields = ("author__username", "title")
    inlines = (PredictionInline,)


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("id", "coupon", "match", "market", "selection", "stake", "state_status")
    list_filter = ("state_status", "market")
    search_fields = (
        "coupon__author__username",
        "match__home_team_name",
        "match__away_team_name",
        "selection",
    )
    autocomplete_fields = ("coupon", "match")

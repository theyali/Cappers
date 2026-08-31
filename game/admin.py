from django.contrib import admin

from game.models import Country, League, LeagueSeason, Match, MatchOdds, Prediction, PredictionCoupon, Sport, Team, Venue


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
        "sport",
        "sync_scope",
        "starts_at",
        "league_name",
        "home_team_name",
        "away_team_name",
        "score",
        "live_minute_label",
        "updated_at",
    )
    list_filter = ("sport", "sync_scope", "time_status", "league__country")
    search_fields = (
        "=external_id",
        "slug",
        "league__name",
        "league__name_ru",
        "home_team__name",
        "home_team__name_ru",
        "away_team__name",
        "away_team__name_ru",
    )
    readonly_fields = ("created_at", "updated_at", "last_seen_at", "raw_data")
    autocomplete_fields = ("sport", "league", "league_season", "home_team", "away_team", "venue")


@admin.register(MatchOdds)
class MatchOddsAdmin(admin.ModelAdmin):
    list_display = ("match", "home_win_bet", "x_bet", "away_win_bet", "goals_over_2_5", "goals_under_2_5")
    search_fields = (
        "match__home_team__name",
        "match__home_team__name_ru",
        "match__away_team__name",
        "match__away_team__name_ru",
        "=match__external_id",
    )
    autocomplete_fields = ("match",)
    readonly_fields = ("raw_data", "extra_markets")


class PredictionItemInline(admin.TabularInline):
    model = Prediction
    extra = 0
    autocomplete_fields = ("match",)
    fields = ("match", "market", "selection", "coefficient", "stake", "state_status")
    verbose_name = "Позиция прогноза"
    verbose_name_plural = "Позиции прогноза"


@admin.register(PredictionCoupon)
class PredictionCouponAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "author",
        "coupon_type",
        "confidence",
        "published_status",
        "state_status",
        "is_paid",
        "total_stake",
        "possible_payout",
        "published_at",
        "settled_at",
    )
    list_filter = ("coupon_type", "published_status", "state_status", "is_paid", "created_at", "settled_at")
    search_fields = ("author__username",)
    readonly_fields = ("coupon_type",)
    fields = (
        "author",
        "coupon_type",
        "confidence",
        "published_status",
        "state_status",
        "is_paid",
        "total_stake",
        "possible_payout",
        "published_at",
        "settled_at",
    )
    inlines = (PredictionItemInline,)


@admin.register(Prediction)
class PredictionItemAdmin(admin.ModelAdmin):
    list_display = ("id", "coupon", "match", "market", "selection", "stake", "state_status")
    list_filter = ("state_status", "market")
    search_fields = (
        "coupon__author__username",
        "match__home_team__name",
        "match__home_team__name_ru",
        "match__away_team__name",
        "match__away_team__name_ru",
        "selection",
    )
    autocomplete_fields = ("coupon", "match")

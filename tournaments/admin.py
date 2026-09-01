from django.contrib import admin

from .models import (
    Tournament,
    TournamentAchievement,
    TournamentCoupon,
    TournamentParticipant,
    TournamentPredictionEntry,
    TournamentResult,
)


class TournamentAchievementInline(admin.TabularInline):
    model = TournamentAchievement
    extra = 0
    fields = ("title", "kind", "icon", "sort_order")


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "status",
        "starts_at",
        "ends_at",
        "coupon_type_rule",
        "min_coefficient",
        "min_confidence",
        "prize_first",
        "prize_second",
        "prize_third",
        "is_featured",
    )
    list_filter = ("status", "coupon_type_rule", "is_featured", "starts_at", "ends_at", "allowed_sports")
    search_fields = ("title", "slug", "description", "rules_text")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("allowed_sports",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("title", "slug", "description", "rules_text", "status", "is_featured")}),
        ("Даты", {"fields": ("starts_at", "ends_at")}),
        ("Изображения", {"fields": ("card_image", "hero_image")}),
        ("Призы", {"fields": ("prize_first", "prize_second", "prize_third")}),
        (
            "Условия прогнозов",
            {"fields": ("min_coefficient", "min_confidence", "coupon_type_rule", "allowed_sports")},
        ),
        ("Системные поля", {"fields": ("created_at", "updated_at")}),
    )
    inlines = (TournamentAchievementInline,)


@admin.register(TournamentAchievement)
class TournamentAchievementAdmin(admin.ModelAdmin):
    list_display = ("title", "tournament", "kind", "sort_order")
    list_filter = ("kind", "tournament")
    search_fields = ("title", "description", "tournament__title")
    autocomplete_fields = ("tournament",)


@admin.register(TournamentParticipant)
class TournamentParticipantAdmin(admin.ModelAdmin):
    list_display = ("tournament", "user", "status", "joined_at", "left_at")
    list_filter = ("status", "tournament", "joined_at")
    search_fields = ("tournament__title", "user__username", "user__email")
    autocomplete_fields = ("tournament", "user")
    readonly_fields = ("joined_at",)


class TournamentPredictionEntryInline(admin.TabularInline):
    model = TournamentPredictionEntry
    extra = 0
    fields = ("prediction", "match", "created_at")
    autocomplete_fields = ("prediction", "match")
    readonly_fields = ("created_at",)


@admin.register(TournamentCoupon)
class TournamentCouponAdmin(admin.ModelAdmin):
    list_display = ("tournament", "participant", "coupon", "created_at")
    list_filter = ("tournament", "created_at")
    search_fields = (
        "tournament__title",
        "participant__user__username",
        "participant__user__email",
        "coupon__id",
    )
    autocomplete_fields = ("tournament", "participant", "coupon")
    readonly_fields = ("created_at",)
    inlines = (TournamentPredictionEntryInline,)


@admin.register(TournamentPredictionEntry)
class TournamentPredictionEntryAdmin(admin.ModelAdmin):
    list_display = ("tournament", "participant", "match", "prediction", "tournament_coupon", "created_at")
    list_filter = ("tournament", "created_at")
    search_fields = (
        "tournament__title",
        "participant__user__username",
        "match__home_team__name",
        "match__home_team__name_ru",
        "match__away_team__name",
        "match__away_team__name_ru",
    )
    autocomplete_fields = ("tournament", "participant", "tournament_coupon", "prediction", "match")
    readonly_fields = ("created_at",)


@admin.register(TournamentResult)
class TournamentResultAdmin(admin.ModelAdmin):
    list_display = (
        "tournament",
        "rank",
        "participant",
        "profit",
        "roi_percent",
        "prize_amount",
        "coupons_count",
        "finalized_at",
    )
    list_filter = ("tournament", "rank", "finalized_at")
    search_fields = ("tournament__title", "participant__user__username", "participant__user__email")
    autocomplete_fields = ("tournament", "participant", "achievement")
    readonly_fields = ("finalized_at",)

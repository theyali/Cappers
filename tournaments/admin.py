from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import (
    Tournament,
    TournamentAchievement,
    TournamentCoupon,
    TournamentEligibilityRule,
    TournamentFAQ,
    TournamentParticipant,
    TournamentPredictionEntry,
    TournamentPrize,
    TournamentPrizeAward,
    TournamentResult,
    TournamentStage,
)
from .services.leaderboard import finalize_tournament_results


class TournamentAchievementInline(admin.TabularInline):
    model = TournamentAchievement
    extra = 0
    fields = ("title", "kind", "icon", "sort_order")


class TournamentStageInline(admin.TabularInline):
    model = TournamentStage
    extra = 1
    fields = ("title", "period", "description", "sort_order", "is_active")
    ordering = ("sort_order", "id")


class TournamentPrizeInline(admin.TabularInline):
    model = TournamentPrize
    extra = 1
    fields = (
        "place",
        "money_amount",
        "coins_amount",
        "vip_days",
        "achievement",
        "title",
        "description",
        "sort_order",
        "is_active",
    )
    autocomplete_fields = ("achievement",)
    ordering = ("place", "sort_order", "id")


class TournamentEligibilityRuleInline(admin.TabularInline):
    model = TournamentEligibilityRule
    extra = 1
    fields = (
        "rule_type",
        "operator",
        "value",
        "sport",
        "title",
        "description",
        "sort_order",
        "is_active",
    )
    autocomplete_fields = ("sport",)
    ordering = ("sort_order", "id")


class TournamentAdminForm(forms.ModelForm):
    class Meta:
        model = Tournament
        fields = "__all__"
        widgets = {"card_icon_bg_color": forms.TextInput(attrs={"type": "color"})}


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    form = TournamentAdminForm
    list_display = (
        "title",
        "status",
        "access_type",
        "entry_type",
        "entry_fee_coins",
        "starts_at",
        "ends_at",
        "coupon_type_rule",
        "min_coefficient",
        "min_confidence",
        "prize_first_display",
        "prize_second_display",
        "prize_third_display",
        "is_featured",
        "finalized_at",
    )
    list_filter = (
        "status",
        "access_type",
        "entry_type",
        "analysts_only",
        "vip_only",
        "new_users_only",
        "eligibility_mode",
        "coupon_type_rule",
        "is_featured",
        "starts_at",
        "ends_at",
        "allowed_sports",
        "eligibility_sport",
    )
    search_fields = ("title", "slug", "description", "rules_text")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("allowed_sports",)
    readonly_fields = ("finalized_at", "created_at", "updated_at")
    actions = ("finalize_results",)
    fieldsets = (
        (None, {"fields": ("title", "slug", "description", "rules_text", "status", "is_featured")}),
        (
            "Тексты наград",
            {"fields": ("reward_payout_text", "reward_wallet_text", "reward_coins_wallet_text", "reward_rules_text")},
        ),
        (
            "Тип доступа",
            {
                "fields": (
                    "access_type",
                    "analysts_only",
                    "vip_only",
                    "new_users_only",
                )
            },
        ),
        ("Стоимость участия", {"fields": ("entry_type", "entry_fee_coins")}),
        ("Даты", {"fields": ("starts_at", "ends_at")}),
        ("Изображения карточки", {"fields": ("card_image", "hero_image", "hero_icon", "card_icon_bg_color")}),
        ("Спонсор карточки", {"fields": ("sponsor_name", "sponsor_logo", "sponsor_url")}),
        ("Призы, ₽", {"fields": ("prize_first", "prize_second", "prize_third")}),
        (
            "Условия прогнозов",
            {"fields": ("min_coefficient", "min_confidence", "coupon_type_rule", "allowed_sports")},
        ),
        (
            "Условия допуска",
            {"fields": ("eligibility_mode", "min_user_predictions", "min_user_wins", "eligibility_sport")},
        ),
        ("Системные поля", {"fields": ("finalized_at", "created_at", "updated_at")}),
    )
    inlines = (
        TournamentPrizeInline,
        TournamentEligibilityRuleInline,
        TournamentStageInline,
        TournamentAchievementInline,
    )

    @admin.action(description="Зафиксировать итоги и выдать призы")
    def finalize_results(self, request, queryset):
        finalized = 0
        skipped = []
        for tournament in queryset.order_by("id"):
            try:
                finalize_tournament_results(tournament)
            except ValidationError as exc:
                skipped.append(f"«{tournament.title}»: {exc.messages[0]}")
            else:
                finalized += 1
        message = f"Итоги зафиксированы: {finalized}."
        if skipped:
            message += " Пропущены: " + "; ".join(skipped)
        self.message_user(request, message, level=messages.WARNING if skipped else messages.SUCCESS)

    @admin.display(description="1 место, ₽", ordering="prize_first")
    def prize_first_display(self, obj):
        return f"{obj.prize_first} ₽"

    @admin.display(description="2 место, ₽", ordering="prize_second")
    def prize_second_display(self, obj):
        return f"{obj.prize_second} ₽"

    @admin.display(description="3 место, ₽", ordering="prize_third")
    def prize_third_display(self, obj):
        return f"{obj.prize_third} ₽"


@admin.register(TournamentAchievement)
class TournamentAchievementAdmin(admin.ModelAdmin):
    list_display = ("title", "tournament", "kind", "sort_order")
    list_filter = ("kind", "tournament")
    search_fields = ("title", "description", "tournament__title")
    autocomplete_fields = ("tournament",)


@admin.register(TournamentFAQ)
class TournamentFAQAdmin(admin.ModelAdmin):
    list_display = ("question", "sort_order", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("question", "answer")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("sort_order", "id")
    fields = ("question", "answer", "sort_order", "is_active", "created_at", "updated_at")


@admin.register(TournamentStage)
class TournamentStageAdmin(admin.ModelAdmin):
    list_display = ("title", "tournament", "period", "sort_order", "is_active")
    list_filter = ("is_active", "tournament")
    search_fields = ("title", "period", "description", "tournament__title")
    autocomplete_fields = ("tournament",)


@admin.register(TournamentPrize)
class TournamentPrizeAdmin(admin.ModelAdmin):
    list_display = (
        "tournament",
        "place",
        "money_amount",
        "coins_amount",
        "vip_days",
        "achievement",
        "sort_order",
        "is_active",
    )
    list_filter = ("is_active", "tournament", "place")
    search_fields = ("title", "description", "tournament__title", "achievement__title")
    autocomplete_fields = ("tournament", "achievement")
    ordering = ("tournament", "place", "sort_order", "id")


@admin.register(TournamentEligibilityRule)
class TournamentEligibilityRuleAdmin(admin.ModelAdmin):
    list_display = ("tournament", "rule_type", "operator", "value", "sport", "sort_order", "is_active")
    list_filter = ("is_active", "rule_type", "operator", "tournament", "sport")
    search_fields = ("title", "description", "tournament__title")
    autocomplete_fields = ("tournament", "sport")
    ordering = ("tournament", "sort_order", "id")


@admin.register(TournamentPrizeAward)
class TournamentPrizeAwardAdmin(admin.ModelAdmin):
    list_display = (
        "tournament",
        "participant",
        "prize",
        "money_awarded",
        "coins_awarded",
        "vip_days_awarded",
        "achievement_awarded",
        "created_at",
    )
    list_filter = ("tournament", "created_at")
    search_fields = (
        "tournament__title",
        "participant__user__username",
        "participant__user__email",
        "prize__title",
        "achievement_awarded__title",
    )
    autocomplete_fields = ("tournament", "participant", "prize", "achievement_awarded")
    readonly_fields = ("created_at",)
    ordering = ("-created_at", "-id")


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
        "prize_amount_display",
        "coupons_count",
        "finalized_at",
    )
    list_filter = ("tournament", "rank", "finalized_at")
    search_fields = ("tournament__title", "participant__user__username", "participant__user__email")
    autocomplete_fields = ("tournament", "participant", "achievement")
    readonly_fields = ("finalized_at",)

    @admin.display(description="Приз, ₽", ordering="prize_amount")
    def prize_amount_display(self, obj):
        return f"{obj.prize_amount} ₽"

from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .roulette_models import RoulettePrize, RoulettePrizeCondition, RouletteSettings


class RoulettePrizeAdminForm(forms.ModelForm):
    class Meta:
        model = RoulettePrize
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        reward_type = cleaned_data.get("reward_type")
        reward_value = cleaned_data.get("reward_value")
        reward_text = (cleaned_data.get("reward_text") or "").strip()

        value_required_types = {
            RoulettePrize.RewardType.VIRTUAL_BALANCE,
            RoulettePrize.RewardType.VIP_DAYS,
            RoulettePrize.RewardType.FREE_PREDICTIONS,
            RoulettePrize.RewardType.RATING_BOOST,
            RoulettePrize.RewardType.EXTRA_SPIN,
        }
        integer_value_types = {
            RoulettePrize.RewardType.VIP_DAYS,
            RoulettePrize.RewardType.FREE_PREDICTIONS,
            RoulettePrize.RewardType.EXTRA_SPIN,
        }

        if reward_type in value_required_types and (reward_value is None or reward_value <= 0):
            self.add_error("reward_value", "Для этого типа награды укажите значение больше нуля.")
        if reward_type in integer_value_types and reward_value is not None and reward_value != reward_value.to_integral_value():
            self.add_error("reward_value", "Для этого типа награды укажите целое количество.")
        if reward_type == RoulettePrize.RewardType.PROMO_CODE and not reward_text:
            self.add_error("reward_text", "Для промокода укажите сам промокод.")
        if reward_type == RoulettePrize.RewardType.NOTHING and reward_value not in (None, 0):
            self.add_error("reward_value", "Для пустого сектора значение должно быть равно нулю.")

        return cleaned_data


class RoulettePrizeConditionInline(admin.TabularInline):
    model = RoulettePrizeCondition
    extra = 0
    min_num = 0
    fields = ("condition_type", "threshold", "is_active", "order")
    ordering = ("order", "id")
    show_change_link = True


@admin.register(RouletteSettings)
class RouletteSettingsAdmin(admin.ModelAdmin):
    list_display = ("is_enabled", "daily_free_spins", "reset_hour", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Основные настройки",
            {
                "fields": (
                    "is_enabled",
                    "daily_free_spins",
                    "reset_hour",
                )
            },
        ),
        ("Системная информация", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return not RouletteSettings.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.action(description="Включить выбранные секторы")
def activate_prizes(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="Отключить выбранные секторы")
def deactivate_prizes(modeladmin, request, queryset):
    queryset.update(is_active=False)


@admin.register(RoulettePrize)
class RoulettePrizeAdmin(admin.ModelAdmin):
    form = RoulettePrizeAdminForm
    inlines = (RoulettePrizeConditionInline,)
    actions = (activate_prizes, deactivate_prizes)
    save_on_top = True

    list_display = (
        "icon_preview_small",
        "title",
        "short_text",
        "reward_type",
        "reward_value",
        "weight",
        "is_active",
        "sector_order",
        "daily_award_limit",
        "per_user_award_limit",
        "active_period",
        "drawn_count",
        "issued_count",
    )
    list_display_links = ("title",)
    list_editable = ("weight", "is_active", "sector_order")
    list_filter = (
        "is_active",
        "reward_type",
        "condition_logic",
        "active_from",
        "active_until",
    )
    search_fields = ("title", "short_text", "reward_text")
    ordering = ("sector_order", "id")
    readonly_fields = (
        "icon_preview",
        "drawn_count",
        "issued_count",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Сектор",
            {
                "fields": (
                    "title",
                    "short_text",
                    "icon",
                    "icon_preview",
                    "is_active",
                    "sector_order",
                )
            },
        ),
        (
            "Награда",
            {
                "fields": (
                    "reward_type",
                    "reward_value",
                    "reward_text",
                    "weight",
                )
            },
        ),
        (
            "Ограничения выдачи",
            {
                "fields": (
                    "total_award_limit",
                    "daily_award_limit",
                    "per_user_award_limit",
                    "active_from",
                    "active_until",
                    "condition_logic",
                )
            },
        ),
        (
            "Статистика",
            {
                "fields": ("drawn_count", "issued_count"),
                "description": "Статистика начнёт заполняться после подключения истории прокруток.",
            },
        ),
        (
            "Системная информация",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Иконка")
    def icon_preview_small(self, obj):
        if not obj.icon:
            return "—"
        return format_html('<img src="{}" width="40" height="40" alt="">', obj.icon.url)

    @admin.display(description="Preview")
    def icon_preview(self, obj):
        if not obj or not obj.icon:
            return "Иконка не загружена"
        return format_html('<img src="{}" width="96" height="96" alt="{}">', obj.icon.url, obj.title)

    @admin.display(description="Действует")
    def active_period(self, obj):
        if not obj.active_from and not obj.active_until:
            return "Без ограничений"
        start = obj.active_from.strftime("%d.%m.%Y %H:%M") if obj.active_from else "—"
        end = obj.active_until.strftime("%d.%m.%Y %H:%M") if obj.active_until else "—"
        return f"{start} — {end}"

    @admin.display(description="Выпало")
    def drawn_count(self, obj):
        spins = getattr(obj, "spins", None)
        if spins is None:
            return 0
        return spins.count()

    @admin.display(description="Выдано")
    def issued_count(self, obj):
        spins = getattr(obj, "spins", None)
        if spins is None:
            return 0

        spin_model = spins.model
        field_names = {field.name for field in spin_model._meta.get_fields()}
        if "issued_at" in field_names:
            return spins.filter(issued_at__isnull=False).count()
        if "reward_issued_at" in field_names:
            return spins.filter(reward_issued_at__isnull=False).count()
        return 0


@admin.register(RoulettePrizeCondition)
class RoulettePrizeConditionAdmin(admin.ModelAdmin):
    list_display = ("prize", "condition_type", "threshold", "is_active", "order")
    list_editable = ("is_active", "order")
    list_filter = ("condition_type", "is_active")
    search_fields = ("prize__title",)
    autocomplete_fields = ("prize",)
    ordering = ("prize", "order", "id")
    readonly_fields = ("created_at", "updated_at")

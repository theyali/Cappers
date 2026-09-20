from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.utils.html import format_html

from .models import Achievement, AchievementCategory, UserAchievement
from .services import sync_user_achievements


@admin.register(AchievementCategory)
class AchievementCategoryAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("sort_order", "title")


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = (
        "icon_preview",
        "title",
        "key",
        "category",
        "audience",
        "metric",
        "target_value",
        "is_active",
        "sort_order",
    )
    list_filter = ("is_active", "audience", "metric", "category")
    list_editable = ("is_active", "sort_order")
    search_fields = ("title", "key", "description")
    autocomplete_fields = ("category",)
    readonly_fields = ("icon_preview", "created_at", "updated_at")
    fieldsets = (
        (
            "Основное",
            {
                "fields": (
                    "category",
                    "key",
                    "title",
                    "description",
                    "short_description",
                )
            },
        ),
        (
            "Иконка",
            {
                "fields": (
                    "icon",
                    "fallback_static_icon",
                    "icon_preview",
                )
            },
        ),
        (
            "Условие",
            {
                "fields": (
                    "audience",
                    "metric",
                    "condition_operator",
                    "target_value",
                )
            },
        ),
        (
            "Награды",
            {
                "fields": (
                    "coins_reward",
                    "xp_reward",
                )
            },
        ),
        (
            "Показы",
            {
                "fields": (
                    "is_active",
                    "is_secret",
                    "show_progress",
                    "sort_order",
                )
            },
        ),
        (
            "Система",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="Иконка")
    def icon_preview(self, obj):
        if obj.icon:
            return format_html(
                '<img src="{}" style="width:32px;height:32px;object-fit:contain">',
                obj.icon.url,
            )
        if obj.fallback_static_icon:
            return obj.fallback_static_icon
        return "—"


@admin.register(UserAchievement)
class UserAchievementAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "achievement",
        "source",
        "progress_percent",
        "unlocked_at",
    )
    list_filter = ("source", "achievement__category", "achievement")
    search_fields = (
        "user__username",
        "user__email",
        "achievement__title",
        "achievement__key",
    )
    autocomplete_fields = ("user", "achievement")
    readonly_fields = ("unlocked_at",)
    list_select_related = ("user", "achievement", "achievement__category")
    actions = ("resync_selected_users",)

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault("source", UserAchievement.Source.MANUAL)
        return initial

    @admin.action(description="Пересчитать достижения выбранных пользователей")
    def resync_selected_users(self, request, queryset):
        user_ids = queryset.values_list("user_id", flat=True).distinct()
        User = get_user_model()
        users_count = 0
        awarded_count = 0

        for user in User.objects.filter(pk__in=user_ids).iterator():
            awarded_count += len(
                sync_user_achievements(
                    user,
                    notify=False,
                )
            )
            users_count += 1

        self.message_user(
            request,
            (
                f"Пересчитано пользователей: {users_count}. "
                f"Новых достижений выдано: {awarded_count}."
            ),
            level=messages.SUCCESS,
        )

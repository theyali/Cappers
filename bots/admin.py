from django.contrib import admin
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils.html import format_html

from bots.models import (
    BotAccount,
    BotActionLog,
    BotExpertStrategy,
    BotOnlineSession,
    BotPlannedAction,
    BotRuntimeControl,
)


@admin.register(BotAccount)
class BotAccountAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "kind",
        "persona",
        "is_active",
        "planned_actions_stats",
        "last_queue_issue",
        "created_at",
    )
    list_filter = ("kind", "is_active", "created_at", "planned_actions__status")
    search_fields = ("user__username", "persona")
    autocomplete_fields = ("user",)
    actions = ("activate_bots", "pause_bots")

    def get_queryset(self, request):
        issue_queryset = BotPlannedAction.objects.filter(
            bot=OuterRef("pk"),
            status__in=[
                BotPlannedAction.Status.SKIPPED,
                BotPlannedAction.Status.FAILED,
            ],
        ).order_by("-finished_at", "-updated_at", "-id")
        return (
            super()
            .get_queryset(request)
            .select_related("user")
            .annotate(
                planned_pending_count=Count(
                    "planned_actions",
                    filter=Q(planned_actions__status=BotPlannedAction.Status.PENDING),
                    distinct=True,
                ),
                planned_done_count=Count(
                    "planned_actions",
                    filter=Q(planned_actions__status=BotPlannedAction.Status.DONE),
                    distinct=True,
                ),
                planned_skipped_count=Count(
                    "planned_actions",
                    filter=Q(planned_actions__status=BotPlannedAction.Status.SKIPPED),
                    distinct=True,
                ),
                planned_failed_count=Count(
                    "planned_actions",
                    filter=Q(planned_actions__status=BotPlannedAction.Status.FAILED),
                    distinct=True,
                ),
                last_issue_status=Subquery(issue_queryset.values("status")[:1]),
                last_issue_action=Subquery(issue_queryset.values("action")[:1]),
                last_issue_error=Subquery(issue_queryset.values("error")[:1]),
            )
        )

    @admin.display(description="Очередь planned/done/skipped/fail")
    def planned_actions_stats(self, obj):
        return format_html(
            "{} / {} / {} / {}",
            getattr(obj, "planned_pending_count", 0),
            getattr(obj, "planned_done_count", 0),
            getattr(obj, "planned_skipped_count", 0),
            getattr(obj, "planned_failed_count", 0),
        )

    @admin.display(description="Последний skip/fail")
    def last_queue_issue(self, obj):
        status = getattr(obj, "last_issue_status", "")
        action = getattr(obj, "last_issue_action", "")
        error = getattr(obj, "last_issue_error", "")
        if not status:
            return "—"
        if not error:
            error = "без причины"
        return f"{status} · {action}: {error[:120]}"

    @admin.action(description="Включить выбранных ботов")
    def activate_bots(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"Включено ботов: {updated}")

    @admin.action(description="Приостановить выбранных ботов")
    def pause_bots(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"Приостановлено ботов: {updated}")


@admin.register(BotExpertStrategy)
class BotExpertStrategyAdmin(admin.ModelAdmin):
    list_display = (
        "bot",
        "cadence_days",
        "daily_predictions_min",
        "daily_predictions_max",
        "risk_profile",
        "next_run_at",
    )
    list_filter = ("cadence_days", "risk_profile")
    autocomplete_fields = ("bot",)


@admin.register(BotActionLog)
class BotActionLogAdmin(admin.ModelAdmin):
    list_display = ("bot", "action", "target", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("bot__user__username", "target")
    autocomplete_fields = ("bot",)


@admin.register(BotPlannedAction)
class BotPlannedActionAdmin(admin.ModelAdmin):
    list_display = (
        "bot",
        "action",
        "status",
        "scheduled_at",
        "started_at",
        "finished_at",
        "payload_short",
        "result_short",
        "error_short",
    )
    list_filter = ("action", "status", "scheduled_at")
    search_fields = ("bot__user__username", "action", "error")
    autocomplete_fields = ("bot",)
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at", "error", "result")

    @admin.display(description="Payload")
    def payload_short(self, obj):
        return _short_json(obj.payload)

    @admin.display(description="Result")
    def result_short(self, obj):
        return _short_json(obj.result)

    @admin.display(description="Причина")
    def error_short(self, obj):
        return (obj.error or "—")[:120]


@admin.register(BotOnlineSession)
class BotOnlineSessionAdmin(admin.ModelAdmin):
    list_display = ("bot", "starts_at", "ends_at", "target_actions", "actions_planned", "actions_done")
    list_filter = ("starts_at", "ends_at")
    search_fields = ("bot__user__username",)
    autocomplete_fields = ("bot",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(BotRuntimeControl)
class BotRuntimeControlAdmin(admin.ModelAdmin):
    list_display = ("mode", "note", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not BotRuntimeControl.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


def _short_json(value) -> str:
    if not value:
        return "—"
    text = str(value)
    return text if len(text) <= 120 else f"{text[:117]}..."

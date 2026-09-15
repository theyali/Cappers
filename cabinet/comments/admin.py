from django.contrib import admin
from django.db import transaction
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from django.utils.text import Truncator

from .models import Comment


class ModerationReasonFilter(admin.SimpleListFilter):
    title = "причина модерации"
    parameter_name = "moderation_reason"

    def lookups(self, request, model_admin):
        reasons = (
            model_admin.get_queryset(request)
            .exclude(moderation_reason="")
            .order_by("moderation_reason")
            .values_list("moderation_reason", flat=True)
            .distinct()
        )
        return [("__empty__", "Без причины"), *((reason, reason) for reason in reasons)]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "__empty__":
            return queryset.filter(moderation_reason="")
        if value:
            return queryset.filter(moderation_reason=value)
        return queryset


def _set_comment_status(queryset, *, status: str, reason: str) -> int:
    """Change moderation state through model.save() so metric signals are preserved."""
    changed = 0
    with transaction.atomic():
        for comment in queryset.select_related("content_type").iterator():
            if comment.status == status and comment.moderation_reason == reason:
                continue
            comment.status = status
            comment.moderation_reason = reason
            comment.save(
                update_fields=(
                    "status",
                    "moderation_reason",
                    "updated_at",
                )
            )
            changed += 1
    return changed


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "short_text",
        "user",
        "status",
        "moderation_reason_value",
        "target_object_link",
        "created_at",
    )
    list_filter = (
        "status",
        ModerationReasonFilter,
        "content_type",
        "created_at",
    )
    search_fields = (
        "text",
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    readonly_fields = (
        "user",
        "content_type",
        "object_id",
        "target_object_link",
        "parent",
        "created_at",
        "updated_at",
    )
    actions = (
        "publish_comments",
        "reject_comments",
        "delete_comments",
    )
    list_select_related = (
        "user",
        "content_type",
        "parent",
    )
    ordering = ("-created_at", "-id")
    date_hierarchy = "created_at"
    list_per_page = 50
    save_on_top = True

    fieldsets = (
        (
            "Комментарий",
            {
                "fields": (
                    "text",
                    "status",
                    "moderation_reason",
                )
            },
        ),
        (
            "Целевой объект",
            {
                "fields": (
                    "target_object_link",
                    "content_type",
                    "object_id",
                    "parent",
                )
            },
        ),
        (
            "Аудит",
            {
                "fields": (
                    "user",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        # Comments are created only through product flows, not manually by staff.
        return False

    @admin.display(description="Комментарий")
    def short_text(self, obj: Comment) -> str:
        return Truncator(obj.text).chars(90)

    @admin.display(description="Причина", ordering="moderation_reason")
    def moderation_reason_value(self, obj: Comment) -> str:
        return obj.moderation_reason or "—"

    @admin.display(description="Объект")
    def target_object_link(self, obj: Comment):
        target = obj.target
        if target is None:
            return format_html(
                '<span title="Целевой объект удалён">{}.{} #{}</span>',
                obj.content_type.app_label,
                obj.content_type.model,
                obj.object_id,
            )

        label = Truncator(str(target)).chars(80)
        try:
            url = reverse(
                f"admin:{obj.content_type.app_label}_{obj.content_type.model}_change",
                args=(obj.object_id,),
            )
        except NoReverseMatch:
            return format_html(
                "<span>{}.{} #{} — {}</span>",
                obj.content_type.app_label,
                obj.content_type.model,
                obj.object_id,
                label,
            )
        return format_html(
            '<a href="{}">{}.{} #{} — {}</a>',
            url,
            obj.content_type.app_label,
            obj.content_type.model,
            obj.object_id,
            label,
        )

    @admin.action(description="Опубликовать выбранные комментарии")
    def publish_comments(self, request, queryset):
        changed = _set_comment_status(
            queryset,
            status=Comment.Status.PUBLISHED,
            reason="",
        )
        self.message_user(request, f"Опубликовано комментариев: {changed}.")

    @admin.action(description="Отклонить выбранные комментарии")
    def reject_comments(self, request, queryset):
        changed = _set_comment_status(
            queryset,
            status=Comment.Status.REJECTED,
            reason="rejected_by_moderator",
        )
        self.message_user(request, f"Отклонено комментариев: {changed}.")

    @admin.action(description="Удалить выбранные комментарии")
    def delete_comments(self, request, queryset):
        changed = _set_comment_status(
            queryset,
            status=Comment.Status.DELETED,
            reason="deleted_by_moderator",
        )
        self.message_user(request, f"Удалено комментариев: {changed}.")

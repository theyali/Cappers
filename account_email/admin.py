from django.contrib import admin

from .models import EmailChangeRequest


@admin.register(EmailChangeRequest)
class EmailChangeRequestAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "purpose",
        "current_email",
        "new_email",
        "current_confirmed_at",
        "completed_at",
        "expires_at",
        "created_at",
    )
    list_filter = ("purpose", "current_confirmed_at", "completed_at", "expires_at")
    search_fields = ("user__username", "user__email", "current_email", "new_email")
    readonly_fields = (
        "current_token",
        "code_hash",
        "current_confirmed_at",
        "new_code_sent_at",
        "completed_at",
        "created_at",
        "updated_at",
    )

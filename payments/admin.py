from django.contrib import admin

from .models import Payment, PaymentEvent


class ReadOnlyAdminMixin:
    """Payments change only through provider events and services, never by hand."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PaymentEventInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = PaymentEvent
    extra = 0
    fields = ("created_at", "event_type", "dedup_key", "external_id", "signature_valid", "processed_at", "error")
    readonly_fields = fields


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "public_id",
        "user",
        "provider",
        "purpose",
        "status",
        "amount",
        "currency",
        "amount_rub",
        "is_test",
        "created_at",
        "paid_at",
        "fulfilled_at",
    )
    list_filter = ("provider", "purpose", "status", "is_test", "created_at")
    search_fields = ("=public_id", "=external_id", "=external_invoice_id", "user__username", "user__email")
    list_select_related = ("user",)
    inlines = (PaymentEventInline,)


@admin.register(PaymentEvent)
class PaymentEventAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "provider", "event_type", "payment", "dedup_key", "signature_valid", "processed_at")
    list_filter = ("provider", "event_type", "signature_valid", "created_at")
    search_fields = ("=dedup_key", "=external_id", "=payment__public_id")
    list_select_related = ("payment",)

from django.contrib import admin

from .models import BalanceTransaction, CapperBalance


@admin.register(CapperBalance)
class CapperBalanceAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(BalanceTransaction)
class BalanceTransactionAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "amount", "balance_after", "related_model", "related_id", "created_at")
    list_filter = ("kind", "created_at")
    search_fields = ("user__username", "user__email", "note", "related_model", "related_id")
    readonly_fields = ("created_at",)

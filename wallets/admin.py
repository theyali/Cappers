from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models import Count

from .models import (
    BalanceTransaction,
    CapperBalance,
    CapperBankStats,
    CapperRealBalance,
    CopiedBet,
    CopyBettingSubscription,
    RealBalanceTransaction,
)
from .services import approve_real_withdrawal, cancel_real_withdrawal


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


@admin.register(CapperRealBalance)
class CapperRealBalanceAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "pending_withdrawal", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(CapperBankStats)
class CapperBankStatsAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "coupons_count",
        "settled_count",
        "total_stake",
        "average_stake",
        "lost_amount",
        "earned_amount",
        "pending_stake",
        "net_result",
        "updated_at",
    )
    search_fields = ("user__username", "user__email")
    readonly_fields = (
        "user",
        "coupons_count",
        "settled_count",
        "total_stake",
        "average_stake",
        "lost_amount",
        "earned_amount",
        "pending_stake",
        "net_result",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(RealBalanceTransaction)
class RealBalanceTransactionAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "status", "amount", "balance_after", "related_model", "related_id", "created_at")
    list_filter = ("kind", "status", "created_at")
    search_fields = ("user__username", "user__email", "note", "related_model", "related_id")
    readonly_fields = (
        "user",
        "kind",
        "status",
        "amount",
        "balance_after",
        "related_model",
        "related_id",
        "note",
        "created_at",
    )
    actions = ("approve_withdrawals", "cancel_withdrawals")

    @admin.action(description="Подтвердить выбранные заявки на вывод")
    def approve_withdrawals(self, request, queryset):
        processed = 0
        failed = 0
        for withdrawal in queryset.select_related("user"):
            try:
                approve_real_withdrawal(withdrawal)
            except ValidationError:
                failed += 1
            else:
                processed += 1
        self.message_user(
            request,
            f"Подтверждено заявок: {processed}. Пропущено: {failed}.",
            level=messages.SUCCESS if failed == 0 else messages.WARNING,
        )

    @admin.action(description="Отменить выбранные заявки на вывод")
    def cancel_withdrawals(self, request, queryset):
        processed = 0
        failed = 0
        for withdrawal in queryset.select_related("user"):
            try:
                cancel_real_withdrawal(withdrawal)
            except ValidationError:
                failed += 1
            else:
                processed += 1
        self.message_user(
            request,
            f"Отменено заявок: {processed}. Пропущено: {failed}.",
            level=messages.SUCCESS if failed == 0 else messages.WARNING,
        )

    def has_add_permission(self, request):
        return False


@admin.register(CopyBettingSubscription)
class CopyBettingSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "analyst",
        "status",
        "pending_status",
        "bank_amount",
        "stake_percent",
        "min_total_coefficient",
        "copied_bets_count",
        "current_loss",
        "total_profit",
        "updated_at",
    )
    list_filter = (
        "status",
        "pending_status",
        "copy_regular_coupons",
        "copy_tournament_coupons",
        "allowed_sports",
        "started_at",
        "active_since",
        "updated_at",
    )
    search_fields = ("user__username", "user__email", "analyst__username", "analyst__email")
    autocomplete_fields = ("user", "analyst", "allowed_sports")
    readonly_fields = ("started_at", "active_since", "pending_status_requested_at", "stopped_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_copied_bets_count=Count("copied_bets"))

    @admin.display(description="Скопировано ставок")
    def copied_bets_count(self, obj):
        return obj._copied_bets_count


@admin.register(CopiedBet)
class CopiedBetAdmin(admin.ModelAdmin):
    list_display = ("user", "analyst", "source_coupon", "state_status", "stake", "possible_payout", "profit", "created_at")
    list_filter = ("state_status", "created_at", "settled_at")
    search_fields = ("user__username", "analyst__username", "source_coupon__id")
    autocomplete_fields = ("subscription", "user", "analyst", "source_coupon")
    readonly_fields = ("created_at", "settled_at")

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import ValidationError
from django.db.models import Count

from .models import (
    CapperBankStats,
    CapperRealBalance,
    CoinPackage,
    CoinSettings,
    CoinTransaction,
    CoinWallet,
    CopiedBet,
    CopyBettingSubscription,
    RealBalanceTransaction,
)
from .package_pricing import format_effective_coin_price_rub
from .services import adjust_coin_balance, approve_real_withdrawal, cancel_real_withdrawal


class CoinWalletActionForm(helpers.ActionForm):
    coin_adjustment = forms.IntegerField(
        required=False,
        label="Изменение коинов",
        help_text="Например 500 или -250.",
    )
    coin_adjustment_note = forms.CharField(
        required=False,
        max_length=180,
        label="Комментарий",
    )


@admin.register(CoinWallet)
class CoinWalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "updated_at")
    search_fields = ("user__username", "user__email")
    list_select_related = ("user",)
    readonly_fields = ("user", "balance", "created_at", "updated_at")
    action_form = CoinWalletActionForm
    actions = ("adjust_selected_wallets",)

    @admin.action(description="Скорректировать коины выбранных кошельков")
    def adjust_selected_wallets(self, request, queryset):
        raw_amount = str(request.POST.get("coin_adjustment", "")).strip()
        note = str(request.POST.get("coin_adjustment_note", "")).strip()
        try:
            amount = int(raw_amount)
        except (TypeError, ValueError):
            self.message_user(
                request,
                "Укажите целое значение в поле «Изменение коинов».",
                level=messages.ERROR,
            )
            return
        if amount == 0:
            self.message_user(
                request,
                "Корректировка коинов не может быть нулевой.",
                level=messages.ERROR,
            )
            return

        processed = 0
        failed = 0
        admin_note = note or "Ручная корректировка через Django admin"
        admin_note = f"{admin_note} · администратор: {request.user}"
        for wallet in queryset.select_related("user"):
            try:
                adjust_coin_balance(wallet.user, amount, note=admin_note)
            except ValidationError:
                failed += 1
            else:
                processed += 1

        self.message_user(
            request,
            f"Скорректировано кошельков: {processed}. Пропущено: {failed}.",
            level=messages.SUCCESS if failed == 0 else messages.WARNING,
        )

    def has_add_permission(self, request):
        return False


@admin.register(CoinTransaction)
class CoinTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "kind",
        "amount",
        "balance_after",
        "related_model",
        "related_id",
        "created_at",
    )
    list_filter = ("kind", "created_at")
    search_fields = ("user__username", "user__email", "note", "related_model", "related_id")
    list_select_related = ("user",)
    readonly_fields = (
        "user",
        "kind",
        "amount",
        "balance_after",
        "related_model",
        "related_id",
        "note",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CoinSettings)
class CoinSettingsAdmin(admin.ModelAdmin):
    list_display = ("coin_price_rub", "initial_grant", "is_enabled", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Базовый справочный курс",
            {
                "fields": ("coin_price_rub",),
                "description": (
                    "coin_price_rub — базовый справочный курс внутренней валюты. "
                    "Он не обязан совпадать с фактической ценой коина в пакетах: "
                    "для пакета она считается как price_rub / (coins + bonus_coins)."
                ),
            },
        ),
        (
            "Выдача коинов",
            {
                "fields": ("initial_grant",),
                "description": "initial_grant — стартовое количество coins для нового пользователя.",
            },
        ),
        ("Система", {"fields": ("is_enabled", "created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return not CoinSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CoinPackage)
class CoinPackageAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "coins",
        "price_rub",
        "bonus_coins",
        "total_coins_display",
        "effective_coin_price_display",
        "is_active",
        "order",
    )
    list_editable = ("is_active", "order")
    list_filter = ("is_active",)
    search_fields = ("title",)
    ordering = ("order", "id")
    readonly_fields = (
        "total_coins_display",
        "effective_coin_price_display",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Пакет коинов",
            {
                "fields": (
                    "title",
                    "coins",
                    "price_rub",
                    "bonus_coins",
                    "total_coins_display",
                    "effective_coin_price_display",
                ),
                "description": (
                    "coins — базовый объём пакета; price_rub — цена покупки в рублях; "
                    "bonus_coins — промо-надбавка. Фактическая цена 1 coin считается "
                    "по всему объёму пакета и может отличаться от базового coin_price_rub."
                ),
            },
        ),
        ("Публикация", {"fields": ("is_active", "order")}),
        ("Служебные данные", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Всего coins")
    def total_coins_display(self, obj):
        return obj.total_coins

    @admin.display(description="Фактическая цена 1 coin")
    def effective_coin_price_display(self, obj):
        return f"{format_effective_coin_price_rub(obj.price_rub, obj.total_coins)} ₽"


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

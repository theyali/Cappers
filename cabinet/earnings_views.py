from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from wallets.models import RealBalanceTransaction
from wallets.services import ensure_real_balance, format_money

from .models import AnalystPaidSubscription, User


EARNING_KINDS = (
    RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
    RealBalanceTransaction.Kind.TOURNAMENT_PRIZE,
)


def _period_summary(queryset, *, label: str, days: int | None = None) -> dict:
    period_queryset = queryset
    if days is not None:
        period_queryset = period_queryset.filter(
            created_at__gte=timezone.now() - timedelta(days=days)
        )

    values = period_queryset.aggregate(
        total=Sum("amount"),
        subscription_income=Sum(
            "amount",
            filter=Q(kind=RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME),
        ),
        tournament_income=Sum(
            "amount",
            filter=Q(kind=RealBalanceTransaction.Kind.TOURNAMENT_PRIZE),
        ),
        subscription_purchases=Count(
            "id",
            filter=Q(kind=RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME),
        ),
    )

    total = values["total"] or Decimal("0.00")
    subscription_income = values["subscription_income"] or Decimal("0.00")
    tournament_income = values["tournament_income"] or Decimal("0.00")

    return {
        "label": label,
        "days": days,
        "total": total,
        "total_display": format_money(total),
        "subscription_income": subscription_income,
        "subscription_income_display": format_money(subscription_income),
        "tournament_income": tournament_income,
        "tournament_income_display": format_money(tournament_income),
        "referral_income": Decimal("0.00"),
        "referral_income_display": format_money(0),
        "subscription_purchases": values["subscription_purchases"],
    }


def build_earnings_context(user) -> dict:
    if user.role != User.Role.ANALYST:
        return {
            "earnings_all_time": _period_summary(
                RealBalanceTransaction.objects.none(),
                label="За всё время",
            ),
            "earnings_periods": [],
            "active_paid_subscribers": 0,
            "paid_subscribers_total": 0,
            "active_paid_subscriptions": [],
            "recent_earning_transactions": [],
        }

    now = timezone.now()
    real_balance = ensure_real_balance(user)
    earning_transactions = RealBalanceTransaction.objects.filter(
        user=user,
        status=RealBalanceTransaction.Status.COMPLETED,
        amount__gt=0,
        kind__in=EARNING_KINDS,
    )

    active_paid_subscriptions = list(
        AnalystPaidSubscription.objects.filter(
            analyst=user,
            expires_at__gt=now,
        )
        .select_related("subscriber", "subscriber__analyst_profile", "plan")
        .order_by("-expires_at", "-id")
    )

    return {
        "real_balance": real_balance,
        "real_balance_display": format_money(real_balance.balance),
        "real_pending_withdrawal_display": format_money(real_balance.pending_withdrawal),
        "earnings_all_time": _period_summary(earning_transactions, label="За всё время"),
        "earnings_periods": [
            _period_summary(earning_transactions, label="Неделя", days=7),
            _period_summary(earning_transactions, label="Месяц", days=30),
            _period_summary(earning_transactions, label="Квартал", days=90),
        ],
        "active_paid_subscribers": len(active_paid_subscriptions),
        "paid_subscribers_total": AnalystPaidSubscription.objects.filter(
            analyst=user,
        ).count(),
        "active_paid_subscriptions": active_paid_subscriptions,
        "recent_earning_transactions": earning_transactions.order_by(
            "-created_at",
            "-id",
        )[:20],
    }


@login_required
def profile_earnings(request):
    if request.user.role != User.Role.ANALYST:
        return redirect("cabinet:profile")

    return redirect(f"{reverse('cabinet:profile')}?tab=earnings")

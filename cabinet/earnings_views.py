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
    RealBalanceTransaction.Kind.REFERRAL_SUBSCRIPTION,
    RealBalanceTransaction.Kind.REFERRAL_TOURNAMENT,
    RealBalanceTransaction.Kind.REFERRAL_BALANCE_TOP_UP,
)

REFERRAL_EARNING_KINDS = (
    RealBalanceTransaction.Kind.REFERRAL_SUBSCRIPTION,
    RealBalanceTransaction.Kind.REFERRAL_TOURNAMENT,
    RealBalanceTransaction.Kind.REFERRAL_BALANCE_TOP_UP,
)

_CHART_MONTHS = {
    1: "янв",
    2: "фев",
    3: "мар",
    4: "апр",
    5: "май",
    6: "июн",
    7: "июл",
    8: "авг",
    9: "сен",
    10: "окт",
    11: "ноя",
    12: "дек",
}


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
        referral_income=Sum("amount", filter=Q(kind__in=REFERRAL_EARNING_KINDS)),
    )

    total = values["total"] or Decimal("0.00")
    subscription_income = values["subscription_income"] or Decimal("0.00")
    tournament_income = values["tournament_income"] or Decimal("0.00")
    referral_income = values["referral_income"] or Decimal("0.00")

    return {
        "label": label,
        "days": days,
        "total": total,
        "total_display": format_money(total),
        "subscription_income": subscription_income,
        "subscription_income_display": format_money(subscription_income),
        "tournament_income": tournament_income,
        "tournament_income_display": format_money(tournament_income),
        "referral_income": referral_income,
        "referral_income_display": format_money(referral_income),
        "subscription_purchases": values["subscription_purchases"],
    }


def _compact_chart_value(value: Decimal) -> str:
    value = Decimal(value)
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    if absolute >= Decimal("1000000"):
        compact = absolute / Decimal("1000000")
        text = f"{compact:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{text}M"
    if absolute >= Decimal("1000"):
        compact = absolute / Decimal("1000")
        text = f"{compact:.0f}" if compact >= 10 else f"{compact:.1f}".rstrip("0").rstrip(".")
        return f"{sign}{text}K"
    return f"{sign}{absolute:.0f}"


def _build_income_chart(queryset, *, days: int = 30) -> dict:
    end_day = timezone.localdate()
    start_day = end_day - timedelta(days=days - 1)
    daily = {start_day + timedelta(days=index): Decimal("0.00") for index in range(days)}

    for created_at, amount in queryset.filter(
        created_at__gte=timezone.now() - timedelta(days=days)
    ).values_list("created_at", "amount"):
        created_day = timezone.localtime(created_at).date() if timezone.is_aware(created_at) else created_at.date()
        if created_day in daily:
            daily[created_day] += amount or Decimal("0.00")

    cumulative = Decimal("0.00")
    raw_points = []
    scale_candidates = [Decimal("1.00")]
    for day, amount in daily.items():
        cumulative += amount
        raw_points.append((day, amount, cumulative))
        scale_candidates.extend((amount, cumulative))

    scale = max(scale_candidates)
    plot_left = 42.0
    plot_right = 530.0
    zero_y = 166.0
    positive_height = 116.0
    negative_height = 34.0
    step = (plot_right - plot_left) / max(days - 1, 1)
    bar_width = max(4.0, min(10.0, step * 0.56))

    points = []
    line_parts = []
    labels = []
    for index, (day, amount, running_total) in enumerate(raw_points):
        x = plot_left + (step * index)
        bar_height = float((amount / scale) * Decimal(str(positive_height))) if amount > 0 else 0.0
        line_y = zero_y - float((running_total / scale) * Decimal(str(positive_height)))
        point = {
            "x": round(x, 2),
            "bar_x": round(x - (bar_width / 2), 2),
            "bar_y": round(zero_y - bar_height, 2),
            "bar_height": round(max(bar_height, 1.2) if amount > 0 else 0.0, 2),
            "line_y": round(line_y, 2),
            "amount": amount,
            "cumulative": running_total,
        }
        points.append(point)
        line_parts.append(f"{'M' if index == 0 else 'L'} {point['x']} {point['line_y']}")

        if index % 5 == 0 or index == days - 1:
            labels.append(
                {
                    "x": point["x"],
                    "text": f"{day.day} {_CHART_MONTHS[day.month]}",
                }
            )

    half_scale = scale / Decimal("2")
    ticks = [
        {"y": round(zero_y - positive_height, 2), "label": _compact_chart_value(scale)},
        {"y": round(zero_y - (positive_height / 2), 2), "label": _compact_chart_value(half_scale)},
        {"y": zero_y, "label": "0"},
        {"y": round(zero_y + negative_height, 2), "label": _compact_chart_value(-half_scale)},
    ]

    total = raw_points[-1][2] if raw_points else Decimal("0.00")
    return {
        "days": days,
        "period_label": "30 дней",
        "points": points,
        "labels": labels,
        "ticks": ticks,
        "line_path": " ".join(line_parts),
        "bar_width": round(bar_width, 2),
        "zero_y": zero_y,
        "plot_left": plot_left,
        "plot_right": plot_right,
        "total": total,
        "total_display": format_money(total),
        "total_sign": "+" if total > 0 else "",
    }


def build_earnings_context(user) -> dict:
    if user.role != User.Role.ANALYST:
        empty_transactions = RealBalanceTransaction.objects.none()
        return {
            "earnings_all_time": _period_summary(
                empty_transactions,
                label="За всё время",
            ),
            "earnings_periods": [],
            "earnings_chart": _build_income_chart(empty_transactions),
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
        "earnings_chart": _build_income_chart(earning_transactions),
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

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from game.models import PredictionCoupon
from wallets.models import RealBalanceTransaction
from wallets.services import ensure_real_balance, format_coins, format_money

from .models import AnalystPaidSubscription, User
from .vip import annotate_vip_status, attach_vip_status_to_user


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


def _svg_number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _signed_coins(value: Decimal) -> str:
    integer_value = int(value)
    prefix = "+" if integer_value > 0 else ""
    return f"{prefix}{format_coins(integer_value)}"


def _coupon_profit(*, state_status: str, stake: Decimal, possible_payout: Decimal) -> Decimal:
    stake = stake or Decimal("0.00")
    possible_payout = possible_payout or Decimal("0.00")
    if state_status == PredictionCoupon.StateStatus.WIN:
        return possible_payout - stake
    if state_status == PredictionCoupon.StateStatus.LOSE:
        return -stake
    return Decimal("0.00")


def _build_income_chart(
    queryset,
    *,
    days: int | None = 30,
    period_label: str = "30 дней",
    period_caption: str = "за 30 дней",
) -> dict:
    settled_queryset = queryset.filter(settled_at__isnull=False)
    end_day = timezone.localdate()

    if days is None:
        earliest_settled_at = (
            settled_queryset.order_by("settled_at")
            .values_list("settled_at", flat=True)
            .first()
        )
        if earliest_settled_at:
            start_day = (
                timezone.localtime(earliest_settled_at).date()
                if timezone.is_aware(earliest_settled_at)
                else earliest_settled_at.date()
            )
        else:
            start_day = end_day - timedelta(days=29)
    else:
        start_day = end_day - timedelta(days=days - 1)
        settled_queryset = settled_queryset.filter(
            settled_at__gte=timezone.now() - timedelta(days=days)
        )

    day_count = max((end_day - start_day).days + 1, 1)
    daily = {
        start_day + timedelta(days=index): Decimal("0.00")
        for index in range(day_count)
    }

    settled_coupons = settled_queryset.values_list(
        "settled_at",
        "state_status",
        "total_stake",
        "possible_payout",
    )

    for settled_at, state_status, total_stake, possible_payout in settled_coupons:
        settled_day = (
            timezone.localtime(settled_at).date()
            if timezone.is_aware(settled_at)
            else settled_at.date()
        )
        if settled_day not in daily:
            continue
        daily[settled_day] += _coupon_profit(
            state_status=state_status,
            stake=total_stake,
            possible_payout=possible_payout,
        )

    cumulative = Decimal("0.00")
    raw_points = []
    for day, amount in daily.items():
        cumulative += amount
        raw_points.append((day, amount, cumulative))

    positive_scale = max(
        [Decimal("1.00")]
        + [
            value
            for _, amount, running in raw_points
            for value in (amount, running)
            if value > 0
        ]
    )
    negative_scale = max(
        [Decimal("1.00")]
        + [
            abs(value)
            for _, amount, running in raw_points
            for value in (amount, running)
            if value < 0
        ]
    )

    plot_left = 42.0
    plot_right = 530.0
    zero_y = 166.0
    positive_height = 116.0
    negative_height = 34.0
    step = (plot_right - plot_left) / max(day_count - 1, 1)
    bar_width = max(2.0, min(10.0, step * 0.56))

    points = []
    line_parts = []
    labels = []
    label_step = max(1, round((day_count - 1) / 5))

    for index, (day, amount, running_total) in enumerate(raw_points):
        x = plot_left + (step * index)

        if amount > 0:
            bar_height = float((amount / positive_scale) * Decimal(str(positive_height)))
            bar_y = zero_y - bar_height
            bar_fill = "#0b56fa"
        elif amount < 0:
            bar_height = float((abs(amount) / negative_scale) * Decimal(str(negative_height)))
            bar_y = zero_y
            bar_fill = "#707072"
        else:
            bar_height = 0.0
            bar_y = zero_y
            bar_fill = "#0b56fa"

        if running_total >= 0:
            line_y = zero_y - float(
                (running_total / positive_scale) * Decimal(str(positive_height))
            )
        else:
            line_y = zero_y + float(
                (abs(running_total) / negative_scale) * Decimal(str(negative_height))
            )

        point = {
            "x": _svg_number(x),
            "bar_x": _svg_number(x - (bar_width / 2)),
            "bar_y": _svg_number(bar_y),
            "bar_height": _svg_number(max(bar_height, 1.2) if amount else 0.0),
            "has_bar": bool(amount),
            "bar_fill": bar_fill,
            "line_y": _svg_number(line_y),
            "date": day.strftime("%d.%m.%Y"),
            "date_short": f"{day.day} {_CHART_MONTHS[day.month]}",
            "amount_display": _signed_coins(amount),
            "cumulative_display": _signed_coins(running_total),
        }
        points.append(point)
        line_parts.append(
            f"{'M' if index == 0 else 'L'} {point['x']} {point['line_y']}"
        )

        if index % label_step == 0 or index == day_count - 1:
            labels.append(
                {
                    "x": point["x"],
                    "text": point["date_short"],
                }
            )

    ticks = [
        {
            "y": _svg_number(zero_y - positive_height),
            "label_y": _svg_number(zero_y - positive_height + 3),
            "label": _compact_chart_value(positive_scale),
        },
        {
            "y": _svg_number(zero_y - (positive_height / 2)),
            "label_y": _svg_number(zero_y - (positive_height / 2) + 3),
            "label": _compact_chart_value(positive_scale / Decimal("2")),
        },
        {
            "y": _svg_number(zero_y),
            "label_y": _svg_number(zero_y + 3),
            "label": "0",
        },
        {
            "y": _svg_number(zero_y + negative_height),
            "label_y": _svg_number(zero_y + negative_height + 3),
            "label": _compact_chart_value(-negative_scale),
        },
    ]

    total = raw_points[-1][2] if raw_points else Decimal("0.00")
    if total > 0:
        total_color = "#54db87"
    elif total < 0:
        total_color = "#ff5c67"
    else:
        total_color = "#ffffff"

    return {
        "days": day_count,
        "period_label": period_label,
        "period_caption": period_caption,
        "points": points,
        "labels": labels,
        "ticks": ticks,
        "line_path": " ".join(line_parts),
        "bar_width": _svg_number(bar_width),
        "zero_y": _svg_number(zero_y),
        "plot_left": _svg_number(plot_left),
        "plot_right": _svg_number(plot_right),
        "total_display": format_coins(int(total)),
        "total_sign": "+" if total > 0 else "",
        "total_color": total_color,
    }


def _income_charts(queryset) -> dict:
    return {
        "7": _build_income_chart(
            queryset,
            days=7,
            period_label="7 дней",
            period_caption="за 7 дней",
        ),
        "30": _build_income_chart(
            queryset,
            days=30,
            period_label="30 дней",
            period_caption="за 30 дней",
        ),
        "90": _build_income_chart(
            queryset,
            days=90,
            period_label="90 дней",
            period_caption="за 90 дней",
        ),
        "all": _build_income_chart(
            queryset,
            days=None,
            period_label="Все время",
            period_caption="за всё время",
        ),
    }


def build_earnings_context(user) -> dict:
    if user.role != User.Role.ANALYST:
        empty_transactions = RealBalanceTransaction.objects.none()
        empty_charts = _income_charts(PredictionCoupon.objects.none())
        return {
            "earnings_all_time": _period_summary(
                empty_transactions,
                label="За всё время",
            ),
            "earnings_periods": [],
            "earnings_chart": empty_charts["30"],
            "earnings_charts": empty_charts,
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
    settled_prediction_coupons = PredictionCoupon.objects.filter(
        author=user,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        state_status__in=(
            PredictionCoupon.StateStatus.WIN,
            PredictionCoupon.StateStatus.LOSE,
            PredictionCoupon.StateStatus.REFUND,
        ),
    )
    earnings_charts = _income_charts(settled_prediction_coupons)

    active_paid_subscriptions = list(
        annotate_vip_status(
            AnalystPaidSubscription.objects.filter(
                analyst=user,
                expires_at__gt=now,
            ).select_related("subscriber", "subscriber__analyst_profile", "plan"),
            user_outer_ref="subscriber_id",
        )
        .order_by("-expires_at", "-id")
    )
    for subscription in active_paid_subscriptions:
        attach_vip_status_to_user(subscription.subscriber, subscription)

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
        "earnings_chart": earnings_charts["30"],
        "earnings_charts": earnings_charts,
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

from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from payments.models import Payment
from wallets.services import format_money

from cabinet.models import ReferralVisit, User
from cabinet.presence import presence_payloads


def build_admin_users_context(params):
    payments = (
        Payment.objects.filter(
            user_id=OuterRef("pk"), status=Payment.Status.SUCCEEDED,
            is_test=False, refunded_at__isnull=True,
        )
        .order_by().values("user_id").annotate(total=Sum("amount_rub"))
    )
    referrals = (
        ReferralVisit.objects.filter(
            referrer_id=OuterRef("pk"), registered_at__isnull=False,
            visitor__isnull=False,
        )
        .order_by().values("referrer_id")
        .annotate(total=Count("visitor_id", distinct=True))
    )
    users = (
        User.objects.filter(is_staff=False, is_superuser=False, bot_account__isnull=True)
        .annotate(
            invested_rub=Coalesce(
                Subquery(payments.values("total")[:1]), Value(Decimal("0")),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            ),
            referrals_count=Coalesce(Subquery(referrals.values("total")[:1]), Value(0)),
        )
        .order_by("-date_joined", "-pk")
    )
    page = Paginator(users, 50).get_page(params.get("page"))
    people = list(page.object_list)
    now = timezone.now()
    statuses = presence_payloads(
        [user.pk for user in people],
        fallback_last_seen={user.pk: user.last_login for user in people}, now=now,
    )
    rows = []
    for user in people:
        status = statuses[user.pk]
        rows.append({
            "username": user.username,
            "profile_url": reverse(
                "front:expert_profile" if user.is_analyst else "cabinet:user_profile",
                kwargs={"username": user.username},
            ),
            "registered_at": user.date_joined,
            "last_seen_at": status["last_seen_at"],
            "is_online": status["is_online"],
            "status_label": "В сети" if status["is_online"] else "Не в сети",
            "invested_display": format_money(user.invested_rub),
            "referrals_count": user.referrals_count,
        })
    return {
        "rows": rows, "users_page": page, "active_tab": "admin_users",
        "page_class": "profile", "updated_at": now,
        "display_timezone": timezone.get_current_timezone_name(),
    }

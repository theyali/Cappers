from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import ReferralVisit


REFERRAL_ACTION_SUBSCRIPTION = "subscription"
REFERRAL_ACTION_TOURNAMENT = "tournament"
REFERRAL_ACTION_BALANCE_TOP_UP = "balance_top_up"

REFERRAL_PERCENT_FIELDS = {
    REFERRAL_ACTION_SUBSCRIPTION: "referral_subscription_percent",
    REFERRAL_ACTION_TOURNAMENT: "referral_tournament_percent",
    REFERRAL_ACTION_BALANCE_TOP_UP: "referral_balance_topup_percent",
}

SESSION_REFERRER_KEY = "referral_referrer_id"
SESSION_VISIT_KEY = "referral_visit_id"
LEGACY_SESSION_ANALYST_KEY = "capper_referral_analyst_id"
LEGACY_SESSION_VISIT_KEY = "capper_referral_visit_id"


def _session_key(request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


@transaction.atomic
def record_referral_visit(request, referrer):
    """Record one unique browser session and keep total click count separately."""
    if request.user.is_authenticated and request.user.pk == referrer.pk:
        return None

    session_key = _session_key(request)
    visitor = request.user if request.user.is_authenticated else None
    visit, created = ReferralVisit.objects.select_for_update().get_or_create(
        referrer=referrer,
        session_key=session_key,
        defaults={"visitor": visitor, "visits_count": 1},
    )

    if not created:
        visit.visits_count += 1
        update_fields = ["visits_count", "last_seen_at"]
        if visitor is not None and visit.visitor_id != visitor.pk:
            visit.visitor = visitor
            update_fields.append("visitor")
        visit.save(update_fields=update_fields)

    request.session[SESSION_REFERRER_KEY] = referrer.pk
    request.session[SESSION_VISIT_KEY] = visit.pk
    request.session.pop(LEGACY_SESSION_ANALYST_KEY, None)
    request.session.pop(LEGACY_SESSION_VISIT_KEY, None)
    request.session.modified = True
    return visit


@transaction.atomic
def mark_referral_subscription(request, analyst):
    """Attribute a follow to the referrer link stored in the current session."""
    if not request.user.is_authenticated or request.user.pk == analyst.pk:
        return None

    visit = None
    visit_id = request.session.get(SESSION_VISIT_KEY) or request.session.get(LEGACY_SESSION_VISIT_KEY)
    session_referrer_id = request.session.get(SESSION_REFERRER_KEY) or request.session.get(LEGACY_SESSION_ANALYST_KEY)
    if visit_id and session_referrer_id == analyst.pk:
        visit = (
            ReferralVisit.objects.select_for_update()
            .filter(pk=visit_id, referrer=analyst)
            .first()
        )

    if visit is None:
        visit = (
            ReferralVisit.objects.select_for_update()
            .filter(referrer=analyst, visitor=request.user, subscribed_at__isnull=True)
            .order_by("-last_seen_at", "-id")
            .first()
        )

    if visit is None:
        return None

    already_converted = (
        ReferralVisit.objects.filter(
            referrer=analyst,
            visitor=request.user,
            subscribed_at__isnull=False,
        )
        .exclude(pk=visit.pk)
        .exists()
    )
    if already_converted:
        if visit.visitor_id != request.user.pk:
            visit.visitor = request.user
            visit.save(update_fields=["visitor", "last_seen_at"])
        return visit

    update_fields = []
    if visit.visitor_id != request.user.pk:
        visit.visitor = request.user
        update_fields.append("visitor")
    if visit.subscribed_at is None:
        visit.subscribed_at = timezone.now()
        update_fields.append("subscribed_at")
    if update_fields:
        update_fields.append("last_seen_at")
        visit.save(update_fields=update_fields)
    return visit


@transaction.atomic
def mark_referral_registration(request, user):
    """Bind a new account to the referral visit stored before registration."""
    if not getattr(user, "pk", None):
        return None

    visit_id = request.session.get(SESSION_VISIT_KEY) or request.session.get(LEGACY_SESSION_VISIT_KEY)
    session_referrer_id = request.session.get(SESSION_REFERRER_KEY) or request.session.get(LEGACY_SESSION_ANALYST_KEY)
    if not visit_id or not session_referrer_id or session_referrer_id == user.pk:
        return None

    visit = (
        ReferralVisit.objects.select_for_update()
        .filter(pk=visit_id, referrer_id=session_referrer_id)
        .first()
    )
    if visit is None:
        return None

    update_fields = []
    if visit.visitor_id != user.pk:
        visit.visitor = user
        update_fields.append("visitor")
    if visit.registered_at is None:
        visit.registered_at = timezone.now()
        update_fields.append("registered_at")
    if update_fields:
        update_fields.append("last_seen_at")
        visit.save(update_fields=update_fields)
    return visit


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _referral_percent(action: str) -> Decimal:
    field = REFERRAL_PERCENT_FIELDS.get(action)
    if not field:
        return Decimal("0")

    from back.models import WebsiteSettings

    return _decimal(getattr(WebsiteSettings.load(), field, 0))


def _referrer_for_user(user):
    if not getattr(user, "pk", None):
        return None

    visit = (
        ReferralVisit.objects.filter(visitor=user, registered_at__isnull=False)
        .exclude(referrer=user)
        .select_related("referrer")
        .order_by("registered_at", "first_seen_at", "id")
        .first()
    )
    if visit is None or not visit.referrer.is_analyst:
        return None
    return visit.referrer


def credit_referral_income(referred_user, source_amount, action: str, *, related_obj=None, note: str = ""):
    referrer = _referrer_for_user(referred_user)
    if referrer is None:
        return None

    percent = _referral_percent(action)
    if percent <= 0:
        return None

    source_amount = _decimal(source_amount)
    if source_amount <= 0:
        return None

    amount = (source_amount * percent / Decimal("100")).quantize(Decimal("0.01"))
    if amount <= 0:
        return None

    from wallets.models import RealBalanceTransaction
    from wallets.services import credit_real_balance

    kind_by_action = {
        REFERRAL_ACTION_SUBSCRIPTION: RealBalanceTransaction.Kind.REFERRAL_SUBSCRIPTION,
        REFERRAL_ACTION_TOURNAMENT: RealBalanceTransaction.Kind.REFERRAL_TOURNAMENT,
        REFERRAL_ACTION_BALANCE_TOP_UP: RealBalanceTransaction.Kind.REFERRAL_BALANCE_TOP_UP,
    }
    kind = kind_by_action.get(action)
    if not kind:
        return None

    return credit_real_balance(
        referrer,
        amount,
        kind,
        related_obj=related_obj,
        note=note or f"Реферальное начисление @{referred_user.username}",
    )

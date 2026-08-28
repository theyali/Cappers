from django.db import transaction
from django.utils import timezone

from .models import CapperReferralVisit


SESSION_ANALYST_KEY = "capper_referral_analyst_id"
SESSION_VISIT_KEY = "capper_referral_visit_id"


def _session_key(request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


@transaction.atomic
def record_referral_visit(request, analyst):
    """Record one unique browser session and keep total click count separately."""
    if request.user.is_authenticated and request.user.pk == analyst.pk:
        return None

    session_key = _session_key(request)
    visitor = request.user if request.user.is_authenticated else None
    visit, created = CapperReferralVisit.objects.select_for_update().get_or_create(
        analyst=analyst,
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

    request.session[SESSION_ANALYST_KEY] = analyst.pk
    request.session[SESSION_VISIT_KEY] = visit.pk
    request.session.modified = True
    return visit


@transaction.atomic
def mark_referral_subscription(request, analyst):
    """Attribute a follow to the capper referral link stored in the current session."""
    if not request.user.is_authenticated or request.user.pk == analyst.pk:
        return None

    visit = None
    visit_id = request.session.get(SESSION_VISIT_KEY)
    session_analyst_id = request.session.get(SESSION_ANALYST_KEY)
    if visit_id and session_analyst_id == analyst.pk:
        visit = (
            CapperReferralVisit.objects.select_for_update()
            .filter(pk=visit_id, analyst=analyst)
            .first()
        )

    if visit is None:
        visit = (
            CapperReferralVisit.objects.select_for_update()
            .filter(analyst=analyst, visitor=request.user, subscribed_at__isnull=True)
            .order_by("-last_seen_at", "-id")
            .first()
        )

    if visit is None:
        return None

    already_converted = (
        CapperReferralVisit.objects.filter(
            analyst=analyst,
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

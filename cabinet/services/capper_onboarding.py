from django.urls import reverse

from cabinet.models import AnalystProfile, User


def get_pending_capper_onboarding_url(user) -> str:
    """Resume a requested capper profile without publishing an incomplete account."""
    if not user.is_authenticated or user.role != User.Role.READER:
        return ""
    if AnalystProfile.objects.filter(
        user=user, is_public=False, onboarding_completed_at__isnull=True,
    ).exists():
        return reverse("cabinet:capper_onboarding", kwargs={"step": 1})
    return ""

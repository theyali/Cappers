from django.urls import reverse

from .models import NotificationSectionState
from .services import section_badge_payload


SECTION_BY_VIEW = {
    "front:following_feed": "following",
    "game:match_list": "matches",
    "game:match_list_live": "matches",
    "game:match_list_filtered": "matches",
    "game:match_detail": "matches",
    "tournaments:index": "tournaments",
    "tournaments:detail": "tournaments",
    "tournaments:results": "tournaments",
    "cabinet:bonuses": "bonuses",
    "cabinet:bonus_tasks": "bonus_tasks",
    "cabinet:bonus_levels": "bonus_levels",
    "cabinet:referrals": "referrals",
}


def _section_visit_config(request):
    if not getattr(getattr(request, "user", None), "is_authenticated", False):
        return None
    view_name = getattr(getattr(request, "resolver_match", None), "view_name", "")
    profile_sections = []
    section = SECTION_BY_VIEW.get(view_name, "")
    if view_name == "cabinet:profile":
        profile_sections = ["achievements", "following", "copybetting"]
        if request.user.is_analyst:
            profile_sections += ["predictions", "followers", "earnings"]
        tab = request.GET.get("tab", "profile")
        section = tab if tab in profile_sections else ""
    return {
        "section": section,
        "profile_sections": profile_sections,
        "urls": {
            key: reverse("notifications:mark_section_read", args=[key])
            for key, _label in NotificationSectionState.Section.choices
        },
    }


def section_badges(request):
    payload = section_badge_payload(getattr(request, "user", None))
    return {
        "notification_section_badges": payload["badges"],
        "notification_section_counts": payload["counts"],
        "notification_section_visit": _section_visit_config(request),
    }


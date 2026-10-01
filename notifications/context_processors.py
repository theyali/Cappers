from .services import section_badge_payload


def section_badges(request):
    payload = section_badge_payload(getattr(request, "user", None))
    return {
        "notification_section_badges": payload["badges"],
        "notification_section_counts": payload["counts"],
    }


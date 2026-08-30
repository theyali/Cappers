from __future__ import annotations

import json

from django.conf import settings
from django.urls import reverse

from cappers.timezone_service import (
    TIMEZONE_BOOTSTRAP_SCRIPT,
    activate_request_timezone,
    deactivate_request_timezone,
)


def _static_url(path: str) -> str:
    base = str(settings.STATIC_URL or "/static/")
    if not base.startswith(("/", "http://", "https://")):
        base = f"/{base}"
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _html_injection() -> bytes:
    timing_url = reverse("game:match_timing")
    js_url = _static_url("front/js/match-timing.js")
    payload = (
        TIMEZONE_BOOTSTRAP_SCRIPT
        + f'<script>window.CAPPERS_MATCH_TIMING_URL={json.dumps(timing_url)};</script>'
        + f'<script src="{js_url}" defer></script>'
    )
    return payload.encode("utf-8")


class UserContextMiddleware:
    """Activate the browser timezone and keep authenticated presence fresh."""

    def __init__(self, get_response):
        self.get_response = get_response
        self._injection = None

    def __call__(self, request):
        activate_request_timezone(request)

        try:
            user = getattr(request, "user", None)
            if getattr(user, "is_authenticated", False):
                try:
                    from cabinet.presence import touch_user_presence

                    touch_user_presence(user)
                except Exception:
                    # Presence must never break a normal page request.
                    pass

            response = self.get_response(request)
            return self._inject_html(response)
        finally:
            deactivate_request_timezone()

    def _inject_html(self, response):
        if getattr(response, "streaming", False):
            return response
        content_type = str(response.get("Content-Type", "")).lower()
        if "text/html" not in content_type:
            return response

        content = bytes(response.content)
        marker = b"<head>"
        index = content.lower().find(marker)
        if index < 0:
            return response

        if self._injection is None:
            self._injection = _html_injection()
        insert_at = index + len(marker)
        response.content = content[:insert_at] + self._injection + content[insert_at:]
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
        return response

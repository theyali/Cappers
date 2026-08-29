from __future__ import annotations

import json
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.urls import reverse
from django.utils import timezone


TIMEZONE_COOKIE = "cappers_tz"
TIMEZONE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60


_TIMEZONE_BOOTSTRAP = r"""<script>(function(){try{var z=Intl.DateTimeFormat().resolvedOptions().timeZone;if(!z)return;var n='cappers_tz',c='',parts=document.cookie.split(';');for(var i=0;i<parts.length;i++){var p=parts[i].trim();if(p.indexOf(n+'=')===0){c=decodeURIComponent(p.slice(n.length+1));break;}}if(c===z){try{sessionStorage.removeItem('cappers:tz-reload:'+z);}catch(e){}return;}document.cookie=n+'='+encodeURIComponent(z)+'; Path=/; Max-Age=31536000; SameSite=Lax'+(location.protocol==='https:'?'; Secure':'');var k='cappers:tz-reload:'+z;try{if(sessionStorage.getItem(k)==='1')return;sessionStorage.setItem(k,'1');}catch(e){}location.reload();}catch(e){}})();</script>"""


def _safe_timezone_name(raw_value: str | None) -> str:
    candidate = unquote(str(raw_value or "").strip()) or settings.TIME_ZONE
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError):
        return settings.TIME_ZONE
    return candidate


def _static_url(path: str) -> str:
    base = str(settings.STATIC_URL or "/static/")
    if not base.startswith(("/", "http://", "https://")):
        base = f"/{base}"
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _html_injection() -> bytes:
    timing_url = reverse("game:match_timing")
    css_url = _static_url("front/css/match-timing.css")
    js_url = _static_url("front/js/match-timing.js")
    payload = (
        _TIMEZONE_BOOTSTRAP
        + f'<link rel="stylesheet" href="{css_url}">'
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
        timezone_name = _safe_timezone_name(request.COOKIES.get(TIMEZONE_COOKIE))
        timezone.activate(ZoneInfo(timezone_name))
        request.user_timezone_name = timezone_name

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
            timezone.deactivate()

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

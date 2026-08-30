from __future__ import annotations

from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone


TIMEZONE_COOKIE = "cappers_tz"
TIMEZONE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60
TIMEZONE_BOOTSTRAP_SCRIPT = r"""<script>(function(){try{var z=Intl.DateTimeFormat().resolvedOptions().timeZone;if(!z)return;var n='cappers_tz',c='',parts=document.cookie.split(';');for(var i=0;i<parts.length;i++){var p=parts[i].trim();if(p.indexOf(n+'=')===0){c=decodeURIComponent(p.slice(n.length+1));break;}}if(c===z){try{sessionStorage.removeItem('cappers:tz-reload:'+z);}catch(e){}return;}document.cookie=n+'='+encodeURIComponent(z)+'; Path=/; Max-Age=31536000; SameSite=Lax'+(location.protocol==='https:'?'; Secure':'');var k='cappers:tz-reload:'+z;try{if(sessionStorage.getItem(k)==='1')return;sessionStorage.setItem(k,'1');}catch(e){}location.reload();}catch(e){}})();</script>"""


def safe_timezone_name(raw_value: str | None) -> str:
    candidate = unquote(str(raw_value or "").strip())[:128] or settings.TIME_ZONE
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return settings.TIME_ZONE
    return candidate


def activate_request_timezone(request) -> str:
    timezone_name = safe_timezone_name(request.COOKIES.get(TIMEZONE_COOKIE))
    timezone.activate(ZoneInfo(timezone_name))
    request.user_timezone_name = timezone_name
    return timezone_name


def deactivate_request_timezone() -> None:
    timezone.deactivate()


def current_timezone_name() -> str:
    return timezone.get_current_timezone_name()

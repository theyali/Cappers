from __future__ import annotations

from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone


TIMEZONE_COOKIE = "cappers_tz"
TIMEZONE_COOKIE_MAX_AGE = 365 * 24 * 60 * 60
TIMEZONE_BOOTSTRAP_SCRIPT = r"""<script>(function(){try{var z=Intl.DateTimeFormat().resolvedOptions().timeZone;if(!z)return;var n='cappers_tz',c='',parts=document.cookie.split(';');for(var i=0;i<parts.length;i++){var p=parts[i].trim();if(p.indexOf(n+'=')===0){c=decodeURIComponent(p.slice(n.length+1));break;}}if(c===z){try{sessionStorage.removeItem('cappers:tz-reload:'+z);}catch(e){}return;}document.cookie=n+'='+encodeURIComponent(z)+'; Path=/; Max-Age=31536000; SameSite=Lax'+(location.protocol==='https:'?'; Secure':'');var k='cappers:tz-reload:'+z;try{if(sessionStorage.getItem(k)==='1')return;sessionStorage.setItem(k,'1');}catch(e){}location.reload();}catch(e){}})();</script>"""
SCROLL_RESTORE_BOOTSTRAP_SCRIPT = r"""<script>(function(){try{if(!window.sessionStorage)return;if('scrollRestoration'in history)history.scrollRestoration='manual';var k='cappers:scroll:'+location.pathname+location.search;var y=parseInt(sessionStorage.getItem(k)||'',10);var has=Number.isFinite(y)&&y>0;var save=function(){try{sessionStorage.setItem(k,String(Math.max(0,window.scrollY||document.documentElement.scrollTop||0)));}catch(e){}};window.addEventListener('pagehide',save);window.addEventListener('beforeunload',save);if(!has)return;document.documentElement.setAttribute('data-scroll-restoring','true');var s=document.createElement('style');s.textContent='html[data-scroll-restoring] body{visibility:hidden;}';document.head.appendChild(s);var tries=0;var release=function(){document.documentElement.removeAttribute('data-scroll-restoring');};var restore=function(){tries++;window.scrollTo(0,y);if(tries<12&&Math.abs((window.scrollY||0)-y)>2){requestAnimationFrame(restore);return;}release();};if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',function(){requestAnimationFrame(restore);},{once:true});}else{requestAnimationFrame(restore);}window.addEventListener('load',function(){restore();setTimeout(release,80);},{once:true});setTimeout(release,1200);}catch(e){document.documentElement.removeAttribute('data-scroll-restoring');}})();</script>"""


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

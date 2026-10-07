import ipaddress
import json
import logging
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from cabinet.models import User


logger = logging.getLogger(__name__)

REGISTRATIONS_PER_IP = 5
REGISTRATION_WINDOW = timedelta(hours=1)
SMARTCAPTCHA_VALIDATE_URL = "https://smartcaptcha.yandexcloud.net/validate"


def client_ip(request) -> str | None:
    # nginx passes the client address in X-Real-IP (deploy/nginx).
    ip = (request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "").strip()
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def registration_limit_reached(request) -> bool:
    ip = client_ip(request)
    if not ip:
        return False
    since = timezone.now() - REGISTRATION_WINDOW
    return User.objects.filter(registration_ip=ip, date_joined__gte=since).count() >= REGISTRATIONS_PER_IP


def captcha_client_key() -> str:
    """Site key of Yandex SmartCaptcha; empty while the captcha is not configured."""
    if settings.SMARTCAPTCHA_CLIENT_KEY and settings.SMARTCAPTCHA_SERVER_KEY:
        return settings.SMARTCAPTCHA_CLIENT_KEY
    return ""


def captcha_passed(request) -> bool:
    if not captcha_client_key():
        return True
    token = request.POST.get("smart-token", "")
    if not token:
        return False
    data = urllib.parse.urlencode(
        {"secret": settings.SMARTCAPTCHA_SERVER_KEY, "token": token, "ip": client_ip(request) or ""}
    ).encode()
    try:
        with urllib.request.urlopen(SMARTCAPTCHA_VALIDATE_URL, data=data, timeout=5) as response:
            payload = json.loads(response.read().decode())
    except (OSError, ValueError):
        # As Yandex recommends, an unavailable check does not block registration;
        # the per-IP limit still applies.
        logger.warning("SmartCaptcha validation is unavailable; registration allowed.", exc_info=True)
        return True
    return payload.get("status") == "ok"

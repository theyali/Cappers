import json
import logging
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import PaymentProviderError

logger = logging.getLogger("payments")

# Credentials from .env.example contain it; a secret everyone can read must
# never be trusted to verify notifications.
PLACEHOLDER_MARK = "change-me"


def credentials_configured(*values: str) -> bool:
    return all(values) and not any(PLACEHOLDER_MARK in value for value in values)


def request_json(provider_title: str, url: str, *, headers: dict, timeout: int, body: dict | None = None) -> dict:
    """Call a provider API (GET, or POST with a JSON body) and return its JSON object."""
    request_headers = {"Accept": "application/json", **headers}
    data = None
    if body is not None:
        request_headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = Request(url, data=data, method="GET" if body is None else "POST", headers=request_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            answer = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        logger.error("%s %s answered HTTP %s: %s", provider_title, url, error.code, _error_text(error))
        raise PaymentProviderError("Платёжный сервис временно недоступен.") from error
    except (URLError, TimeoutError, ValueError) as error:
        logger.error("%s %s failed: %s", provider_title, url, error)
        raise PaymentProviderError("Платёжный сервис временно недоступен.") from error
    if not isinstance(answer, dict):
        raise PaymentProviderError(f"{provider_title}: неожиданный ответ.")
    return answer


def parse_amount(value, provider_title: str) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise PaymentProviderError(f"{provider_title}: неверная сумма «{value}».") from error
    if not amount.is_finite():
        raise PaymentProviderError(f"{provider_title}: неверная сумма «{value}».")
    return amount


def _error_text(error: HTTPError) -> str:
    # The provider's own error message helps to see what it refused; keep it short.
    try:
        return error.read().decode("utf-8", "replace")[:300]
    except Exception:
        return ""

import logging

from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from cabinet.services.registration_guard import client_ip
from payments.services.processing import apply_provider_event
from payments.services.providers.base import InvalidSignature, PaymentProviderError
from payments.services.providers.factory import PaymentProviderFactory

logger = logging.getLogger("payments")


@csrf_exempt
@require_POST
def provider_webhook(request, provider_code: str, event_type: str):
    try:
        provider = PaymentProviderFactory.create(provider_code)
    except PaymentProviderError:
        raise Http404
    try:
        provider.verify_signature(request)
        event = provider.parse_webhook(request, event_type=event_type)
    except InvalidSignature:
        logger.warning("Rejected %s %s notification with a bad signature from %s", provider_code, event_type, client_ip(request))
        return HttpResponseForbidden()
    except PaymentProviderError as error:
        logger.warning("Rejected %s %s notification: %s", provider_code, event_type, error)
        return HttpResponseBadRequest()
    return provider.webhook_response(rejection=apply_provider_event(provider_code, event))

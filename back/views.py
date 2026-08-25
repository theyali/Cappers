from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def ajax_health(request):
    """Small AJAX namespace smoke-test endpoint."""
    return JsonResponse({"status": "ok", "namespace": "back"})

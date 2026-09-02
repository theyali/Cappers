from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .help_service import build_help_payload


@require_GET
def help_content(request, key: str):
    payload = build_help_payload(request, key)
    if payload is None:
        response = JsonResponse(
            {
                "ok": False,
                "error": "Раздел помощи не найден или отключён.",
            },
            status=404,
        )
    else:
        response = JsonResponse({"ok": True, **payload})

    response["Cache-Control"] = "no-store"
    return response

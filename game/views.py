from django.http import JsonResponse


def match_list(request):
    """Temporary endpoint until match models are introduced in Stage 4."""
    return JsonResponse({"matches": []})

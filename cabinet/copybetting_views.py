from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .services.copybetting import build_audience_csv, build_copybetting_context, build_reader_copybetting_context


@login_required
@require_GET
@never_cache
def audience(request):
    if not request.user.is_analyst:
        raise PermissionDenied
    if request.GET.get("export") == "csv":
        response = HttpResponse(build_audience_csv(request.user, request.GET), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="copybetting-audience.csv"'
        return response
    context = build_copybetting_context(request.user, request.GET)
    return JsonResponse({"html": render_to_string("cabinet/includes/_copybetting_content.html", context, request=request)})


@login_required
@require_GET
@never_cache
def reader(request):
    if request.user.is_analyst:
        raise PermissionDenied
    context = build_reader_copybetting_context(request.user, request.GET)
    return JsonResponse({"html": render_to_string("cabinet/includes/_copybetting_reader_content.html", context, request=request)})

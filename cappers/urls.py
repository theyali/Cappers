from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthcheck(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", healthcheck, name="healthcheck"),
    path("", include("front.urls")),
    path("cabinet/", include("cabinet.urls")),
    path("games/", include("game.urls")),
    path("ajax/", include("back.urls")),
]

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.http import JsonResponse
from django.urls import include, path

from . import admin as _admin_config  # noqa: F401
from .seo_views import robots_txt
from .sitemaps import sitemaps


def healthcheck(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("tinymce/", include("tinymce.urls")),
    path("health/", healthcheck, name="healthcheck"),
    path("robots.txt", robots_txt, name="robots_txt"),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    path("pages/", include("pages.urls")),
    path("", include("front.urls")),
    path("cabinet/profile/bots/", include("bots.urls")),
    path("cabinet/", include("cabinet.urls")),
    path("email/", include("account_email.urls")),
    path("games/", include("game.urls")),
    path("tournaments/", include("tournaments.urls")),
    path("notifications/", include("notifications.urls")),
    path("wallets/", include("wallets.urls")),
    path("ajax/", include("back.urls")),
]

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

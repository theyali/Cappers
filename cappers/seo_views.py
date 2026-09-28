from django.http import HttpResponse
from django.urls import reverse

from back.models import WebsiteSettings


def robots_txt(request):
    settings = WebsiteSettings.load()
    sitemap_url = request.build_absolute_uri(reverse("sitemap"))
    content = settings.robots_txt or WebsiteSettings.DEFAULT_ROBOTS_TXT
    content = content.replace("{sitemap_url}", sitemap_url)
    if not content.endswith("\n"):
        content += "\n"
    return HttpResponse(content, content_type="text/plain; charset=utf-8")

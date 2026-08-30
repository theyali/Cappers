from django.db.utils import OperationalError, ProgrammingError

from back.models import WebsiteSettings
from front.models import StaticPage


def website_settings(request):
    try:
        settings = WebsiteSettings.load()
        footer_pages = StaticPage.objects.filter(
            is_published=True,
            show_in_footer=True,
        )
    except (OperationalError, ProgrammingError):
        settings = None
        footer_pages = []

    request.website_settings = settings
    view_name = request.resolver_match.view_name if request.resolver_match else ""

    return {
        "website_settings": settings,
        "footer_static_pages": footer_pages,
        "hide_footer": view_name == "front:prediction_detail",
    }

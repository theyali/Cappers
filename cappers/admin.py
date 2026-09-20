from django.contrib import admin

from .admin_dashboard import build_admin_dashboard_context


admin.site.site_header = "Django Admin"
admin.site.site_title = "Django Admin"
admin.site.index_title = "Панель управления"


if not getattr(admin.site, "_cappers_dashboard_configured", False):
    default_each_context = admin.site.each_context

    def each_context(request):
        context = default_each_context(request)
        context.update(
            build_admin_dashboard_context(
                request,
                context.get("available_apps", []),
            )
        )
        return context

    admin.site.each_context = each_context
    admin.site._cappers_dashboard_configured = True

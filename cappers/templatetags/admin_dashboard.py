from django import template
from django.utils.safestring import mark_safe

from cappers.admin_dashboard import (
    ADMIN_APP_GROUPS,
    ADMIN_APP_GROUP_SOURCES,
    build_admin_dashboard_context,
    group_admin_apps,
)


register = template.Library()


ADMIN_ICONS = {
    "home": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m3 11 9-7 9 7"></path><path d="M5 10v10h14V10M9 20v-6h6v6"></path></svg>',
    "database": '<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5" rx="7" ry="3"></ellipse><path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"></path></svg>',
    "monitor": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="14" rx="2"></rect><path d="M8 21h8M12 18v3"></path></svg>',
    "user": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"></circle><path d="M5 20c.7-4.2 3-6.2 7-6.2s6.3 2 7 6.2"></path></svg>',
    "bell": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9a6 6 0 0 1 12 0v5l2 3H4l2-3V9Z"></path><path d="M9.5 20h5"></path></svg>',
    "bot": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="7" width="16" height="12" rx="3"></rect><path d="M12 3v4M8 12h.01M16 12h.01M8 16h8"></path></svg>',
    "gamepad": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 8h10a4 4 0 0 1 3.8 5.2l-1.2 3.5a2 2 0 0 1-3.2.9L14 16h-4l-2.4 1.6a2 2 0 0 1-3.2-.9l-1.2-3.5A4 4 0 0 1 7 8Z"></path><path d="M7 12h4M9 10v4M16 11h.01M18 13h.01"></path></svg>',
    "wallet": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h14a2 2 0 0 1 2 2v10H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z"></path><path d="M16 10h5v5h-5a2.5 2.5 0 0 1 0-5ZM5 6V4h11"></path></svg>',
    "clock": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2"></path></svg>',
    "file": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h8l4 4v14H6V3Z"></path><path d="M14 3v5h5M9 12h6M9 16h6"></path></svg>',
    "chart": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 20V11M12 20V5M19 20v-8"></path></svg>',
    "seo": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.5"></circle><path d="m15 15 5 5M7 18v2M11 17v3M15 18v2"></path></svg>',
    "search": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6"></circle><path d="m16 16 4 4"></path></svg>',
    "award": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="9" r="5"></circle><path d="m9 13-2 8 5-3 5 3-2-8"></path></svg>',
    "sun": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path></svg>',
    "chevron-right": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3 5 5-5 5"></path></svg>',
    "settings": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"></circle><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.7-1L14.5 3h-5l-.4 3.1a7 7 0 0 0-1.7 1l-2.4-1-2 3.4L5 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.7 1l.4 3.1h5l.4-3.1a7 7 0 0 0 1.7-1l2.4 1 2-3.4L19 13a7 7 0 0 0 .1-1Z"></path></svg>',
    "menu": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"></path></svg>',
    "grid": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="6" height="6" rx="1"></rect><rect x="14" y="4" width="6" height="6" rx="1"></rect><rect x="4" y="14" width="6" height="6" rx="1"></rect><rect x="14" y="14" width="6" height="6" rx="1"></rect></svg>',
}


def _group_key_for_app(app_label):
    for key, source_labels in ADMIN_APP_GROUP_SOURCES.items():
        if app_label in source_labels:
            return key
    return app_label


@register.simple_tag
def admin_app_meta(app_label):
    key = _group_key_for_app(app_label)
    meta = ADMIN_APP_GROUPS.get(key)
    if meta:
        return {"key": key, **meta}
    return {
        "key": app_label,
        "title": app_label.replace("_", " ").title(),
        "subtitle": app_label,
        "icon": "grid",
        "color": "blue",
    }


@register.simple_tag
def admin_grouped_apps(app_list):
    return group_admin_apps(app_list or [])


@register.simple_tag(takes_context=True)
def admin_dashboard_context(context, app_list):
    request = context.get("request")
    if request is None:
        return {
            "dashboard_apps": group_admin_apps(app_list or []),
            "quick_actions": [],
            "recent_actions": [],
        }
    return build_admin_dashboard_context(request, app_list or [])


@register.simple_tag
def admin_icon_svg(icon_name):
    return mark_safe(ADMIN_ICONS.get(icon_name, ADMIN_ICONS["grid"]))

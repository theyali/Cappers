from django import template

from back.content_view import content_view_mode as resolve_content_view_mode
from back.content_view import group_by_sport_and_league


register = template.Library()


@register.simple_tag(takes_context=True)
def content_view_mode(context):
    request = context.get("request")
    if request is None:
        return "grid"
    return resolve_content_view_mode(request)


@register.simple_tag
def group_content_items(items):
    return group_by_sport_and_league(list(items or []))

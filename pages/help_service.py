from django.db.models import Prefetch
from django.template.loader import render_to_string

from .models import HelpAccordionItem, HelpBlock


def get_help_block(key: str):
    items = HelpAccordionItem.objects.filter(is_active=True).order_by("sort_order", "id")
    return (
        HelpBlock.objects.filter(key=key, is_active=True)
        .prefetch_related(Prefetch("items", queryset=items, to_attr="active_items"))
        .first()
    )


def build_help_payload(request, key: str):
    help_block = get_help_block(key)
    if help_block is None:
        return None

    html = render_to_string(
        "pages/includes/_help_modal_content.html",
        {
            "help_block": help_block,
            "help_items": help_block.active_items,
        },
        request=request,
    )
    return {
        "title": help_block.title,
        "html": html,
        "updated_at": help_block.updated_at.isoformat(),
    }

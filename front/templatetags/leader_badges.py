"""Presentation of already-selected ranking badges; never awards or queries DB."""

from datetime import date, datetime

from django import template


register = template.Library()
# Intrinsic SVG dimensions mirror --leader-size-* in main.css for stable SSR.
VARIANTS = {
    "avatar": (1, 20),
    "rating": (1, 28),
    "card": (1, 44),
    "profile": (2, 24),
    "shelf": (None, 68),
    "detail": (1, 104),
}
# BG2's shared shelf uses a slightly larger all-time disk than monthly medals.
SHELF_SIZES = {"month": 62, "all-time": 68}
MONTH_SHORT = (
    "ЯНВ",
    "ФЕВ",
    "МАР",
    "АПР",
    "МАЙ",
    "ИЮН",
    "ИЮЛ",
    "АВГ",
    "СЕН",
    "ОКТ",
    "НОЯ",
    "ДЕК",
)


def _badge_payload(source, size, variant):
    if not isinstance(source, dict) or source.get("kind") not in {"month", "all-time"}:
        return None
    if source.get("status") == "revoked":
        return None
    kind = source["kind"]
    # All-time titles transfer with the ranking, including on the public shelf.
    # Only monthly medals may be displayed as historical achievements.
    if kind == "all-time" and (
        source.get("status") != "active" or source.get("ended_at")
    ):
        return None
    try:
        rank = int(source.get("rank", 1))
    except (TypeError, ValueError):
        return None
    if not 1 <= rank <= (3 if kind == "month" else 10):
        return None

    if kind == "month":
        metal = ("gold", "silver", "bronze")[rank - 1]
    else:
        metal = "gold" if rank == 1 else "silver" if rank <= 3 else "bronze"
    month = source.get("month")
    if month and not isinstance(month, date):
        try:
            month = datetime.strptime(str(month)[:7], "%Y-%m").date()
        except (TypeError, ValueError):
            month = None

    symbol_label = "№1" if rank == 1 else "ТОП-3" if rank <= 3 else "ТОП-10"
    full = size > 44 and (kind == "all-time" or bool(month))
    if kind == "month":
        icon = "month_full" if full else "month_compact"
        ratio = 1.28
        priority = 2 if rank == 1 else 3
    else:
        icon = "all_time_full" if full else "all_time_compact"
        ratio = 1.04
        priority = 0 if rank == 1 else 1 if rank <= 3 else 4

    return {
        **source,
        "rank": rank,
        "metal": metal,
        "icon_template": f"front/svgs/leader_{icon}.svg",
        "width": size,
        "height": round(size * ratio, 2) if full else size,
        "size_variant": variant,
        "full": full,
        "month_short": MONTH_SHORT[month.month - 1] if month else "",
        "shelf_caption": (
            f"{MONTH_SHORT[month.month - 1].title()} {month.year}"
            if kind == "month" and month
            else source.get("shelf_caption") or source.get("label") or ""
        ),
        "symbol_label": symbol_label,
        "symbol_font_size": 15 if rank == 1 else 13 if rank <= 3 else 11,
        "has_wreath": rank <= 3,
        "priority": priority,
        "label": source.get("label") or source.get("title") or "Лидерский знак",
        "historical": kind == "all-time" and source.get("status") == "historical",
    }


@register.simple_tag
def leader_badges_display(
    badges, variant="avatar", more_url="#achievements", more_count=None
):
    variant = variant if variant in VARIANTS else "avatar"
    limit, size = VARIANTS[variant]
    prepared = [
        payload
        for source in (badges or ())
        if (
            payload := _badge_payload(
                source,
                SHELF_SIZES.get(source.get("kind"), size)
                if variant == "shelf" and isinstance(source, dict)
                else size,
                variant,
            )
        )
    ]
    # Stable within a priority: the data owner determines which month represents
    # the author. This presentation helper never invents an award or a date.
    if variant not in {"shelf", "detail"}:
        prepared.sort(key=lambda badge: badge["priority"])
    candidates = (
        prepared
        if variant in {"shelf", "detail"}
        else [badge for badge in prepared if badge.get("status") != "historical"]
    )
    if variant == "profile":
        by_kind = {}
        for badge in candidates:
            by_kind.setdefault(badge["kind"], badge)
        candidates = list(by_kind.values())
    visible = candidates if limit is None else candidates[:limit]
    try:
        more_count = max(0, int(more_count))
    except (TypeError, ValueError):
        more_count = len(prepared) - len(visible)
    return {
        "variant": variant,
        "badges": visible,
        "more_count": more_count if variant == "profile" else 0,
        "more_url": more_url,
        "can_link": variant in {"profile", "shelf", "detail"},
    }

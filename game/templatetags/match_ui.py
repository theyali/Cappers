import re

from django import template


register = template.Library()

_MINUTE_RE = re.compile(r"\d+(?:\+\d+)?")
_HALFTIME_WORDS = ("ht", "half time", "halftime", "interval", "перерыв")
_EXTRA_WORDS = ("extra", "extra time", "et", "aet", "доп")
_FIRST_HALF_WORDS = ("1h", "first half", "1st half", "первый тайм")
_SECOND_HALF_WORDS = ("2h", "second half", "2nd half", "второй тайм")


def _minute_label(match) -> str:
    raw_label = str(getattr(match, "live_minute_label", "") or "").strip()
    found = _MINUTE_RE.search(raw_label)
    if found:
        return f"{found.group(0)}′"

    minute = getattr(match, "live_minute", None)
    if minute not in (None, ""):
        try:
            return f"{int(minute)}′"
        except (TypeError, ValueError):
            pass
    return ""


def _status_text(match) -> str:
    fragments = [str(getattr(match, "time_status", "") or "")]
    raw = getattr(match, "raw_data", None)
    if isinstance(raw, dict):
        for key in ("status", "game_status", "time_status", "period", "phase"):
            value = raw.get(key)
            if isinstance(value, dict):
                fragments.extend(str(item or "") for item in value.values())
            elif value not in (None, ""):
                fragments.append(str(value))
    return " ".join(fragments).strip().lower()


@register.filter
def live_status_label(match) -> str:
    """Human-friendly football LIVE phase used on match cards and match detail."""
    if not match:
        return "LIVE"

    minute_label = _minute_label(match)
    status = str(getattr(match, "time_status", "") or "").strip().lower()
    status_text = _status_text(match)

    if any(word in status_text for word in _HALFTIME_WORDS):
        return "Перерыв"

    if status == "1" or any(word in status_text for word in _FIRST_HALF_WORDS):
        period = "1Т"
    elif status == "2" or any(word in status_text for word in _SECOND_HALF_WORDS):
        period = "2Т"
    elif any(word in status_text for word in _EXTRA_WORDS):
        period = "Extra"
    else:
        minute = getattr(match, "live_minute", None)
        try:
            period = "Extra" if minute is not None and int(minute) > 90 else "LIVE"
        except (TypeError, ValueError):
            period = "LIVE"

    if not minute_label:
        return period
    if period == "Extra":
        return f"Extra {minute_label}"
    return f"{period} - {minute_label}"

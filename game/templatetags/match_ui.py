import re

from django import template


register = template.Library()

_MINUTE_RE = re.compile(r"\d+(?:\+\d+)?")
_HALFTIME_WORDS = ("ht", "half time", "halftime", "interval", "перерыв")
_EXTRA_WORDS = ("extra", "extra time", "et", "aet", "доп")
_FIRST_HALF_WORDS = ("1h", "first half", "1st half", "первый тайм")
_SECOND_HALF_WORDS = ("2h", "second half", "2nd half", "второй тайм")


def _minute_value(match) -> int | None:
    raw_label = str(getattr(match, "live_minute_label", "") or "").strip()
    found = _MINUTE_RE.search(raw_label)
    if found:
        try:
            return int(found.group(0).split("+", 1)[0])
        except (TypeError, ValueError):
            pass

    minute = getattr(match, "live_minute", None)
    if minute not in (None, ""):
        try:
            return int(minute)
        except (TypeError, ValueError):
            pass
    return None


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


def _phase_text(match) -> str:
    """Return only provider fields that can actually describe a match period.

    time_status is intentionally ignored here: for Neurokeff it is a numeric
    game-state flag (for example, 1 means the game is live), not a half number.
    """
    fragments = []
    raw = getattr(match, "raw_data", None)
    if isinstance(raw, dict):
        for key in ("period", "phase", "period_name", "phase_name"):
            value = raw.get(key)
            if isinstance(value, dict):
                fragments.extend(str(item or "") for item in value.values())
            elif value not in (None, ""):
                fragments.append(str(value))
    return " ".join(fragments).strip().lower()


@register.filter
def live_status_label(match) -> str:
    """Human-friendly LIVE phase used on match cards and match detail."""
    if not match:
        return "LIVE"

    minute_value = _minute_value(match)
    minute_label = _minute_label(match)
    phase_text = _phase_text(match)

    if any(word in phase_text for word in _HALFTIME_WORDS):
        return "Перерыв"

    # Explicit period data wins when the provider sends it. The numeric
    # time_status field is not used here because it describes game state.
    if any(word in phase_text for word in _EXTRA_WORDS):
        period = "Extra"
    elif any(word in phase_text for word in _SECOND_HALF_WORDS):
        period = "2Т"
    elif any(word in phase_text for word in _FIRST_HALF_WORDS):
        period = "1Т"
    elif minute_value is not None and minute_value > 45:
        # 90+ stoppage time remains the second half; extra time requires an
        # explicit provider phase marker.
        period = "2Т"
    elif minute_value is not None:
        period = "1Т"
    else:
        period = "LIVE"

    if not minute_label:
        return period
    if period == "Extra":
        return f"Extra {minute_label}"
    return f"{period} - {minute_label}"


@register.simple_tag
def match_card_status(match) -> dict:
    """Initial card status, including the local 10-minute pre-kickoff window."""
    if not match:
        return {"state": "prematch", "label": "Скоро"}

    from game.models import Match

    if match.sync_scope == Match.SyncScope.LIVE:
        return {"state": "live", "label": live_status_label(match)}
    if match.sync_scope == Match.SyncScope.FINISHED:
        return {"state": "finished", "label": match.get_sync_scope_display()}

    if match.sync_scope == Match.SyncScope.PREMATCH:
        from game.services.match_timing import match_timing_payload

        timing = match_timing_payload(match)
        if timing.get("state") == "soon":
            return {"state": "soon", "label": "Скоро начнется"}
        return {"state": "prematch", "label": "Скоро"}

    return {"state": match.sync_scope, "label": match.get_sync_scope_display()}


@register.simple_tag
def match_watched(user, match) -> bool:
    if not user or not getattr(user, "is_authenticated", False) or not match:
        return False
    from notifications.models import MatchWatch

    return MatchWatch.objects.filter(user=user, match=match).exists()

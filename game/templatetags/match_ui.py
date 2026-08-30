import re

from django import template


register = template.Library()

_MINUTE_RE = re.compile(r"\d+(?:\+\d+)?")
_PERIOD_RE = re.compile(r"(?:^|\D)([1-9])(?:\D|$)")
_HALFTIME_WORDS = ("ht", "half time", "halftime", "interval", "перерыв")
_EXTRA_WORDS = ("extra", "extra time", "et", "aet", "доп")
_FIRST_HALF_WORDS = ("1h", "first half", "1st half", "первый тайм")
_SECOND_HALF_WORDS = ("2h", "second half", "2nd half", "второй тайм")
_BASKETBALL_WORDS = ("basketball", "basket")
_FOOTBALL_WORDS = ("football", "soccer")
_HOCKEY_WORDS = ("hockey", "ice-hockey", "ice_hockey")
_TENNIS_WORDS = ("tennis",)


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


def _sport_code(match) -> str:
    direct = str(getattr(match, "sport_code", "") or "").strip().lower()
    if direct:
        return direct
    sport = getattr(match, "sport", None)
    return str(getattr(sport, "code", "") or "football").strip().lower()


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


def _period_number(*values: str, max_period: int | None = None) -> int | None:
    for value in values:
        text = str(value or "").strip().lower()
        if not text:
            continue
        match = _PERIOD_RE.search(text)
        if not match:
            continue
        number = int(match.group(1))
        if max_period is None or number <= max_period:
            return number
    return None


def _ordinal(number: int, feminine: bool = False) -> str:
    suffix = "я" if feminine else "й"
    return f"{number}-{suffix}"


def _non_football_live_status(match, sport_code: str, phase_text: str) -> str:
    raw_label = str(getattr(match, "live_minute_label", "") or "").strip()
    minute_value = _minute_value(match)
    minute_label = _minute_label(match)

    if any(word in phase_text for word in _EXTRA_WORDS) or raw_label.upper() in {"OT", "ОТ"}:
        period = "Овертайм"
    elif any(word in sport_code for word in _TENNIS_WORDS):
        number = _period_number(phase_text, raw_label, max_period=5)
        period = f"{_ordinal(number)} сет" if number else "LIVE"
    elif any(word in sport_code for word in _BASKETBALL_WORDS):
        number = _period_number(phase_text, raw_label, max_period=4)
        if number is None and minute_value is not None:
            number = min(max(((minute_value - 1) // 12) + 1, 1), 4)
        period = f"{_ordinal(number, feminine=True)} четверть" if number else "LIVE"
    elif any(word in sport_code for word in _HOCKEY_WORDS):
        number = _period_number(phase_text, raw_label, max_period=3)
        if number is None and minute_value is not None:
            number = min(max(((minute_value - 1) // 20) + 1, 1), 3)
        period = f"{_ordinal(number)} период" if number else "LIVE"
    else:
        period = "LIVE"

    if not minute_label or period == minute_label.replace("′", ""):
        return period
    if period == "LIVE":
        return f"LIVE - {minute_label}"
    if minute_value is not None and minute_value <= 5 and raw_label.isdigit():
        return period
    return f"{period} - {minute_label}"


@register.filter
def live_status_label(match) -> str:
    """Human-friendly LIVE phase used on match cards and match detail."""
    if not match:
        return "LIVE"

    minute_value = _minute_value(match)
    minute_label = _minute_label(match)
    phase_text = _phase_text(match)
    sport_code = _sport_code(match)

    if any(word in phase_text for word in _HALFTIME_WORDS):
        return "Перерыв"

    if not any(word in sport_code for word in _FOOTBALL_WORDS):
        return _non_football_live_status(match, sport_code, phase_text)

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


@register.filter
def match_score_or_start_label(match) -> str:
    from game.services.match_time_display import format_match_score_or_start_label

    return format_match_score_or_start_label(match)


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
    if not match:
        return False

    precomputed = getattr(match, "_watched_for_request", None)
    if precomputed is not None:
        return bool(precomputed)

    if not user or not getattr(user, "is_authenticated", False):
        return False

    from notifications.models import MatchWatch

    return MatchWatch.objects.filter(user=user, match=match).exists()

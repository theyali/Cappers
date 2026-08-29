from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from django import template
from django.core.exceptions import ObjectDoesNotExist


register = template.Library()

_LINE_RE = re.compile(r"(?<![\d.])[+-]?\d+(?:[.,]\d+)?")


def _display_odd(value: Any) -> str | None:
    try:
        odd = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if odd <= 0:
        return None
    return f"{odd.quantize(Decimal('0.01'))}"


def _flatten_market(payload: Any, prefix: str = ""):
    if not isinstance(payload, dict):
        return
    for raw_key, raw_value in payload.items():
        key = str(raw_key).strip()
        label = f"{prefix} {key}".strip()
        if isinstance(raw_value, dict):
            yield from _flatten_market(raw_value, label)
            continue
        odd = _display_odd(raw_value)
        if odd is not None:
            yield label, odd


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").split())


def _line_matches(text: str, line: str) -> bool:
    try:
        target = Decimal(str(line).replace(",", "."))
    except InvalidOperation:
        return False
    for raw_value in _LINE_RE.findall(text):
        try:
            if Decimal(raw_value.replace(",", ".")) == target:
                return True
        except InvalidOperation:
            continue
    return False


def _total_side_matches(text: str, side: str) -> bool:
    normalized = _normalized(text)
    if side == "over":
        return any(marker in normalized for marker in ("over", "больше", "тб"))
    return any(marker in normalized for marker in ("under", "меньше", "тм"))


def _handicap_side_matches(text: str, side: str, match) -> bool:
    normalized = _normalized(text)
    home_name = _normalized(getattr(match, "home_team_name", ""))
    away_name = _normalized(getattr(match, "away_team_name", ""))

    if side == "home":
        if home_name and home_name in normalized:
            return True
        if any(marker in normalized for marker in ("home", "team1", "team 1", "p1", "п1", "хозя")):
            return True
        return bool(re.search(r"(?:^|\s)1(?:\s|$)", normalized))

    if away_name and away_name in normalized:
        return True
    if any(marker in normalized for marker in ("away", "team2", "team 2", "p2", "п2", "гост")):
        return True
    return bool(re.search(r"(?:^|\s)2(?:\s|$)", normalized))


def _total_odd(odds, side: str, line: str) -> str | None:
    if odds is None:
        return None

    if line == "2.5":
        direct_field = "goals_over_2_5" if side == "over" else "goals_under_2_5"
        direct = _display_odd(getattr(odds, direct_field, None))
        if direct is not None:
            return direct

    payload = getattr(odds, "totals_all", {})
    for label, odd in _flatten_market(payload):
        if _total_side_matches(label, side) and _line_matches(label, line):
            return odd
    return None


def _handicap_odd(odds, side: str, line: str, match) -> str | None:
    if odds is None:
        return None

    try:
        is_zero = Decimal(str(line).replace(",", ".")) == 0
    except InvalidOperation:
        is_zero = False

    if is_zero:
        direct_field = "fora_1_0" if side == "home" else "fora_2_0"
        direct = _display_odd(getattr(odds, direct_field, None))
        if direct is not None:
            return direct

    payload = getattr(odds, "handicaps_all", {})
    for label, odd in _flatten_market(payload):
        if _handicap_side_matches(label, side, match) and _line_matches(label, line):
            return odd
    return None


def _winner_option(match, odds, side: str, label: str) -> dict[str, Any]:
    field = {
        "home": "home_win_bet",
        "draw": "x_bet",
        "away": "away_win_bet",
    }[side]
    selection = {
        "home": getattr(match, "home_team_name", "") or "Хозяева",
        "draw": "Ничья",
        "away": getattr(match, "away_team_name", "") or "Гости",
    }[side]
    return {
        "key": f"winner-{side}",
        "label": label,
        "market": "winner",
        "selection": selection,
        "coefficient": _display_odd(getattr(odds, field, None)) if odds else None,
    }


def _total_option(odds, side: str, line: str) -> dict[str, Any]:
    is_over = side == "over"
    label = f"{'ТБ' if is_over else 'ТМ'} {line}"
    return {
        "key": f"total-{side}-{line.replace('.', '-')}",
        "label": label,
        "market": "total",
        "selection": label,
        "coefficient": _total_odd(odds, side, line),
    }


def _handicap_option(match, odds, side: str, line: str) -> dict[str, Any]:
    label = f"{'Ф1' if side == 'home' else 'Ф2'} {line}"
    return {
        "key": f"handicap-{side}-{line.replace('+', 'plus-').replace('-', 'minus-').replace('.', '-')}",
        "label": label,
        "market": "handicap",
        "selection": label,
        "coefficient": _handicap_odd(odds, side, line, match),
    }


def _btts_yes_option(odds) -> dict[str, Any]:
    return {
        "key": "btts-yes",
        "label": "ОЗ Да",
        "market": "both_score",
        "selection": "Обе забьют: да",
        "coefficient": _display_odd(getattr(odds, "btts_yes", None)) if odds else None,
    }


def _match_odds(match):
    try:
        return match.odds
    except (ObjectDoesNotExist, AttributeError):
        return None


def build_match_coupon_options(match) -> dict[str, Any]:
    odds = _match_odds(match)
    sport_code = str(getattr(match, "sport_code", "football") or "football").lower()

    if sport_code == "hockey":
        items = [
            _winner_option(match, odds, "home", "П1"),
            _winner_option(match, odds, "draw", "X"),
            _winner_option(match, odds, "away", "П2"),
            _total_option(odds, "over", "5.5"),
            _total_option(odds, "under", "5.5"),
            _handicap_option(match, odds, "home", "0"),
        ]
    elif sport_code == "basketball":
        items = [
            _winner_option(match, odds, "home", "П1"),
            _winner_option(match, odds, "away", "П2"),
            _total_option(odds, "over", "160.5"),
            _total_option(odds, "under", "160.5"),
            _handicap_option(match, odds, "home", "-3.5"),
            _handicap_option(match, odds, "away", "+3.5"),
        ]
    elif sport_code == "tennis":
        items = [
            _winner_option(match, odds, "home", "П1"),
            _winner_option(match, odds, "away", "П2"),
            _total_option(odds, "over", "22.5"),
            _total_option(odds, "under", "22.5"),
            _handicap_option(match, odds, "home", "-1.5"),
            _handicap_option(match, odds, "away", "+1.5"),
        ]
    else:
        items = [
            _winner_option(match, odds, "home", "1"),
            _winner_option(match, odds, "draw", "X"),
            _winner_option(match, odds, "away", "2"),
            _total_option(odds, "over", "2.5"),
            _total_option(odds, "under", "2.5"),
            _btts_yes_option(odds),
        ]

    return {
        "items": items,
        "has_any": any(item["coefficient"] is not None for item in items),
    }


@register.simple_tag
def match_coupon_options(match):
    return build_match_coupon_options(match)

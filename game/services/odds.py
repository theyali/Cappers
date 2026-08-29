from __future__ import annotations

import re
from typing import Any


DIRECT_ODDS_KEYS = {
    "home_win_bet",
    "x_bet",
    "away_win_bet",
    "goals_over_2_5",
    "goals_under_2_5",
    "fora_1_0",
    "fora_2_0",
    "btts_yes",
    "btts_no",
    "d_1x",
    "d_2x",
    "first_time_home_win_bet",
    "first_time_x_bet",
    "first_time_away_win_bet",
}

GROUP_ALIASES = {
    "totals_all": ("totals_all", "totals", "total_goals", "goals_totals"),
    "double_chance_all": ("double_chance_all", "double_chance", "double_chances"),
    "handicaps_all": ("handicaps_all", "handicaps", "fora_all", "spreads"),
    "btts_all": ("btts_all", "both_teams_to_score", "both_score"),
    "team_totals_all": ("team_totals_all", "team_totals", "individual_totals"),
    "first_half_totals_all": ("first_half_totals_all", "first_half_totals"),
    "first_half_handicaps_all": ("first_half_handicaps_all", "first_half_handicaps"),
    "half_time_full_time_all": ("half_time_full_time_all", "ht_ft", "halftime_fulltime"),
    "exact_score_all": ("exact_score_all", "correct_score", "exact_score"),
}

BOOKMAKER_KEYS = ("bookmakers", "bookmaker", "bookmaker_list", "bookmakers_list", "bk", "bks")
MARKET_KEYS = ("bets", "markets", "market", "odds", "events")
VALUE_KEYS = ("values", "outcomes", "selections", "items", "odds")
LINE_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def match_odds_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}

    defaults = _empty_defaults(payload)
    _apply_legacy_payload(defaults, payload)

    for bookmaker in _extract_bookmakers(payload):
        normalized = _normalize_bookmaker(bookmaker)
        _merge_normalized(defaults, normalized)

    return defaults


def has_odds_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    if _has_legacy_payload(payload):
        return True
    return any(
        _normalized_values(market)
        for bookmaker in _extract_bookmakers(payload)
        for market in _market_items(bookmaker)
    )


def _empty_defaults(raw_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "home_win_bet": None,
        "x_bet": None,
        "away_win_bet": None,
        "goals_over_2_5": None,
        "goals_under_2_5": None,
        "fora_1_0": None,
        "fora_2_0": None,
        "btts_yes": None,
        "btts_no": None,
        "d_1x": None,
        "d_2x": None,
        "first_time_home_win_bet": None,
        "first_time_x_bet": None,
        "first_time_away_win_bet": None,
        "totals_all": {},
        "double_chance_all": {},
        "handicaps_all": {},
        "btts_all": {},
        "team_totals_all": {},
        "first_half_totals_all": {},
        "first_half_handicaps_all": {},
        "half_time_full_time_all": {},
        "exact_score_all": {},
        "extra_markets": {},
        "raw_data": raw_data,
    }


def _apply_legacy_payload(defaults: dict[str, Any], payload: dict[str, Any]) -> None:
    for key in DIRECT_ODDS_KEYS:
        defaults[key] = _to_float(payload.get(key))

    used_keys = set(DIRECT_ODDS_KEYS) | set(BOOKMAKER_KEYS)
    for field, aliases in GROUP_ALIASES.items():
        _apply_legacy_group(defaults, field, _first_dict(payload, aliases))
        used_keys.update(aliases)

    defaults["extra_markets"] = {
        key: value
        for key, value in payload.items()
        if key not in used_keys and isinstance(value, dict) and value
    }


def _has_legacy_payload(payload: dict[str, Any]) -> bool:
    for key in DIRECT_ODDS_KEYS:
        if _to_float(payload.get(key)) is not None:
            return True
    for aliases in GROUP_ALIASES.values():
        if _first_dict(payload, aliases):
            return True
    return any(
        key not in DIRECT_ODDS_KEYS
        and all(key not in aliases for aliases in GROUP_ALIASES.values())
        and key not in BOOKMAKER_KEYS
        and isinstance(value, dict)
        and bool(value)
        for key, value in payload.items()
    )


def _apply_legacy_group(defaults: dict[str, Any], field: str, value: dict) -> None:
    if not value:
        return

    if field in {"totals_all", "first_half_totals_all"}:
        _apply_total_container(defaults, value, field)
    elif field in {"handicaps_all", "first_half_handicaps_all"}:
        _apply_handicap_container(defaults, value, field)
    elif field == "team_totals_all":
        _apply_team_total_container(defaults, value)
    else:
        defaults[field] = _flat_odds_dict(value)


def _apply_total_container(defaults: dict[str, Any], value: dict, field: str) -> None:
    for key, item in value.items():
        text = _normalize_text(key)
        if isinstance(item, dict) and text in {"total", "totals"}:
            _apply_line_totals(defaults, item, field)
        elif isinstance(item, dict) and text in {"ah", "asian handicap", "handicap", "handicaps"}:
            _apply_handicap_container(defaults, item, "handicaps_all")
        elif isinstance(item, dict) and _is_team_total(text):
            _put_group(defaults["team_totals_all"], key, _line_totals_to_dict(item))
        elif _to_float(item) is not None:
            defaults[field][key] = _to_float(item)


def _apply_handicap_container(defaults: dict[str, Any], value: dict, field: str) -> None:
    if field == "handicaps_all":
        target = defaults["handicaps_all"]
        direct_defaults = defaults
    else:
        target = defaults["first_half_handicaps_all"]
        direct_defaults = None

    for key, item in value.items():
        if isinstance(item, dict) and _is_line_pair(item, ("home", "away")):
            line = _normalize_line(item.get("line") or key)
            home_odd = _to_float(item.get("home"))
            away_odd = _to_float(item.get("away"))
            if home_odd is not None:
                target[f"Home {line}"] = home_odd
                if direct_defaults is not None and line in {"0", "+0", "-0"}:
                    direct_defaults["fora_1_0"] = home_odd
            if away_odd is not None:
                away_line = _opposite_line(line)
                target[f"Away {away_line}"] = away_odd
                if direct_defaults is not None and line in {"0", "+0", "-0"}:
                    direct_defaults["fora_2_0"] = away_odd
        elif _to_float(item) is not None:
            target[key] = _to_float(item)


def _apply_team_total_container(defaults: dict[str, Any], value: dict) -> None:
    for key, item in value.items():
        if isinstance(item, dict):
            odds = _line_totals_to_dict(item)
            if odds:
                _put_group(defaults["team_totals_all"], key, odds)
        elif _to_float(item) is not None:
            defaults["team_totals_all"][key] = _to_float(item)


def _apply_line_totals(defaults: dict[str, Any], line_map: dict, field: str) -> None:
    for label, odd in _line_totals_to_dict(line_map).items():
        defaults[field][label] = odd
        line = _line_from_text(label)
        side = _total_side(label)
        if field == "totals_all" and line == "2.5":
            if side == "Over":
                defaults["goals_over_2_5"] = odd
            elif side == "Under":
                defaults["goals_under_2_5"] = odd


def _line_totals_to_dict(line_map: dict) -> dict[str, float]:
    values: dict[str, float] = {}
    for key, item in line_map.items():
        if not isinstance(item, dict) or not _is_line_pair(item, ("over", "under")):
            continue
        line = _normalize_line(item.get("line") or key)
        over_odd = _to_float(item.get("over"))
        under_odd = _to_float(item.get("under"))
        if over_odd is not None:
            values[f"Over {line}"] = over_odd
        if under_odd is not None:
            values[f"Under {line}"] = under_odd
    return values


def _flat_odds_dict(value: dict) -> dict:
    return {
        key: _to_float(item) if _to_float(item) is not None else item
        for key, item in value.items()
        if item not in (None, "")
    }


def _is_line_pair(value: dict, sides: tuple[str, str]) -> bool:
    return any(_to_float(value.get(side)) is not None for side in sides)


def _merge_normalized(defaults: dict[str, Any], normalized: dict[str, Any]) -> None:
    for key in DIRECT_ODDS_KEYS:
        if normalized.get(key) is not None:
            defaults[key] = normalized[key]
    for key in GROUP_ALIASES:
        if normalized.get(key):
            defaults[key] = {**defaults.get(key, {}), **normalized[key]}
    if normalized.get("extra_markets"):
        defaults["extra_markets"] = {
            **defaults.get("extra_markets", {}),
            **normalized["extra_markets"],
        }


def _extract_bookmakers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    explicit_bookmakers: list[dict[str, Any]] = []
    for key in BOOKMAKER_KEYS:
        value = payload.get(key)
        bookmakers = _bookmaker_list(value)
        if bookmakers:
            explicit_bookmakers.extend(bookmakers)
    if explicit_bookmakers:
        return explicit_bookmakers

    nested = payload.get("data")
    if isinstance(nested, dict):
        bookmakers = _extract_bookmakers(nested)
        if bookmakers:
            return bookmakers

    found: list[dict[str, Any]] = []
    _collect_nested_bookmakers(payload, found)
    if found:
        return found

    if any(key in payload for key in MARKET_KEYS):
        return [payload]
    return []


def _collect_nested_bookmakers(value: Any, found: list[dict[str, Any]]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_nested_bookmakers(item, found)
        return

    if not isinstance(value, dict):
        return

    if any(key in value for key in MARKET_KEYS) and _market_items(value):
        found.append(value)
        return

    for item in value.values():
        _collect_nested_bookmakers(item, found)


def _bookmaker_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        if any(key in value for key in MARKET_KEYS):
            return [value]
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _normalize_bookmaker(bookmaker: dict[str, Any]) -> dict[str, Any]:
    defaults = _empty_defaults({})
    for market in _market_items(bookmaker):
        market_name = _market_name(market)
        values = _normalized_values(market)
        if not values:
            continue
        _apply_market(defaults, market_name, values)
    return defaults


def _market_items(bookmaker: dict[str, Any]) -> list[dict[str, Any]]:
    for key in MARKET_KEYS:
        value = bookmaker.get(key)
        markets = _market_list(value)
        if markets:
            return markets
    return []


def _market_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        markets = []
        for key, item in value.items():
            if isinstance(item, dict):
                markets.append({"name": key, **item} if "name" not in item else item)
            elif isinstance(item, list):
                markets.append({"name": key, "values": item})
        return markets
    return []


def _market_name(market: dict[str, Any]) -> str:
    return str(
        market.get("name")
        or market.get("label")
        or market.get("key")
        or market.get("type")
        or market.get("id")
        or "Market"
    )


def _market_values(market: dict[str, Any]) -> list[Any]:
    for key in VALUE_KEYS:
        value = market.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [
                {"value": item_key, **item_value}
                if isinstance(item_value, dict)
                else {"value": item_key, "odd": item_value}
                for item_key, item_value in value.items()
            ]
    if _to_float(_odd_value(market)) is not None:
        return [market]
    return []


def _normalized_values(market: dict[str, Any]) -> dict[str, float]:
    values = {}
    market_text = _normalize_text(_market_name(market))
    for item in _market_values(market):
        label = _value_label(item)
        odd = _to_float(_odd_value(item))
        if not label or odd is None:
            continue
        line = _line_value(item)
        if line and line not in label and (line != "0" or _is_handicap(market_text)):
            label = f"{label} {line}".strip()
        values[label] = odd
    return values


def _value_label(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item or "")
    return str(
        item.get("value")
        or item.get("name")
        or item.get("label")
        or item.get("outcome")
        or item.get("selection")
        or item.get("side")
        or item.get("type")
        or ""
    )


def _odd_value(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    for key in ("odd", "odds", "price", "coefficient", "coef", "koef"):
        if key in item:
            return item.get(key)
    return None


def _line_value(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("line", "handicap", "total", "points"):
        value = item.get(key)
        if value not in (None, ""):
            return _normalize_line(value)
    return ""


def _apply_market(defaults: dict[str, Any], market_name: str, values: dict[str, float]) -> None:
    normalized = _normalize_text(market_name)
    if _is_first_half_winner(normalized):
        _apply_winner(defaults, values, prefix="first_time_")
    elif _is_match_winner(normalized):
        _apply_winner(defaults, values)
    elif _is_double_chance(normalized):
        _apply_double_chance(defaults, values)
    elif _is_first_half_total(normalized):
        _apply_totals(defaults, values, "first_half_totals_all")
    elif _is_team_total(normalized):
        _put_group(defaults["team_totals_all"], market_name, values)
    elif _is_total(normalized):
        _apply_totals(defaults, values, "totals_all")
    elif _is_first_half_handicap(normalized):
        _put_group(defaults["first_half_handicaps_all"], market_name, values)
    elif _is_handicap(normalized):
        _apply_handicaps(defaults, values)
    elif _is_btts(normalized):
        _apply_btts(defaults, values)
    elif _is_ht_ft(normalized):
        _put_group(defaults["half_time_full_time_all"], market_name, values)
    elif _is_exact_score(normalized):
        _put_group(defaults["exact_score_all"], market_name, values)
    else:
        _put_group(defaults["extra_markets"], market_name, values)


def _apply_winner(defaults: dict[str, Any], values: dict[str, float], *, prefix: str = "") -> None:
    field_map = {
        "home": f"{prefix}home_win_bet",
        "draw": f"{prefix}x_bet",
        "away": f"{prefix}away_win_bet",
    }
    for label, odd in values.items():
        side = _winner_side(label)
        if side in field_map:
            defaults[field_map[side]] = odd


def _apply_double_chance(defaults: dict[str, Any], values: dict[str, float]) -> None:
    for label, odd in values.items():
        key = _double_chance_key(label)
        if not key:
            defaults["double_chance_all"][label] = odd
            continue
        defaults["double_chance_all"][key.upper()] = odd
        if key == "1x":
            defaults["d_1x"] = odd
        elif key == "x2":
            defaults["d_2x"] = odd


def _apply_totals(defaults: dict[str, Any], values: dict[str, float], field: str) -> None:
    for label, odd in values.items():
        side = _total_side(label)
        line = _line_from_text(label)
        key = f"{side} {line}".strip() if side else label
        defaults[field][key] = odd
        if field == "totals_all" and line == "2.5":
            if side == "Over":
                defaults["goals_over_2_5"] = odd
            elif side == "Under":
                defaults["goals_under_2_5"] = odd


def _apply_handicaps(defaults: dict[str, Any], values: dict[str, float]) -> None:
    for label, odd in values.items():
        defaults["handicaps_all"][label] = odd
        side = _winner_side(label)
        line = _line_from_text(label)
        if line in {"0", "+0", "-0"}:
            if side == "home":
                defaults["fora_1_0"] = odd
            elif side == "away":
                defaults["fora_2_0"] = odd


def _apply_btts(defaults: dict[str, Any], values: dict[str, float]) -> None:
    for label, odd in values.items():
        key = "Yes" if _is_yes(label) else "No" if _is_no(label) else label
        defaults["btts_all"][key] = odd
        if key == "Yes":
            defaults["btts_yes"] = odd
        elif key == "No":
            defaults["btts_no"] = odd


def _put_group(group: dict[str, Any], key: str, values: dict[str, float]) -> None:
    key = str(key or "Market")
    if key in group and isinstance(group[key], dict):
        group[key] = {**group[key], **values}
    elif key in group:
        group[f"{key} #2"] = values
    else:
        group[key] = values


def _winner_side(label: str) -> str | None:
    text = _normalize_text(label)
    compact = text.replace(" ", "")
    if compact in {"1", "home", "team1", "hometeam", "hosts", "p1", "п1"} or text.startswith("home"):
        return "home"
    if compact in {"x", "draw", "tie", "nichya"} or "draw" in text or "нич" in text:
        return "draw"
    if compact in {"2", "away", "team2", "awayteam", "guests", "p2", "п2"} or text.startswith("away"):
        return "away"
    if "хозя" in text:
        return "home"
    if "гост" in text:
        return "away"
    return None


def _double_chance_key(label: str) -> str | None:
    compact = _normalize_text(label).replace(" ", "").replace("/", "").replace("х", "x")
    aliases = {
        "1x": "1x",
        "x1": "1x",
        "homedraw": "1x",
        "drawhome": "1x",
        "12": "12",
        "homeaway": "12",
        "awayhome": "12",
        "x2": "x2",
        "2x": "x2",
        "drawaway": "x2",
        "awaydraw": "x2",
    }
    return aliases.get(compact)


def _is_match_winner(text: str) -> bool:
    return not _is_half(text) and any(
        token in text
        for token in (
            "1x2",
            "3way",
            "3 way",
            "winner",
            "moneyline",
            "match result",
            "match betting",
            "full time result",
            "home/away",
            "побед",
            "исход",
        )
    )


def _is_first_half_winner(text: str) -> bool:
    return _is_half(text) and any(token in text for token in ("1x2", "winner", "result", "исход"))


def _is_double_chance(text: str) -> bool:
    return "double chance" in text or "двой" in text or _double_chance_key(text) is not None


def _is_total(text: str) -> bool:
    return "total" in text or "over/under" in text or "тотал" in text


def _is_first_half_total(text: str) -> bool:
    return _is_half(text) and _is_total(text)


def _is_team_total(text: str) -> bool:
    return _is_total(text) and any(token in text for token in ("team", "individual", "команд", "индивидуал"))


def _is_handicap(text: str) -> bool:
    return "handicap" in text or "spread" in text or "puck line" in text or "фора" in text


def _is_first_half_handicap(text: str) -> bool:
    return _is_half(text) and _is_handicap(text)


def _is_btts(text: str) -> bool:
    return "btts" in text or "both teams" in text or "обе" in text


def _is_ht_ft(text: str) -> bool:
    return "half time/full time" in text or "halftime/fulltime" in text or "ht/ft" in text or "тайм/матч" in text


def _is_exact_score(text: str) -> bool:
    return "correct score" in text or "exact score" in text or "точный счет" in text


def _is_half(text: str) -> bool:
    return "half" in text or "1st" in text or "first" in text or "тайм" in text or "полов" in text


def _total_side(label: str) -> str:
    text = _normalize_text(label)
    if "over" in text or "больше" in text or "тб" in text:
        return "Over"
    if "under" in text or "меньше" in text or "тм" in text:
        return "Under"
    return ""


def _line_from_text(label: str) -> str:
    match = LINE_RE.search(str(label))
    return _normalize_line(match.group(0)) if match else ""


def _normalize_line(value: Any) -> str:
    text = str(value).strip().replace(",", ".")
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    return str(int(number)) if number.is_integer() else str(number).rstrip("0").rstrip(".")


def _opposite_line(value: str) -> str:
    try:
        number = -float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return value
    if number == 0:
        return "0"
    normalized = _normalize_line(number)
    return normalized if normalized.startswith("-") else f"+{normalized}"


def _is_yes(label: str) -> bool:
    text = _normalize_text(label)
    return text in {"yes", "y", "да"} or "yes" in text


def _is_no(label: str) -> bool:
    text = _normalize_text(label)
    return text in {"no", "n", "нет"} or "no" in text


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("-", " ").replace("ё", "е")


def _first_dict(payload: dict[str, Any], aliases: tuple[str, ...]) -> dict:
    for alias in aliases:
        value = payload.get(alias)
        if isinstance(value, dict):
            return value
    return {}


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

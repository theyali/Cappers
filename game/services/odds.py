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


def match_odds_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}

    defaults = {
        "home_win_bet": _to_float(payload.get("home_win_bet")),
        "x_bet": _to_float(payload.get("x_bet")),
        "away_win_bet": _to_float(payload.get("away_win_bet")),
        "goals_over_2_5": _to_float(payload.get("goals_over_2_5")),
        "goals_under_2_5": _to_float(payload.get("goals_under_2_5")),
        "fora_1_0": _to_float(payload.get("fora_1_0")),
        "fora_2_0": _to_float(payload.get("fora_2_0")),
        "btts_yes": _to_float(payload.get("btts_yes")),
        "btts_no": _to_float(payload.get("btts_no")),
        "d_1x": _to_float(payload.get("d_1x")),
        "d_2x": _to_float(payload.get("d_2x")),
        "first_time_home_win_bet": _to_float(payload.get("first_time_home_win_bet")),
        "first_time_x_bet": _to_float(payload.get("first_time_x_bet")),
        "first_time_away_win_bet": _to_float(payload.get("first_time_away_win_bet")),
        "raw_data": payload,
    }

    used_keys = set(DIRECT_ODDS_KEYS)
    for field, aliases in GROUP_ALIASES.items():
        defaults[field] = _first_dict(payload, aliases)
        used_keys.update(aliases)

    defaults["extra_markets"] = {
        key: value
        for key, value in payload.items()
        if key not in used_keys and isinstance(value, (dict, list))
    }
    return defaults


def has_odds_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False

    for key in DIRECT_ODDS_KEYS:
        if _to_float(payload.get(key)) is not None:
            return True

    for aliases in GROUP_ALIASES.values():
        if _first_dict(payload, aliases):
            return True

    return any(
        key not in DIRECT_ODDS_KEYS
        and all(key not in aliases for aliases in GROUP_ALIASES.values())
        and isinstance(value, (dict, list))
        and bool(value)
        for key, value in payload.items()
    )


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

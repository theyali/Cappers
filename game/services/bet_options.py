"""Bettable match outcomes built from the stored provider line (MatchOdds).

The same builders feed the odds buttons on match pages and the server-side
coupon validation, so a coupon can only contain an outcome the site actually
offers, at the coefficient currently stored in MatchOdds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ObjectDoesNotExist

from game.models import Prediction, PredictionCoupon
from game.services.odds import format_outcome_line, outcome_code_from_label


# Markets the settlement engine can resolve automatically. Other markets are
# still shown on the match page, but cannot be added to a coupon. A coupon
# position also needs a structured outcome code (see outcome_code_from_label),
# so settlement never has to guess the side from team names.
SETTLEABLE_MARKETS = frozenset(
    {
        "winner",
        "double_chance",
        "total",
        "both_score",
        "handicap",
        "exact_score",
        "first_half_winner",
        "first_half_total",
        "first_half_handicap",
    }
)
MARKET_MAX_LENGTH = 80
SELECTION_MAX_LENGTH = 120

_LINE_RE = re.compile(r"(?<![\d.])[+-]?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class BetOption:
    market: str
    selection: str
    coefficient: Decimal
    outcome_code: str


def is_outcome_bettable(match, market: str, outcome_code: str) -> bool:
    if market not in SETTLEABLE_MARKETS or not outcome_code:
        return False
    sport_code = str(getattr(match, "sport_code", "football") or "football").lower()
    if sport_code == "basketball" and (outcome_code == "X" or market == "double_chance"):
        # Regular-time scores are not available for basketball, so outcomes that
        # depend on a regular-time draw cannot be settled.
        return False
    return True


def optional_odd(value: Any) -> str | None:
    try:
        odd = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not odd.is_finite() or odd <= 0:
        return None
    return f"{odd.quantize(Decimal('0.01'))}"


def bet_option_key(market: Any, selection: Any) -> tuple[str, str]:
    """Normalize a (market, selection) pair the same way for offers and coupons."""
    market_text = str(market or "").strip()[:MARKET_MAX_LENGTH]
    selection_text = str(selection or "").strip()[:SELECTION_MAX_LENGTH]
    return market_text, " ".join(selection_text.casefold().split())


def match_bet_options(match, odds=None) -> dict[tuple[str, str], BetOption]:
    """Return every outcome that can be added to a coupon, keyed by ``bet_option_key``.

    ``odds`` lets callers pass a freshly loaded MatchOdds row; otherwise the
    match relation is used.
    """
    odds = odds if odds is not None else _match_odds(match)
    if not _match_odds_has_values(odds):
        return {}

    options: dict[tuple[str, str], BetOption] = {}

    def add(market: str, selection: str, coefficient: str | None, outcome_code: str, bettable: bool = True) -> None:
        if not bettable or coefficient is None or not is_outcome_bettable(match, market, outcome_code):
            return
        key = bet_option_key(market, selection)
        options.setdefault(
            key,
            BetOption(key[0], selection[:SELECTION_MAX_LENGTH], Decimal(coefficient), outcome_code),
        )

    for item in build_match_coupon_options(match, odds=odds)["items"]:
        add(item["market"], item["selection"], item["coefficient"], item["outcome_code"])

    for tab in build_match_odds_tabs(match, odds=odds):
        for section in tab["sections"]:
            for row in section["rows"]:
                for button in row["odds"]:
                    add(
                        button["market"],
                        button["selection"],
                        button["coefficient"],
                        button["outcome_code"],
                        button["bettable"],
                    )

    return options


def _match_odds(match):
    try:
        return match.odds
    except (ObjectDoesNotExist, AttributeError):
        return None


# Quick coupon options (match cards and tables).


def _flatten_market(payload: Any, prefix: str = ""):
    if not isinstance(payload, dict):
        return
    for raw_key, raw_value in payload.items():
        key = str(raw_key).strip()
        label = f"{prefix} {key}".strip()
        if isinstance(raw_value, dict):
            yield from _flatten_market(raw_value, label)
            continue
        odd = optional_odd(raw_value)
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
        direct = optional_odd(getattr(odds, direct_field, None))
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
        direct = optional_odd(getattr(odds, direct_field, None))
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
        "outcome_code": {"home": "1", "draw": "X", "away": "2"}[side],
        "coefficient": optional_odd(getattr(odds, field, None)) if odds else None,
    }


def _total_option(odds, side: str, line: str) -> dict[str, Any]:
    is_over = side == "over"
    label = f"{'ТБ' if is_over else 'ТМ'} {line}"
    return {
        "key": f"total-{side}-{line.replace('.', '-')}",
        "label": label,
        "market": "total",
        "selection": label,
        "outcome_code": f"{side} {format_outcome_line(line)}",
        "coefficient": _total_odd(odds, side, line),
    }


def _handicap_option(match, odds, side: str, line: str) -> dict[str, Any]:
    label = f"{'Ф1' if side == 'home' else 'Ф2'} {line}"
    return {
        "key": f"handicap-{side}-{line.replace('+', 'plus-').replace('-', 'minus-').replace('.', '-')}",
        "label": label,
        "market": "handicap",
        "selection": label,
        "outcome_code": f"{side} {format_outcome_line(line, signed=True)}",
        "coefficient": _handicap_odd(odds, side, line, match),
    }


def _btts_yes_option(odds) -> dict[str, Any]:
    return {
        "key": "btts-yes",
        "label": "ОЗ Да",
        "market": "both_score",
        "selection": "Обе забьют: да",
        "outcome_code": "yes",
        "coefficient": optional_odd(getattr(odds, "btts_yes", None)) if odds else None,
    }


def build_match_coupon_options(match, odds=None) -> dict[str, Any]:
    odds = odds if odds is not None else _match_odds(match)
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


# Full odds tabs (match page and tournament odds panel).


def build_match_winner_odds(match) -> dict:
    odds = _match_odds(match)
    totals = odds.totals_all if odds and isinstance(odds.totals_all, dict) else {}
    values = {
        "home": optional_odd(odds.home_win_bet if odds else None),
        "draw": optional_odd(odds.x_bet if odds else None),
        "away": optional_odd(odds.away_win_bet if odds else None),
        "over25": optional_odd(
            (odds.goals_over_2_5 or _nested_odd(totals, "Over 2.5"))
            if odds
            else None
        ),
        "under25": optional_odd(
            (odds.goals_under_2_5 or _nested_odd(totals, "Under 2.5"))
            if odds
            else None
        ),
        "btts_yes": optional_odd(odds.btts_yes if odds else None),
    }
    values["has_any"] = any(value is not None for value in values.values())
    return values


def build_match_odds_tabs(match, odds=None) -> list[dict]:
    odds = odds if odds is not None else _match_odds(match)
    if not _match_odds_has_values(odds):
        return _prediction_odds_tabs(match)

    home_name = match.home_team_name or "Хозяева"
    away_name = match.away_team_name or "Гости"

    popular_sections = [
        _odds_section(
            "Исход матча",
            [
                _odds_row(
                    "Основное время",
                    [
                        _odds_button("1", home_name, "winner", home_name, optional_odd(odds.home_win_bet), outcome_code="1"),
                        _odds_button("X", "Ничья", "winner", "Ничья", optional_odd(odds.x_bet), outcome_code="X"),
                        _odds_button("2", away_name, "winner", away_name, optional_odd(odds.away_win_bet), outcome_code="2"),
                    ],
                ),
                _odds_row(
                    "Двойной шанс",
                    [
                        _odds_button("1X", f"{home_name} или ничья", "double_chance", f"{home_name} или ничья", optional_odd(odds.d_1x), outcome_code="1X"),
                        _odds_button("X2", f"Ничья или {away_name}", "double_chance", f"Ничья или {away_name}", optional_odd(odds.d_2x), outcome_code="X2"),
                    ],
                ),
                *_generic_market_rows(odds.double_chance_all, "double_chance", "Двойной шанс"),
            ],
        ),
        _odds_section(
            "Тоталы",
            [
                _odds_row(
                    "Тотал голов 2.5",
                    [
                        _odds_button("ТБ 2.5", "Больше 2.5", "total", "ТБ 2.5", optional_odd(odds.goals_over_2_5), outcome_code="over 2.5"),
                        _odds_button("ТМ 2.5", "Меньше 2.5", "total", "ТМ 2.5", optional_odd(odds.goals_under_2_5), outcome_code="under 2.5"),
                    ],
                ),
                *_totals_rows_from_payload(odds.totals_all, skip_lines={"2.5"}),
            ],
        ),
        _odds_section(
            "Обе забьют",
            [
                _odds_row(
                    "Голы обеих команд",
                    [
                        _odds_button("ОЗ Да", "Да", "both_score", "Обе забьют: да", optional_odd(odds.btts_yes), outcome_code="yes"),
                        _odds_button("ОЗ Нет", "Нет", "both_score", "Обе забьют: нет", optional_odd(odds.btts_no), outcome_code="no"),
                    ],
                ),
                *_generic_market_rows(odds.btts_all, "both_score", "Обе забьют"),
            ],
        ),
    ]

    match_sections = [
        popular_sections[0],
        _odds_section(
            "Форы",
            [
                _odds_row(
                    "Фора 0",
                    [
                        _odds_button("Ф1 0", home_name, "handicap", f"{home_name} фора 0", optional_odd(odds.fora_1_0), outcome_code="home 0"),
                        _odds_button("Ф2 0", away_name, "handicap", f"{away_name} фора 0", optional_odd(odds.fora_2_0), outcome_code="away 0"),
                    ],
                ),
                *_generic_market_rows(odds.handicaps_all, "handicap", "Фора"),
            ],
        ),
    ]
    match_sections = [section for section in match_sections if section["rows"]]

    total_sections = [
        popular_sections[1],
        _odds_section("Индивидуальные тоталы", _generic_market_rows(odds.team_totals_all, "team_total", "Индивидуальный тотал")),
    ]

    first_half_section = _odds_section(
        "1-й тайм",
        [
            _odds_row(
                "Исход 1-го тайма",
                [
                    _odds_button("1", home_name, "first_half_winner", f"1-й тайм: {home_name}", optional_odd(odds.first_time_home_win_bet), outcome_code="1"),
                    _odds_button("X", "Ничья", "first_half_winner", "1-й тайм: ничья", optional_odd(odds.first_time_x_bet), outcome_code="X"),
                    _odds_button("2", away_name, "first_half_winner", f"1-й тайм: {away_name}", optional_odd(odds.first_time_away_win_bet), outcome_code="2"),
                ],
            ),
            *_totals_rows_from_payload(odds.first_half_totals_all, market="first_half_total"),
            *_generic_market_rows(odds.first_half_handicaps_all, "first_half_handicap", "Фора 1-го тайма"),
        ],
    )
    other_sections = [
        _odds_section("Тайм / матч", _generic_market_rows(odds.half_time_full_time_all, "half_time_full_time", "Тайм / матч")),
        _odds_section("Точный счет", _generic_market_rows(odds.exact_score_all, "exact_score", "Точный счет")),
        *_extra_market_sections(odds.extra_markets),
    ]

    tabs = [
        {"key": "popular", "label": "Популярное", "sections": [section for section in popular_sections if section["rows"]]},
        {"key": "match", "label": "Матч", "sections": match_sections},
        {"key": "totals", "label": "Тоталы", "sections": [section for section in total_sections if section["rows"]]},
        {"key": "first_half", "label": "1-й тайм", "sections": [first_half_section] if first_half_section["rows"] else []},
        {"key": "other", "label": "Другие", "sections": [section for section in other_sections if section["rows"]]},
    ]
    tabs = [tab for tab in tabs if tab["sections"]]
    for tab in tabs:
        for section in tab["sections"]:
            for row in section["rows"]:
                for button in row["odds"]:
                    button["bettable"] = button["bettable"] and is_outcome_bettable(
                        match,
                        button["market"],
                        button["outcome_code"],
                    )
    return tabs


def _match_odds_has_values(odds) -> bool:
    if odds is None:
        return False

    direct_fields = (
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
    )
    if any(optional_odd(getattr(odds, field, None)) is not None for field in direct_fields):
        return True

    json_fields = (
        "totals_all",
        "double_chance_all",
        "handicaps_all",
        "btts_all",
        "team_totals_all",
        "first_half_totals_all",
        "first_half_handicaps_all",
        "half_time_full_time_all",
        "exact_score_all",
        "extra_markets",
    )
    return any(bool(getattr(odds, field, None)) for field in json_fields)


def _prediction_odds_tabs(match) -> list[dict]:
    """Show coefficients from published predictions when the line is missing.

    These values come from other coupons, not from the provider, so they are
    informational only and cannot be added to a new coupon.
    """
    predictions = (
        Prediction.objects.filter(
            match=match,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            coupon__audience=PredictionCoupon.Audience.FREE,
        )
        .values("market", "selection", "coefficient")
        .distinct()
        .order_by("market", "selection")
    )

    rows = [
        _odds_row(
            human_market_label(prediction["market"]),
            [
                _odds_button(
                    _short_odd_label(prediction["selection"]),
                    prediction["selection"],
                    prediction["market"],
                    prediction["selection"],
                    optional_odd(prediction["coefficient"]),
                    bettable=False,
                )
            ],
        )
        for prediction in predictions
    ]
    section = _odds_section("Сохраненные коэффициенты", rows)
    if not section["rows"]:
        return []
    return [{"key": "popular", "label": "Популярное", "sections": [section]}]


def _odds_section(title: str, rows: list[dict]) -> dict:
    return {"title": title, "rows": [row for row in rows if row["odds"]]}


def _odds_row(title: str, odds: list[dict | None]) -> dict:
    return {"title": title, "odds": [odd for odd in odds if odd]}


def _odds_button(
    label: str,
    description: str,
    market: str,
    selection: str,
    coefficient: str | None,
    *,
    outcome_code: str = "",
    bettable: bool = True,
) -> dict | None:
    if coefficient is None:
        return None
    return {
        "label": label,
        "description": description,
        "market": market,
        "selection": selection,
        "coefficient": coefficient,
        "key": f"{market}:{selection}",
        "outcome_code": outcome_code,
        "bettable": bettable and market in SETTLEABLE_MARKETS and bool(outcome_code),
    }


def _totals_rows_from_payload(
    totals_all: dict,
    *,
    market: str = "total",
    skip_lines: set[str] | None = None,
) -> list[dict]:
    if not isinstance(totals_all, dict):
        return []
    skip_lines = skip_lines or set()

    rows_by_line: dict[str, dict[str, str | None]] = {}
    for raw_key, raw_value in totals_all.items():
        key = str(raw_key)
        odd = optional_odd(raw_value)
        if odd is None and isinstance(raw_value, dict):
            rows_by_line.update(_nested_total_values(raw_value))
            continue
        if odd is None:
            continue
        lower_key = key.lower()
        if "over" in lower_key or "больше" in lower_key:
            side = "over"
        elif "under" in lower_key or "меньше" in lower_key:
            side = "under"
        else:
            continue
        line = key.replace("Over", "").replace("Under", "").replace("Больше", "").replace("Меньше", "").strip()
        if not line:
            line = "2.5"
        rows_by_line.setdefault(line, {"over": None, "under": None})[side] = odd

    rows = []
    for line, values in sorted(rows_by_line.items(), key=lambda item: _line_sort_key(item[0])):
        if line in skip_lines:
            continue
        code_line = format_outcome_line(line)
        rows.append(
            _odds_row(
                f"Тотал {line}",
                [
                    _odds_button(
                        f"ТБ {line}",
                        f"Больше {line}",
                        market,
                        f"ТБ {line}",
                        values.get("over"),
                        outcome_code=f"over {code_line}" if code_line else "",
                    ),
                    _odds_button(
                        f"ТМ {line}",
                        f"Меньше {line}",
                        market,
                        f"ТМ {line}",
                        values.get("under"),
                        outcome_code=f"under {code_line}" if code_line else "",
                    ),
                ],
            )
        )

    return rows


def _nested_total_values(payload: dict) -> dict[str, dict[str, str | None]]:
    nested_totals = payload.get("total") if isinstance(payload.get("total"), dict) else payload
    if not isinstance(nested_totals, dict):
        return {}

    rows_by_line: dict[str, dict[str, str | None]] = {}
    for raw_line, raw_value in nested_totals.items():
        if not isinstance(raw_value, dict):
            continue
        line = str(raw_value.get("line") or raw_line).replace(",", ".").strip()
        if not line:
            continue
        rows_by_line.setdefault(line, {"over": None, "under": None})["over"] = optional_odd(raw_value.get("over"))
        rows_by_line.setdefault(line, {"over": None, "under": None})["under"] = optional_odd(raw_value.get("under"))
    return rows_by_line


def _generic_market_rows(payload: dict, market: str, title: str) -> list[dict]:
    if not isinstance(payload, dict):
        return []

    grouped_rows: list[dict] = []
    flat_buttons: list[dict] = []
    for raw_key, raw_value in payload.items():
        label = human_market_label(raw_key)
        if isinstance(raw_value, dict):
            row = _odds_row(
                label,
                [
                    _odds_button(
                        _short_odd_label(option_key),
                        human_market_label(option_key),
                        market,
                        f"{label}: {human_market_label(option_key)}",
                        optional_odd(option_value),
                        outcome_code=outcome_code_from_label(market, option_key),
                    )
                    for option_key, option_value in raw_value.items()
                ],
            )
            if row["odds"]:
                grouped_rows.append(row)
        else:
            button = _odds_button(
                _short_odd_label(raw_key),
                label,
                market,
                label,
                optional_odd(raw_value),
                outcome_code=outcome_code_from_label(market, raw_key),
            )
            if button:
                flat_buttons.append(button)

    if flat_buttons:
        grouped_rows.insert(0, _odds_row(title, flat_buttons))
    return grouped_rows


def _extra_market_sections(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    sections = []
    for raw_title, raw_value in payload.items():
        if isinstance(raw_value, dict):
            section = _odds_section(
                human_market_label(raw_title),
                _generic_market_rows(raw_value, f"extra:{raw_title}", human_market_label(raw_title)),
            )
            if section["rows"]:
                sections.append(section)
    return sections


def human_market_label(value) -> str:
    text = str(value or "").strip()
    replacements = {
        "home": "Хозяева",
        "away": "Гости",
        "draw": "Ничья",
        "yes": "Да",
        "no": "Нет",
        "over": "Больше",
        "under": "Меньше",
    }
    lower = text.lower().replace("_", " ")
    # Keep the minus of handicap lines ("Home -1.5") and score dashes ("3-2").
    readable = re.sub(r"-(?!\d)", " ", text.replace("_", " ")).strip()
    return replacements.get(lower, readable or "Ставка")


def _short_odd_label(value) -> str:
    text = human_market_label(value)
    shortcuts = {
        "Хозяева": "1",
        "Ничья": "X",
        "Гости": "2",
        "Да": "Да",
        "Нет": "Нет",
    }
    return shortcuts.get(text, text[:18])


def _line_sort_key(value: str) -> tuple[int, Decimal]:
    try:
        return (0, Decimal(value.replace(",", ".")))
    except (InvalidOperation, ValueError):
        return (1, Decimal("0"))


def _nested_odd(odds: dict, key: str):
    if isinstance(odds, dict):
        return odds.get(key)
    return None

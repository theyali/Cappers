"""Conservative comparison keys for the audited Neurokeff v2 football line.

The provider's broad `key` is not a contract: e.g. corners and player markets
also use `total`. Only explicitly recognized market names enter comparison.
Original markets stay intact so unsupported offers can be mapped later.
"""

import re
from collections import Counter
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from game.models import ComparisonBookmaker
from game.services.match_time_display import format_match_start_label
from game.services.odds import format_outcome_line, outcome_code_from_label


NORMALIZATION_VERSION = 1
DENSE_MARKET_LINE_LIMIT = 3


def _text(value):
    return " ".join(str(value or "").casefold().split())


# Exact aliases verified against full v2 responses, not substring matching.
# Each definition: market, period, subject, settlement, line reference.
FOOTBALL_MARKETS = {
    "match winner": ("winner", "full_time", "match", "regular_time", ""),
    "first half winner": ("winner", "first_half", "match", "regular_time", ""),
    "second half winner": ("winner", "second_half", "match", "regular_time", ""),
    "double chance": ("double_chance", "full_time", "match", "regular_time", ""),
    "double chance - first half": ("double_chance", "first_half", "match", "regular_time", ""),
    "double chance - second half": ("double_chance", "second_half", "match", "regular_time", ""),
    "both teams score": ("both_score", "full_time", "match", "regular_time", ""),
    "both teams to score": ("both_score", "full_time", "match", "regular_time", ""),
    "both teams score - first half": ("both_score", "first_half", "match", "regular_time", ""),
    "both teams to score - second half": ("both_score", "second_half", "match", "regular_time", ""),
    "goals over/under": ("total", "full_time", "match", "regular_time", ""),
    "goals over/under first half": ("total", "first_half", "match", "regular_time", ""),
    "goals over/under - second half": ("total", "second_half", "match", "regular_time", ""),
    "total - home": ("team_total", "full_time", "home", "regular_time", ""),
    "total - away": ("team_total", "full_time", "away", "regular_time", ""),
    "home team total goals(1st half)": ("team_total", "first_half", "home", "regular_time", ""),
    "away team total goals(1st half)": ("team_total", "first_half", "away", "regular_time", ""),
    "home team total goals(2nd half)": ("team_total", "second_half", "home", "regular_time", ""),
    "away team total goals(2nd half)": ("team_total", "second_half", "away", "regular_time", ""),
    "exact score": ("exact_score", "full_time", "match", "regular_time", ""),
    "correct score": ("exact_score", "full_time", "match", "regular_time", ""),
    "correct score - first half": ("exact_score", "first_half", "match", "regular_time", ""),
    "correct score - second half": ("exact_score", "second_half", "match", "regular_time", ""),
    # API-Football represents both Home/Away prices against the HOME handicap.
    # Away -1.5 is the away selection on home -1.5, NOT away's own -1.5.
    "asian handicap": ("handicap", "full_time", "match", "asian", "home"),
    "asian handicap first half": ("handicap", "first_half", "match", "asian", "home"),
    "asian handicap (2nd half)": ("handicap", "second_half", "match", "asian", "home"),
    "handicap result": ("handicap", "full_time", "match", "european", "home"),
    "handicap result - first half": ("handicap", "first_half", "match", "european", "home"),
    "european handicap (2nd half)": ("handicap", "second_half", "match", "european", "home"),
}


def _selection_and_line(market, outcome, kind):
    label = str(outcome.get("raw_name") or outcome.get("name") or "").strip()
    if not label:
        label = str(outcome.get("key") or "")
    if kind in {"total", "team_total", "handicap"}:
        if kind == "handicap":
            parsed = re.fullmatch(r"(home|away|draw)\s*\(?\s*([+-]?\d+(?:[.,]\d+)?)?\s*\)?", label, re.I)
        else:
            parsed = re.fullmatch(r"(over|under|тб|тм)\s*\(?\s*([+-]?\d+(?:[.,]\d+)?)?\s*\)?", label, re.I)
        if not parsed:
            return None
        selection = _text(parsed.group(1))
        selection = {"тб": "over", "тм": "under"}.get(selection, selection)
        explicit = outcome.get("line")
        text_line = parsed.group(2)
        if explicit not in (None, "") and text_line is not None:
            if format_outcome_line(explicit) != format_outcome_line(text_line):
                return None
        # market.line is often just the FIRST line of a multi-line market.
        value = explicit if explicit not in (None, "") else text_line
        if value is None:
            value = market.get("line")
        line = format_outcome_line(value)
        if not line:
            return None
        if kind != "handicap" and Decimal(line) < 0:
            return None
        if kind == "handicap":
            rules = FOOTBALL_MARKETS[_text(market.get("name"))][3]
            if rules == "asian" and selection == "draw":
                return None
            if rules == "european" and Decimal(line) != Decimal(line).to_integral_value():
                return None
        return selection, line
    allowed = {
        "winner": {"home", "away", "draw", "1", "2", "x", "п1", "п2", "ничья"},
        "double_chance": {"home/draw", "home/away", "draw/away", "home_draw", "home_away", "draw_away", "1x", "x2", "2x", "12"},
        "both_score": {"yes", "no", "да", "нет"},
    }
    if kind in allowed and _text(label) not in allowed[kind]:
        return None
    if kind == "exact_score" and not re.fullmatch(r"\d+\s*[:\-]\s*\d+", label):
        return None
    selection = outcome_code_from_label(kind, label)
    if not selection:
        return None
    if outcome.get("line") not in (None, "") or market.get("line") not in (None, ""):
        return None
    return selection, ""


def normalize_bookmaker_markets(markets, *, match_id, sport_code, scope):
    """Return offers + diagnostics; do not pick a winner or mutate source data."""
    offers = []
    reasons = Counter()
    candidates = {}
    ambiguous = set()
    for market_index, market in enumerate(markets):
        definition = FOOTBALL_MARKETS.get(_text(market.get("name"))) if sport_code == "football" else None
        for outcome_index, outcome in enumerate(market.get("outcomes", [])):
            if scope not in {"prematch", "live"}:
                reasons["unsupported_scope"] += 1
                continue
            if sport_code != "football":
                reasons["unaudited_sport"] += 1
                continue
            if definition is None:
                reasons["unsupported_market"] += 1
                continue
            kind, period, team, settlement, reference = definition
            # Names recover team totals where v2 leaves team=null; conflicts are unsafe.
            if market.get("period") not in (None, "", period) or market.get("team") not in (None, "", team):
                reasons["conflicting_context"] += 1
                continue
            if market.get("suspended") is True or outcome.get("suspended") is True:
                reasons["suspended"] += 1
                continue
            try:
                price = Decimal(str(outcome.get("odds")))
            except InvalidOperation:
                reasons["invalid_price"] += 1
                continue
            if not price.is_finite() or price <= 1:
                reasons["invalid_price"] += 1
                continue
            parsed = _selection_and_line(market, outcome, kind)
            if parsed is None:
                reasons["unsupported_outcome"] += 1
                continue
            selection, line = parsed
            identity = [str(match_id), sport_code, scope, "goals", kind, period, team, settlement, reference, selection, line]
            key = "|".join(identity)
            offer = {
                "comparison_key": key,
                "match_id": match_id, "sport": sport_code, "scope": scope,
                "metric": "goals", "market": kind, "period": period, "team": team,
                "settlement": settlement, "line_reference": reference,
                "selection": selection, "line": line, "coefficient": format(price.normalize(), "f"),
                "source": {"market_index": market_index, "outcome_index": outcome_index,
                           "market_id": market.get("id"), "raw_key": market.get("raw_key"),
                           "market_name": market.get("name"), "outcome_name": outcome.get("name")},
            }
            previous = candidates.get(key)
            if previous and previous["coefficient"] != offer["coefficient"]:
                # Two conflicting prices from one BK must not silently become a best price.
                ambiguous.add(key)
            candidates.setdefault(key, offer)
    for key, offer in candidates.items():
        if key in ambiguous:
            reasons["conflicting_duplicate"] += 1
        else:
            offers.append(offer)
    return offers, {"version": NORMALIZATION_VERSION, "accepted": len(offers), "skipped": dict(reasons)}


def build_match_comparison_groups(match, scope="prematch"):
    """Group saved available offers; freshness checks and best-price selection are separate."""
    snapshot = match.odds_snapshots.filter(scope=scope, available=True).first()
    if snapshot is None:
        return []
    return _comparison_groups(match, snapshot)


def _comparison_groups(match, snapshot):
    groups = {}
    for bookmaker in snapshot.bookmakers.all():
        # Normalize from source so existing rows and mapping updates work immediately.
        offers, _ = normalize_bookmaker_markets(
            bookmaker.markets, match_id=match.pk, sport_code=match.sport_code, scope=snapshot.scope,
        )
        for offer in offers:
            key = offer["comparison_key"]
            group = groups.setdefault(key, {k: v for k, v in offer.items() if k not in {"coefficient", "source"}})
            group.setdefault("offers", []).append({
                "bookmaker_key": bookmaker.bookmaker_key, "bookmaker": bookmaker.name,
                "coefficient": offer["coefficient"], "source": offer["source"],
            })
    result = []
    for key in sorted(groups):
        group = groups[key]
        brands = {}
        for offer in group["offers"]:
            brands.setdefault(_text(offer["bookmaker"]), []).append(offer)
        # Provider PKs can repeat a brand. Never manufacture a better offer by
        # choosing one of its conflicting feed records.
        group["offers"] = [
            entries[0] for entries in brands.values()
            if len({Decimal(o["coefficient"]) for o in entries}) == 1
        ]
        if group["offers"]:
            result.append(group)
    return result


def build_match_odds_comparison(match, scope=None, *, now=None):
    """Rank fresh current lines or explicitly labelled archives of finished games.

    Freshness is measured both from our successful fetch and the provider's
    update. Re-fetching an old provider snapshot must not make its prices fresh.
    Stale active lines remain unranked; finished games compare their saved slice.
    """
    now = now or timezone.now()
    # The public comparison is always prematch, including during/after a game.
    # Live is an explicit internal opt-in, never a fallback for a missing archive.
    scope = scope or "prematch"
    if scope not in {"prematch", "live"}:
        raise ValueError("Odds comparison scope must be prematch or live")
    stale_seconds = max(1, int(getattr(
        settings,
        "NEUROKEFF_LIVE_ODDS_STALE_SECONDS" if scope == "live" else "NEUROKEFF_PREMATCH_ODDS_STALE_SECONDS",
        60 if scope == "live" else 3600,
    )))
    snapshot = match.odds_snapshots.filter(scope=scope).prefetch_related("bookmakers").first()
    archived = match.sync_scope == "finished" or (scope == "prematch" and (
        match.sync_scope != "prematch" or (match.starts_at and match.starts_at <= now)
    ))
    result = {"status": "missing", "scope": scope, "stale_seconds": stale_seconds,
              "provider_updated_at": None, "fetched_at": None, "groups": [], "archived": bool(archived),
              "archive_needs_refresh": bool(archived and match.starts_at and match.starts_at <= now
                                            and (snapshot is None or snapshot.fetched_at < match.starts_at))}
    if snapshot is None:
        return result
    result.update(
        provider_updated_at=snapshot.provider_updated_at.isoformat() if snapshot.provider_updated_at else None,
        fetched_at=snapshot.fetched_at.isoformat(),
    )
    if not snapshot.available and not (archived and snapshot.bookmakers.all()):
        result["status"] = "unavailable"
        return result
    groups = _comparison_groups(match, snapshot)
    if snapshot.fetched_at > now or (snapshot.provider_updated_at and snapshot.provider_updated_at > now):
        status = "invalid_timestamp"
    elif match.sync_scope == "finished":
        status = "finished"
    elif archived:
        status = "archived"
    elif match.sync_scope != scope:
        status = "scope_mismatch"
    elif snapshot.provider_updated_at is None:
        status = "unknown_freshness"
    elif (now - snapshot.fetched_at).total_seconds() > stale_seconds or (
        now - snapshot.provider_updated_at
    ).total_seconds() > stale_seconds:
        status = "stale"
    else:
        status = "ready" if groups else "empty"
    result["status"] = status
    for group in groups:
        offers = group["offers"]
        # Repeated feed records for the same named BK do not count as competitors.
        bookmaker_count = len({_text(offer["bookmaker"]) for offer in offers})
        has_comparison = bookmaker_count >= 2
        eligible = status in {"ready", "archived", "finished"} and has_comparison
        best = max(Decimal(offer["coefficient"]) for offer in offers) if eligible else None
        winners = []
        for offer in offers:
            offer["is_best"] = best is not None and Decimal(offer["coefficient"]) == best
            if offer["is_best"]:
                winners.append({"bookmaker_key": offer["bookmaker_key"], "bookmaker": offer["bookmaker"]})
        group.update(
            bookmaker_count=bookmaker_count,
            has_comparison=has_comparison,
            status=("single_bookmaker" if status == "ready" and not has_comparison else status),
            best_coefficient=format(best, "f") if best is not None else None,
            best_bookmakers=winners,
        )
    result["groups"] = groups
    return result


def _display_coefficient(value):
    whole, _, fraction = format(Decimal(value), "f").partition(".")
    return whole + "." + fraction.ljust(2, "0")


def _match_winner_sidebar_offers(groups, rows, brand_info):
    """Best full-time P1/X/P2 offers; independent from the active table filter."""
    offers = []
    for index, (group, row) in enumerate(zip(groups, rows)):
        if group["period"] != "full_time" or row["label"] not in {"П1", "Х", "П2"}:
            continue
        if not group["best_coefficient"] or not row["winner_brands"]:
            continue
        best = Decimal(group["best_coefficient"])
        brand = min(row["winner_brands"], key=lambda item: (item["name"].casefold(), item["key"]))
        competitor = max(
            (offer for offer in group["offers"] if _text(offer["bookmaker"]) != brand["key"]),
            key=lambda offer: Decimal(offer["coefficient"]),
        )
        runner_up = Decimal(competitor["coefficient"])
        edge = (best / runner_up - 1) * 100
        advantage = "Один из лучших коэффициентов"
        if edge > 0:
            percent = format(edge.quantize(Decimal("0.1"), rounding=ROUND_DOWN), "f").rstrip("0").rstrip(".").replace(".", ",")
            percent = f"на {percent}%" if percent != "0" else "менее чем на 0,1%"
            competitor_name = brand_info(_text(competitor["bookmaker"]), competitor["bookmaker"])["name"]
            advantage = f"{percent} выше, чем у {competitor_name}"
        offers.append({"bookmaker": brand, "label": row["label"], "context": row["context"],
                       "coefficient": row["best"], "advantage": advantage, "row_index": index})
    return sorted(offers, key=lambda offer: {"П1": 0, "Х": 1, "П2": 2}[offer["label"]])


def _compact_dense_market_groups(kind, groups):
    """Keep a useful, stable subset of line-based markets for the comparison UI."""
    if kind not in {"total", "handicap"}:
        return groups

    slots = {}
    for group in groups:
        key = (group["period"], group["settlement"], group["team"], group["line"])
        slots.setdefault(key, []).append(group)

    context_order = (
        (("full_time", "regular_time"), ("first_half", "regular_time"), ("second_half", "regular_time"))
        if kind == "total"
        else (("full_time", "asian"), ("full_time", "european"),
              ("first_half", "asian"), ("first_half", "european"),
              ("second_half", "asian"), ("second_half", "european"))
    )
    selected_context = next(
        (context for context in context_order if any(key[:2] == context for key in slots)),
        None,
    )
    candidate_keys = [key for key in slots if selected_context is None or key[:2] == selected_context]

    def line_value(key):
        return Decimal(key[3])

    selected_keys = []
    if kind == "total":
        remaining = set(candidate_keys)
        for target in (Decimal("0.5"), Decimal("2.5"), Decimal("3.5")):
            if not remaining:
                break
            closest = min(
                remaining,
                key=lambda key: (
                    abs(line_value(key) - target),
                    -len({group["selection"] for group in slots[key]}),
                    line_value(key),
                ),
            )
            selected_keys.append(closest)
            remaining.remove(closest)
    else:
        selected_keys = sorted(
            candidate_keys,
            key=lambda key: (
                abs(line_value(key)),
                line_value(key),
                -len({group["selection"] for group in slots[key]}),
            ),
        )[:DENSE_MARKET_LINE_LIMIT]

    selected = set(selected_keys)
    return [group for group in groups if (
        group["period"], group["settlement"], group["team"], group["line"]
    ) in selected]


def build_match_odds_comparison_ui(match):
    """Presentation for the read-only comparison panel, shared by SSR and refresh."""
    result = build_match_odds_comparison(match)
    brand_keys = {_text(o["bookmaker"]) for g in result["groups"] for o in g["offers"]}
    brands = {b.key: b for b in ComparisonBookmaker.objects.filter(key__in=brand_keys)}

    def brand_info(key, source_name):
        brand = brands.get(key)
        name = brand.name if brand else source_name
        return {"key": key, "name": name, "icon": brand.icon_url if brand else "",
                "initials": name[:2].upper()}

    titles = {"winner": "Исход матча", "total": "Тоталы", "handicap": "Форы", "both_score": "Обе забьют"}
    periods = {"full_time": "Матч", "first_half": "1-й тайм", "second_half": "2-й тайм"}
    sections = []
    for kind, title in titles.items():
        groups = [g for g in result["groups"] if g["market"] == kind]
        groups = _compact_dense_market_groups(kind, groups)
        if not groups:
            continue
        books = {}
        for group in groups:
            for offer in group["offers"]:
                books[_text(offer["bookmaker"])] = offer["bookmaker"]
        columns = [brand_info(key, name) for key, name in sorted(books.items(), key=lambda item: (item[1].casefold(), item[0]))]
        rows = []
        ordered_groups = sorted(groups, key=lambda g: (
            {"full_time": 0, "first_half": 1, "second_half": 2}.get(g["period"], 3),
            g["settlement"], Decimal(g["line"] or "0"),
            {"1": 0, "X": 1, "2": 2, "home": 0, "draw": 1, "away": 2,
             "over": 0, "under": 1}.get(g["selection"], 3), g["selection"],
        ))
        for group in ordered_groups:
            selection = group["selection"]
            if kind == "winner":
                label = {"1": "П1", "X": "Х", "2": "П2"}.get(selection, selection)
            elif kind == "total":
                label = f"{'ТБ' if selection == 'over' else 'ТМ'} {group['line']}"
            elif kind == "both_score":
                label = "Да" if selection == "yes" else "Нет"
            else:
                # Football provider lines are home-referenced; convert Asian away
                # selections to their own handicap for readable Ф2 labels.
                line = Decimal(group["line"])
                if group["settlement"] == "asian" and selection == "away":
                    line = -line
                line_label = format_outcome_line(line, signed=True)
                if group["settlement"] == "european":
                    side = {"home": "П1", "away": "П2", "draw": "Х"}[selection]
                    label = f"{side} при Ф1({line_label})"
                else:
                    side = {"home": "Ф1", "away": "Ф2"}[selection]
                    label = f"{side} ({line_label})"
            context = periods.get(group["period"], group["period"])
            if kind == "handicap":
                context += " · " + ("Азиатская" if group["settlement"] == "asian" else "Европейская")
            by_book = {_text(o["bookmaker"]): o for o in group["offers"]}
            cells = [{"value": _display_coefficient(by_book[c["key"]]["coefficient"]) if c["key"] in by_book else "—",
                      "is_best": by_book[c["key"]]["is_best"] if c["key"] in by_book else False,
                      "bookmaker": c["name"]} for c in columns]
            winners = list(dict.fromkeys(b["bookmaker"] for b in group["best_bookmakers"]))
            rows.append({"label": label, "context": context, "cells": cells,
                         "best": _display_coefficient(group["best_coefficient"]) if group["best_coefficient"] else None, "winners": ", ".join(winners),
                         "winner_brands": [brand_info(_text(name), name) for name in winners],
                         "single": not group["has_comparison"]})
        bookmaker_rows = []
        for column_index, bookmaker in enumerate(columns):
            cells = []
            for outcome_index, row in enumerate(rows):
                cell = dict(row["cells"][column_index])
                cell.update(label=row["label"], context=row["context"], outcome_index=outcome_index)
                cells.append(cell)

            margin = None
            if kind == "winner":
                full_time_cells = [
                    cell for cell in cells
                    if cell["context"] == periods["full_time"] and cell["label"] in {"П1", "Х", "П2"}
                    and cell["value"] != "—"
                ]
                if len(full_time_cells) == 3:
                    overround = (sum(Decimal("1") / Decimal(cell["value"]) for cell in full_time_cells) - 1) * 100
                    margin = format(overround.quantize(Decimal("0.1")), "f")

            bookmaker_rows.append({
                "bookmaker": bookmaker,
                "cells": cells,
                "margin": margin,
                "margin_label": f"{margin} %" if margin is not None else "—",
            })
        sections.append({"key": kind, "title": title, "columns": columns, "rows": rows,
                         "bookmaker_rows": bookmaker_rows,
                         "featured_offers": (_match_winner_sidebar_offers(ordered_groups, rows, brand_info)
                                             if kind == "winner" else []),
                         "has_best": any(row["best"] for row in rows)})
    messages = {
        "ready": "Актуальные коэффициенты",
        "stale": "Линия устарела · лучшие коэффициенты не отмечены",
        "unknown_freshness": "Время обновления неизвестно · лучшие коэффициенты не отмечены",
        "invalid_timestamp": "Актуальность не подтверждена · лучшие коэффициенты не отмечены",
        "finished": "Матч завершён · лучшие значения сохранённой линии",
        "archived": "Сохранённая предматчевая линия · не текущие предложения",
        "scope_mismatch": "Режим линии изменился · ожидаем обновление",
    }
    result.pop("groups")
    updated = parse_datetime(result["provider_updated_at"]) if result["provider_updated_at"] else None
    expires = None
    if result["status"] == "ready":
        expires = min(updated, parse_datetime(result["fetched_at"])) + timedelta(seconds=result["stale_seconds"])
        if result["scope"] == "prematch" and match.starts_at:
            expires = min(expires, match.starts_at)
    winner_section = next((section for section in sections if section["key"] == "winner"), None)
    result.update(sections=sections, visible=bool(sections), updated_at=updated,
                  sidebar_offers=winner_section["featured_offers"] if winner_section else [],
                  match_title=f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}",
                  match_meta=" · ".join(filter(None, (match.league_name, format_match_start_label(match.starts_at)))),
                  ranking_label=("Архив предматчевой линии · не текущие предложения" if result["scope"] == "prematch"
                                 else "Архив live-линии · не текущие предложения") if result["archived"]
                                else "Максимальные предматчевые коэффициенты среди актуальных предложений БК",
                  note=("Сравниваются одинаковые исходы сохранённой предматчевой линии. Это не текущие предложения для ставок."
                        if result["archived"] else
                        "Сравниваются одинаковые исходы предматчевой линии. Лучшие значения отмечены среди доступных БК; ставки добавляются в купон в блоке выше."),
                  expires_at=expires.isoformat() if expires else "",
                  message=messages.get(result["status"], ""), match_scope=match.sync_scope,
                  supported=match.sport_code == "football")
    return result

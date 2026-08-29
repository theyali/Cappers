from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .models import CapperMonthlyStat


MONTH_NAMES_RU = (
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)
SPORT_ORDER = {
    "football": 0,
    "hockey": 1,
    "basketball": 2,
    "tennis": 3,
}
SPORT_NAMES_RU = {
    "football": "Футбол",
    "hockey": "Хоккей",
    "basketball": "Баскетбол",
    "tennis": "Теннис",
}
SPORT_DECIMAL_FIELDS = (
    "allocated_stake",
    "allocated_profit",
    "flat_units",
    "weight",
    "coefficient_sum",
)
SPORT_INTEGER_FIELDS = (
    "predictions_count",
    "wins_count",
    "losses_count",
    "refunds_count",
)


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _percent(numerator: Decimal, denominator: Decimal) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator / denominator * Decimal("100")), 1)


def prediction_count_text(count: int) -> str:
    value = abs(int(count))
    last_two = value % 100
    last = value % 10
    if 11 <= last_two <= 14:
        word = "прогнозов"
    elif last == 1:
        word = "прогноз"
    elif 2 <= last <= 4:
        word = "прогноза"
    else:
        word = "прогнозов"
    return f"{count} {word}"


def _empty_sport_bucket(code: str, name: str = "") -> dict:
    return {
        "code": code,
        "name": name or SPORT_NAMES_RU.get(code, code.capitalize()),
        "predictions_count": 0,
        "wins_count": 0,
        "losses_count": 0,
        "refunds_count": 0,
        "allocated_stake": Decimal("0"),
        "allocated_profit": Decimal("0"),
        "flat_units": Decimal("0"),
        "weight": Decimal("0"),
        "coefficient_sum": Decimal("0"),
    }


def _merge_sport_snapshot(target: dict[str, dict], snapshot: dict | None) -> None:
    if not isinstance(snapshot, dict):
        return
    for code, raw in snapshot.items():
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or code or "football")
        bucket = target.setdefault(
            code,
            _empty_sport_bucket(code, str(raw.get("name") or "")),
        )
        if raw.get("name"):
            bucket["name"] = str(raw["name"])
        for field in SPORT_INTEGER_FIELDS:
            bucket[field] += int(raw.get(field) or 0)
        for field in SPORT_DECIMAL_FIELDS:
            bucket[field] += _decimal(raw.get(field))


def _result_row(
    *,
    code: str,
    name: str,
    predictions_count: int,
    wins_count: int,
    losses_count: int,
    refunds_count: int,
    profit_percent: float,
    roi: float,
) -> dict:
    states_total = wins_count + losses_count + refunds_count
    denominator = states_total or predictions_count
    return {
        "code": code,
        "name": name,
        "predictions_count": predictions_count,
        "predictions_text": prediction_count_text(predictions_count),
        "wins_count": wins_count,
        "losses_count": losses_count,
        "refunds_count": refunds_count,
        "win_percent": round(wins_count / denominator * 100, 1) if denominator else 0,
        "loss_percent": round(losses_count / denominator * 100, 1) if denominator else 0,
        "refund_percent": round(refunds_count / denominator * 100, 1) if denominator else 0,
        "profit_percent": profit_percent,
        "profit_display": f"{profit_percent:.1f}%",
        "roi": roi,
        "roi_display": f"{roi:.1f}%",
    }


def sport_rows(snapshot: dict | None) -> list[dict]:
    merged: dict[str, dict] = {}
    _merge_sport_snapshot(merged, snapshot)
    rows = []
    for code, bucket in merged.items():
        profit_percent = _percent(bucket["flat_units"], bucket["weight"])
        roi = _percent(bucket["allocated_profit"], bucket["allocated_stake"])
        rows.append(
            _result_row(
                code=code,
                name=bucket["name"] or SPORT_NAMES_RU.get(code, code.capitalize()),
                predictions_count=bucket["predictions_count"],
                wins_count=bucket["wins_count"],
                losses_count=bucket["losses_count"],
                refunds_count=bucket["refunds_count"],
                profit_percent=profit_percent,
                roi=roi,
            )
        )
    return sorted(
        rows,
        key=lambda row: (
            SPORT_ORDER.get(row["code"], 100),
            row["name"].lower(),
        ),
    )


def _overall_row(rows: list[CapperMonthlyStat]) -> dict:
    bets_count = sum(row.bets_count for row in rows)
    wins_count = sum(row.wins_count for row in rows)
    losses_count = sum(row.losses_count for row in rows)
    refunds_count = sum(row.refunds_count for row in rows)
    total_stake = sum((_decimal(row.total_stake) for row in rows), Decimal("0"))
    total_profit = sum((_decimal(row.total_profit) for row in rows), Decimal("0"))
    flat_units = sum(
        (
            _decimal(row.flat_profit_percent)
            * Decimal(row.bets_count)
            / Decimal("100")
            for row in rows
        ),
        Decimal("0"),
    )
    profit_percent = _percent(flat_units, Decimal(bets_count))
    roi = _percent(total_profit, total_stake)
    return _result_row(
        code="all",
        name="Все виды спорта",
        predictions_count=bets_count,
        wins_count=wins_count,
        losses_count=losses_count,
        refunds_count=refunds_count,
        profit_percent=profit_percent,
        roi=roi,
    )


def sport_profit_periods(
    rows: list[CapperMonthlyStat],
) -> tuple[dict[str, dict], list[dict]]:
    all_time_snapshot: dict[str, dict] = {}
    periods: dict[str, dict] = {}
    options = [{"key": "all", "label": "все время"}]

    for row in rows:
        _merge_sport_snapshot(all_time_snapshot, row.sports_data)
        key = row.month.strftime("%Y-%m")
        label = f"{MONTH_NAMES_RU[row.month.month].lower()} {row.month.year}"
        periods[key] = {
            "key": key,
            "label": label,
            "rows": [_overall_row([row]), *sport_rows(row.sports_data)],
        }
        options.append({"key": key, "label": label})

    periods = {
        "all": {
            "key": "all",
            "label": "все время",
            "rows": [_overall_row(rows), *sport_rows(all_time_snapshot)] if rows else [],
        },
        **periods,
    }
    return periods, options

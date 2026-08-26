import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from cabinet.models import User
from game.models import Match, MatchOdds, Prediction, PredictionCoupon
from game.services.coupon_validation import (
    CouponMatchVerificationError,
    verify_matches_for_coupon,
)


SCOPE_FILTERS = (
    ("all", "Все"),
    (Match.SyncScope.LIVE, "Идут сейчас"),
    (Match.SyncScope.PREMATCH, "Предстоящие"),
    (Match.SyncScope.FINISHED, "Завершенные"),
)


def match_list(request):
    active_scope = request.GET.get("scope", "all")
    valid_scopes = {scope for scope, _ in SCOPE_FILTERS}
    if active_scope not in valid_scopes:
        active_scope = "all"

    matches = Match.objects.select_related(
        "sport",
        "league__country",
        "home_team",
        "away_team",
        "odds",
    )
    if active_scope != "all":
        matches = matches.filter(sync_scope=active_scope)

    matches = list(
        matches.annotate(
            scope_order=Case(
                When(sync_scope=Match.SyncScope.LIVE, then=Value(0)),
                When(sync_scope=Match.SyncScope.PREMATCH, then=Value(1)),
                When(sync_scope=Match.SyncScope.FINISHED, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        ).order_by("scope_order", "starts_at", "id")[:60]
    )

    for match in matches:
        match.coupon_odds = _match_winner_odds(match)

    counts = {
        row["sync_scope"]: row["total"]
        for row in Match.objects.values("sync_scope").annotate(total=Count("id"))
    }
    total_count = sum(counts.values())
    scope_tabs = [
        {
            "scope": scope,
            "label": label,
            "count": total_count if scope == "all" else counts.get(scope, 0),
        }
        for scope, label in SCOPE_FILTERS
    ]

    can_write_coupon = (
        request.user.is_authenticated and request.user.role == User.Role.ANALYST
    )
    draft_coupon = _active_draft_coupon(request.user) if can_write_coupon else None

    context = {
        "active_scope": active_scope,
        "scope_tabs": scope_tabs,
        "matches": matches,
        "total_count": total_count,
        "can_write_coupon": can_write_coupon,
        "latest_predictions": _latest_predictions(),
        "draft_coupon": _serialize_draft_coupon(draft_coupon) if draft_coupon else None,
        "coupon_match_stale_seconds": settings.COUPON_MATCH_STALE_SECONDS,
    }
    return render(request, "game/match_list.html", context)


def match_detail(request, slug: str):
    match = get_object_or_404(
        Match.objects.select_related(
            "sport",
            "league__country",
            "home_team",
            "away_team",
            "odds",
        ),
        slug=slug,
    )
    can_write_coupon = (
        request.user.is_authenticated and request.user.role == User.Role.ANALYST
    )
    draft_coupon = _active_draft_coupon(request.user) if can_write_coupon else None

    context = {
        "match": match,
        "can_write_coupon": can_write_coupon,
        "latest_predictions": _latest_predictions(),
        "draft_coupon": _serialize_draft_coupon(draft_coupon) if draft_coupon else None,
        "coupon_match_stale_seconds": settings.COUPON_MATCH_STALE_SECONDS,
        "odds_tabs": _match_odds_tabs(match),
    }
    return render(request, "game/match_detail.html", context)


@login_required
@require_POST
def create_coupon(request):
    if request.user.role != User.Role.ANALYST:
        raise PermissionDenied("Купоны могут создавать только аналитики.")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Некорректный JSON."}, status=400)

    autosave = bool(payload.get("autosave"))
    items = payload.get("items")
    if not isinstance(items, list):
        return JsonResponse({"ok": False, "error": "Передайте список матчей."}, status=400)
    if len(items) > 5 or (not autosave and len(items) < 1):
        return JsonResponse(
            {"ok": False, "error": "В купоне должно быть от 1 до 5 игр."},
            status=400,
        )

    coupon_id = _to_positive_int(payload.get("coupon_id"))
    if autosave and not items:
        if coupon_id:
            PredictionCoupon.objects.filter(
                pk=coupon_id,
                author=request.user,
                published_status=PredictionCoupon.PublishedStatus.DRAFT,
            ).delete()
        return JsonResponse(
            {
                "ok": True,
                "draft_id": None,
                "message": "Пустой черновик удален.",
                "autosaved": True,
            }
        )

    try:
        match_ids = _extract_match_ids(items)
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": _validation_message(exc)}, status=400)

    if len(set(match_ids)) != len(items):
        return JsonResponse(
            {"ok": False, "error": "Один матч нельзя добавить дважды."},
            status=400,
        )

    matches = {
        match.id: match
        for match in Match.objects.filter(id__in=match_ids)
    }
    if len(matches) != len(items):
        return JsonResponse({"ok": False, "error": "Один из матчей не найден."}, status=400)

    non_prematch = [
        match for match in matches.values() if match.sync_scope != Match.SyncScope.PREMATCH
    ]
    if non_prematch:
        match = non_prematch[0]
        return JsonResponse(
            {
                "ok": False,
                "error": f"Матч «{match.home_team_name} — {match.away_team_name}» уже начался или завершен.",
            },
            status=409,
        )

    verification = None
    if not autosave:
        try:
            verification = verify_matches_for_coupon(list(matches.values()))
        except ValidationError as exc:
            return JsonResponse(
                {"ok": False, "error": _validation_message(exc)},
                status=409,
            )
        except CouponMatchVerificationError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=503)

    try:
        stake = _parse_stake(payload.get("stake"), required=not autosave)
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": _validation_message(exc)}, status=400)

    comment = str(payload.get("comment") or "").strip()
    if not autosave and not comment:
        return JsonResponse(
            {"ok": False, "error": "Заполните комментарий к купону."},
            status=400,
        )
    if len(comment) > 1200:
        return JsonResponse(
            {"ok": False, "error": "Комментарий слишком длинный."},
            status=400,
        )

    try:
        normalized_items = [_normalize_prediction_item(item, matches) for item in items]
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": _validation_message(exc)}, status=400)

    total_coefficient = Decimal("1")
    for item in normalized_items:
        total_coefficient *= item["coefficient"]
    possible_payout = stake * total_coefficient if stake > 0 else Decimal("0")

    with transaction.atomic():
        coupon = _draft_for_update(request.user, coupon_id)
        if coupon is None:
            coupon = PredictionCoupon(author=request.user)

        coupon.total_stake = stake
        coupon.possible_payout = possible_payout
        coupon.published_status = (
            PredictionCoupon.PublishedStatus.DRAFT
            if autosave
            else PredictionCoupon.PublishedStatus.PUBLISHED
        )
        coupon.published_at = None if autosave else timezone.now()
        coupon.save()

        coupon.predictions.all().delete()
        Prediction.objects.bulk_create(
            [
                Prediction(
                    coupon=coupon,
                    match=item["match"],
                    market=item["market"],
                    selection=item["selection"],
                    coefficient=item["coefficient"],
                    stake=stake,
                    comment=comment,
                )
                for item in normalized_items
            ]
        )

    coupon = (
        PredictionCoupon.objects.prefetch_related("predictions__match")
        .get(pk=coupon.pk)
    )
    response = {
        "ok": True,
        "coupon_id": coupon.id,
        "draft_id": coupon.id if autosave else None,
        "autosaved": autosave,
        "message": (
            "Черновик сохранен автоматически."
            if autosave
            else "Прогноз опубликован."
        ),
        "draft": _serialize_draft_coupon(coupon) if autosave else None,
    }
    if verification is not None:
        response["remote_checked"] = verification.remote_checked
        response["cache_used"] = verification.cache_used
    return JsonResponse(response)


def _extract_match_ids(items: list[dict]) -> list[int]:
    match_ids: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("Некорректная игра в купоне.")
        match_id = _to_positive_int(item.get("match_id"))
        if match_id is None:
            raise ValidationError("Матч не найден.")
        match_ids.append(match_id)
    return match_ids


def _parse_stake(value, *, required: bool) -> Decimal:
    raw = str(value or "").replace(",", ".").strip()
    if not raw:
        if required:
            raise ValidationError("Укажите сумму ставки.")
        return Decimal("0")

    try:
        stake = Decimal(raw)
    except (InvalidOperation, ValueError):
        if required:
            raise ValidationError("Укажите корректную сумму ставки.")
        return Decimal("0")

    if stake <= 0:
        if required:
            raise ValidationError("Сумма ставки должна быть больше нуля.")
        return Decimal("0")
    return stake


def _draft_for_update(user: User, coupon_id: int | None) -> PredictionCoupon | None:
    queryset = PredictionCoupon.objects.select_for_update().filter(
        author=user,
        published_status=PredictionCoupon.PublishedStatus.DRAFT,
    )
    if coupon_id is not None:
        return queryset.filter(pk=coupon_id).first()
    return queryset.order_by("-updated_at", "-id").first()


def _active_draft_coupon(user: User) -> PredictionCoupon | None:
    return (
        PredictionCoupon.objects.filter(
            author=user,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
        )
        .prefetch_related("predictions__match__league__country", "predictions__match__home_team", "predictions__match__away_team")
        .order_by("-updated_at", "-id")
        .first()
    )


def _serialize_draft_coupon(coupon: PredictionCoupon) -> dict:
    predictions = list(coupon.predictions.all())
    comment = predictions[0].comment if predictions else ""
    stake = coupon.total_stake if coupon.total_stake and coupon.total_stake > 0 else None

    return {
        "id": coupon.id,
        "stake": _decimal_string(stake) if stake is not None else "",
        "comment": comment,
        "items": [_serialize_prediction(prediction) for prediction in predictions],
    }


def _serialize_prediction(prediction: Prediction) -> dict:
    match = prediction.match
    starts_at = (
        timezone.localtime(match.starts_at).strftime("%d.%m %H:%M")
        if match.starts_at
        else "Время не указано"
    )
    return {
        "matchId": str(match.id),
        "matchTitle": f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}",
        "league": match.league_name or "Лига не указана",
        "time": starts_at,
        "betKey": "restored",
        "market": prediction.market,
        "selection": prediction.selection,
        "shortLabel": _prediction_short_label(prediction),
        "coefficient": _decimal_string(prediction.coefficient),
        "lastSeen": match.last_seen_at.isoformat() if match.last_seen_at else "",
    }


def _prediction_short_label(prediction: Prediction) -> str:
    match = prediction.match
    selection = prediction.selection
    if prediction.market == "winner":
        if selection == "Ничья":
            return "X"
        if selection == match.home_team_name:
            return "1"
        if selection == match.away_team_name:
            return "2"
    if prediction.market == "total":
        return selection[:10]
    if prediction.market == "both_score":
        return "ОЗ"
    return selection[:10]


def _normalize_prediction_item(
    item: dict,
    matches: dict[int, Match],
) -> dict:
    if not isinstance(item, dict):
        raise ValidationError("Некорректная игра в купоне.")

    match_id = _to_positive_int(item.get("match_id"))
    if match_id is None or match_id not in matches:
        raise ValidationError("Матч не найден.")

    market = str(item.get("market") or "").strip()
    selection = str(item.get("selection") or "").strip()
    coefficient_raw = str(item.get("coefficient") or "").replace(",", ".").strip()

    if not market:
        raise ValidationError("Выберите тип ставки.")
    if not selection:
        raise ValidationError("Выберите исход.")

    try:
        coefficient = Decimal(coefficient_raw)
    except (InvalidOperation, ValueError):
        raise ValidationError("Укажите коэффициент.")

    if coefficient <= 0:
        raise ValidationError("Коэффициент должен быть больше нуля.")

    return {
        "match": matches[match_id],
        "market": market[:80],
        "selection": selection[:120],
        "coefficient": coefficient,
    }


def _latest_predictions():
    return (
        Prediction.objects.filter(
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related("coupon__author", "match__league__country", "match__home_team", "match__away_team")
        .order_by("-coupon__published_at", "-coupon__created_at", "-created_at")[:6]
    )


def _match_winner_odds(match: Match) -> dict[str, str]:
    try:
        odds = match.odds
    except MatchOdds.DoesNotExist:
        odds = None

    return {
        "home": _format_odd(odds.home_win_bet if odds else Decimal("2")),
        "draw": _format_odd(odds.x_bet if odds else Decimal("2")),
        "away": _format_odd(odds.away_win_bet if odds else Decimal("2")),
        "over25": _format_odd((odds.goals_over_2_5 or _nested_odd(odds.totals_all, "Over 2.5")) if odds else Decimal("2")),
        "under25": _format_odd((odds.goals_under_2_5 or _nested_odd(odds.totals_all, "Under 2.5")) if odds else Decimal("2")),
        "btts_yes": _format_odd(odds.btts_yes if odds else Decimal("2")),
    }


def _match_odds_tabs(match: Match) -> list[dict]:
    if match.sync_scope != Match.SyncScope.PREMATCH:
        return []

    try:
        odds = match.odds
    except MatchOdds.DoesNotExist:
        odds = None
    if odds is None:
        return []

    home_name = match.home_team_name or "Хозяева"
    away_name = match.away_team_name or "Гости"

    popular_sections = [
        _odds_section(
            "Исход матча",
            [
                _odds_row(
                    "Основное время",
                    [
                        _odds_button("1", home_name, "winner", home_name, _optional_odd(odds.home_win_bet)),
                        _odds_button("X", "Ничья", "winner", "Ничья", _optional_odd(odds.x_bet)),
                        _odds_button("2", away_name, "winner", away_name, _optional_odd(odds.away_win_bet)),
                    ],
                ),
                _odds_row(
                    "Двойной шанс",
                    [
                        _odds_button("1X", f"{home_name} или ничья", "double_chance", f"{home_name} или ничья", _optional_odd(odds.d_1x)),
                        _odds_button("X2", f"Ничья или {away_name}", "double_chance", f"Ничья или {away_name}", _optional_odd(odds.d_2x)),
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
                        _odds_button("ТБ 2.5", "Больше 2.5", "total", "ТБ 2.5", _optional_odd(odds.goals_over_2_5)),
                        _odds_button("ТМ 2.5", "Меньше 2.5", "total", "ТМ 2.5", _optional_odd(odds.goals_under_2_5)),
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
                        _odds_button("ОЗ Да", "Да", "both_score", "Обе забьют: да", _optional_odd(odds.btts_yes)),
                        _odds_button("ОЗ Нет", "Нет", "both_score", "Обе забьют: нет", _optional_odd(odds.btts_no)),
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
                        _odds_button("Ф1 0", home_name, "handicap", f"{home_name} фора 0", _optional_odd(odds.fora_1_0)),
                        _odds_button("Ф2 0", away_name, "handicap", f"{away_name} фора 0", _optional_odd(odds.fora_2_0)),
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
                    _odds_button("1", home_name, "first_half_winner", f"1-й тайм: {home_name}", _optional_odd(odds.first_time_home_win_bet)),
                    _odds_button("X", "Ничья", "first_half_winner", "1-й тайм: ничья", _optional_odd(odds.first_time_x_bet)),
                    _odds_button("2", away_name, "first_half_winner", f"1-й тайм: {away_name}", _optional_odd(odds.first_time_away_win_bet)),
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
    return [tab for tab in tabs if tab["sections"]]


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
        odd = _optional_odd(raw_value)
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
        rows.append(
            _odds_row(
                f"Тотал {line}",
                [
                    _odds_button(f"ТБ {line}", f"Больше {line}", market, f"ТБ {line}", values.get("over")),
                    _odds_button(f"ТМ {line}", f"Меньше {line}", market, f"ТМ {line}", values.get("under")),
                ],
            )
        )

    return rows


def _generic_market_rows(payload: dict, market: str, title: str) -> list[dict]:
    if not isinstance(payload, dict):
        return []

    grouped_rows: list[dict] = []
    flat_buttons: list[dict] = []
    for raw_key, raw_value in payload.items():
        label = _human_market_label(raw_key)
        if isinstance(raw_value, dict):
            row = _odds_row(
                label,
                [
                    _odds_button(
                        _short_odd_label(option_key),
                        _human_market_label(option_key),
                        market,
                        f"{label}: {_human_market_label(option_key)}",
                        _optional_odd(option_value),
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
                _optional_odd(raw_value),
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
                _human_market_label(raw_title),
                _generic_market_rows(raw_value, f"extra:{raw_title}", _human_market_label(raw_title)),
            )
            if section["rows"]:
                sections.append(section)
    return sections


def _human_market_label(value) -> str:
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
    return replacements.get(lower, text.replace("_", " ").replace("-", " ").strip() or "Ставка")


def _short_odd_label(value) -> str:
    text = _human_market_label(value)
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


def _optional_odd(value) -> str | None:
    try:
        odd = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if odd <= 0:
        return None
    return f"{odd.quantize(Decimal('0.01'))}"


def _nested_odd(odds: dict, key: str):
    if isinstance(odds, dict):
        return odds.get(key)
    return None


def _format_odd(value) -> str:
    try:
        odd = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        odd = Decimal("2")
    if odd <= 0:
        odd = Decimal("2")
    return f"{odd.quantize(Decimal('0.01'))}"


def _decimal_string(value: Decimal | None) -> str:
    if value is None:
        return ""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _to_positive_int(value) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _validation_message(exc: ValidationError) -> str:
    return exc.messages[0] if exc.messages else "Некорректные данные."

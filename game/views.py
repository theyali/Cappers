import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon


SCOPE_FILTERS = (
    ("all", "Все"),
    (Match.SyncScope.LIVE, "Идут сейчас"),
    (Match.SyncScope.PREMATCH, "Предстоящие"),
    (Match.SyncScope.FINISHED, "Завершенные"),
)

MARKET_LABELS = {
    "winner": "Победитель",
    "total": "Тотал",
    "handicap": "Фора",
    "both_score": "Обе забьют",
}


def match_list(request):
    active_scope = request.GET.get("scope", "all")
    valid_scopes = {scope for scope, _ in SCOPE_FILTERS}
    if active_scope not in valid_scopes:
        active_scope = "all"

    matches = Match.objects.all()
    if active_scope != "all":
        matches = matches.filter(sync_scope=active_scope)

    matches = list(matches.annotate(
        scope_order=Case(
            When(sync_scope=Match.SyncScope.LIVE, then=Value(0)),
            When(sync_scope=Match.SyncScope.PREMATCH, then=Value(1)),
            When(sync_scope=Match.SyncScope.FINISHED, then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    ).order_by("scope_order", "starts_at", "id")[:60])

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

    context = {
        "active_scope": active_scope,
        "scope_tabs": scope_tabs,
        "matches": matches,
        "total_count": total_count,
        "can_write_coupon": request.user.is_authenticated
        and request.user.role == User.Role.ANALYST,
        "latest_predictions": _latest_predictions(),
    }
    return render(request, "game/match_list.html", context)


def match_detail(request, slug: str):
    match = get_object_or_404(Match, slug=slug)
    return render(request, "game/match_detail.html", {"match": match})


@login_required
@require_POST
def create_coupon(request):
    if request.user.role != User.Role.ANALYST:
        raise PermissionDenied("Купоны могут создавать только аналитики.")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Некорректный JSON."}, status=400)

    title = str(payload.get("title") or "").strip()
    items = payload.get("items")
    if not isinstance(items, list):
        return JsonResponse({"ok": False, "error": "Передайте список матчей."}, status=400)
    if not 1 <= len(items) <= 5:
        return JsonResponse({"ok": False, "error": "В купоне должно быть от 1 до 5 игр."}, status=400)

    match_ids = [item.get("match_id") for item in items if isinstance(item, dict)]
    if len(set(match_ids)) != len(items):
        return JsonResponse({"ok": False, "error": "Один матч нельзя добавить дважды."}, status=400)

    matches = {
        match.id: match
        for match in Match.objects.filter(
            id__in=match_ids,
            sync_scope=Match.SyncScope.PREMATCH,
        )
    }
    if len(matches) != len(items):
        return JsonResponse(
            {"ok": False, "error": "В купон можно добавлять только предстоящие матчи."},
            status=400,
        )

    stake_raw = str(payload.get("stake") or "").replace(",", ".").strip()
    try:
        stake = Decimal(stake_raw)
    except (InvalidOperation, ValueError):
        return JsonResponse({"ok": False, "error": "Укажите сумму ставки."}, status=400)
    if stake <= 0:
        return JsonResponse({"ok": False, "error": "Сумма ставки должна быть больше нуля."}, status=400)

    comment = str(payload.get("comment") or "").strip()
    if not comment:
        return JsonResponse({"ok": False, "error": "Заполните комментарий к купону."}, status=400)
    if len(comment) > 1200:
        return JsonResponse({"ok": False, "error": "Комментарий слишком длинный."}, status=400)

    try:
        normalized_items = [_normalize_prediction_item(item, matches) for item in items]
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": exc.message}, status=400)

    total_coefficient = Decimal("1")
    for item in normalized_items:
        total_coefficient *= item["coefficient"]
    possible_payout = stake * total_coefficient
    if not title:
        title = _build_coupon_title(normalized_items)

    with transaction.atomic():
        coupon = PredictionCoupon.objects.create(
            author=request.user,
            title=title,
            total_stake=stake,
            possible_payout=possible_payout,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
        )
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

    return JsonResponse(
        {
            "ok": True,
            "coupon_id": coupon.id,
            "message": "Купон сохранен как черновик.",
        }
    )


def _normalize_prediction_item(
    item: dict,
    matches: dict[int, Match],
) -> dict:
    if not isinstance(item, dict):
        raise ValidationError("Некорректная игра в купоне.")

    try:
        match_id = int(item.get("match_id"))
    except (TypeError, ValueError):
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


def _build_coupon_title(items: list[dict]) -> str:
    first_item = items[0]
    match = first_item["match"]
    market = MARKET_LABELS.get(first_item["market"], first_item["market"])
    starts_at = ""
    if match.starts_at:
        starts_at = timezone.localtime(match.starts_at).strftime("%d.%m %H:%M")

    title_parts = [
        f"{match.home_team_name} — {match.away_team_name}",
        match.league_name,
        f"{market}: {first_item['selection']}",
        starts_at,
    ]
    title = " · ".join(part for part in title_parts if part)
    if len(items) > 1:
        title = f"{title} · +{len(items) - 1}"
    return title[:160]


def _latest_predictions():
    return (
        Prediction.objects.filter(
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related("coupon__author", "match")
        .order_by("-coupon__published_at", "-coupon__created_at", "-created_at")[:6]
    )


def _match_winner_odds(match: Match) -> dict[str, str]:
    odds = match.raw_data.get("odds") if isinstance(match.raw_data, dict) else {}
    if not isinstance(odds, dict):
        odds = {}

    return {
        "home": _format_odd(odds.get("home_win_bet") or odds.get("home") or odds.get("1") or Decimal("2")),
        "draw": _format_odd(odds.get("x_bet") or odds.get("draw") or odds.get("x") or Decimal("2")),
        "away": _format_odd(odds.get("away_win_bet") or odds.get("away") or odds.get("2") or Decimal("2")),
        "over25": _format_odd(odds.get("goals_over_2_5") or _nested_odd(odds, "totals_all", "Over 2.5") or Decimal("2")),
        "under25": _format_odd(odds.get("goals_under_2_5") or _nested_odd(odds, "totals_all", "Under 2.5") or Decimal("2")),
        "btts_yes": _format_odd(odds.get("btts_yes") or Decimal("2")),
    }


def _nested_odd(odds: dict, group: str, key: str):
    value = odds.get(group)
    if isinstance(value, dict):
        return value.get(key)
    return None


def _format_odd(value) -> str:
    try:
        odd = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        odd = Decimal("2")
    if odd <= 0:
        odd = Decimal("2")
    return f"{odd.quantize(Decimal('0.01'))}"

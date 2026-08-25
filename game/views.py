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
from game.models import Match, Prediction, PredictionCoupon
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
    match = get_object_or_404(Match, slug=slug)
    return render(request, "game/match_detail.html", {"match": match})


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
    title = str(payload.get("title") or "").strip()[:160]
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

    if not title and not autosave:
        title = _build_coupon_title(normalized_items)

    with transaction.atomic():
        coupon = _draft_for_update(request.user, coupon_id)
        if coupon is None:
            coupon = PredictionCoupon(author=request.user)

        coupon.title = title
        coupon.total_stake = stake
        coupon.possible_payout = possible_payout
        coupon.published_status = PredictionCoupon.PublishedStatus.DRAFT
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
        "draft_id": coupon.id,
        "autosaved": autosave,
        "message": (
            "Черновик сохранен автоматически."
            if autosave
            else "Купон сохранен как черновик."
        ),
        "draft": _serialize_draft_coupon(coupon),
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
        .prefetch_related("predictions__match")
        .order_by("-updated_at", "-id")
        .first()
    )


def _serialize_draft_coupon(coupon: PredictionCoupon) -> dict:
    predictions = list(coupon.predictions.all())
    comment = predictions[0].comment if predictions else ""
    stake = coupon.total_stake if coupon.total_stake and coupon.total_stake > 0 else None

    return {
        "id": coupon.id,
        "title": coupon.title,
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
        "title": f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}",
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
        "home": _format_odd(
            odds.get("home_win_bet") or odds.get("home") or odds.get("1") or Decimal("2")
        ),
        "draw": _format_odd(
            odds.get("x_bet") or odds.get("draw") or odds.get("x") or Decimal("2")
        ),
        "away": _format_odd(
            odds.get("away_win_bet") or odds.get("away") or odds.get("2") or Decimal("2")
        ),
        "over25": _format_odd(
            odds.get("goals_over_2_5")
            or _nested_odd(odds, "totals_all", "Over 2.5")
            or Decimal("2")
        ),
        "under25": _format_odd(
            odds.get("goals_under_2_5")
            or _nested_odd(odds, "totals_all", "Under 2.5")
            or Decimal("2")
        ),
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

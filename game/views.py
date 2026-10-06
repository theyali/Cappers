import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from cabinet.models import DailyTask, User
from cabinet.roulette.rewards import UserRouletteRewardState
from cabinet.services.daily_tasks import record_daily_task_action
from game.forms import RichPredictionCouponForm
from game.models import Match, Prediction, PredictionCoupon
from game.services.bet_options import (
    build_match_odds_tabs,
    build_match_winner_odds,
    human_market_label,
)
from game.services.coupon_validation import (
    MAX_COUPON_ITEMS,
    CouponMatchClosedError,
    CouponMatchVerificationError,
    CouponOddsChangedError,
    coupon_total_coefficient,
    extract_match_ids,
    parse_confidence,
    parse_stake,
    resolve_coupon_items,
    validate_match_timing,
    verify_matches_for_coupon,
)
from game.services.match_sync import MatchSyncService
from game.services.prediction_editor import (
    build_prediction_editor_context,
    create_rich_prediction,
    update_rich_prediction,
)
from game.services.providers.neurokeff import NeurokeffProviderError
from notifications.models import MatchWatch
from wallets.services import (
    InsufficientCoins,
    charge_prediction_stake,
    copy_published_coupon,
    cover_prediction_stake_with_free_reward,
    format_coins,
)


logger = logging.getLogger(__name__)
DRAFT_SESSION_MAX_AGE_SECONDS = max(
    int(getattr(settings, "SESSION_COOKIE_AGE", 1209600)),
    1,
)

SCOPE_FILTERS = (
    ("all", "Все"),
    (Match.SyncScope.LIVE, "Live"),
    (Match.SyncScope.PREMATCH, "Прематч"),
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
        "home_team__country",
        "away_team__country",
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
            ),
            predictions_count=Count(
                "predictions__coupon",
                filter=Q(
                    predictions__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                    predictions__coupon__audience=PredictionCoupon.Audience.FREE,
                ),
                distinct=True,
            ),
        ).order_by("scope_order", "starts_at", "id")[:60]
    )

    for match in matches:
        match.coupon_odds = build_match_winner_odds(match)

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
    free_predictions_available = _available_free_predictions(request.user) if can_write_coupon else 0

    context = {
        "active_scope": active_scope,
        "scope_tabs": scope_tabs,
        "matches": matches,
        "total_count": total_count,
        "can_write_coupon": can_write_coupon,
        "latest_predictions": _latest_predictions(),
        "draft_coupon": _serialize_draft_coupon(draft_coupon) if draft_coupon else None,
        "free_predictions_available": free_predictions_available,
        "coupon_match_stale_seconds": settings.COUPON_MATCH_STALE_SECONDS,
    }
    return render(request, "game/match_list.html", context)


def match_detail(request, slug: str):
    match = get_object_or_404(
        Match.objects.select_related(
            "sport",
            "league__country",
            "home_team__country",
            "away_team__country",
            "odds",
        ),
        slug=slug,
    )
    can_write_coupon = (
        request.user.is_authenticated and request.user.role == User.Role.ANALYST
    )
    draft_coupon = _active_draft_coupon(request.user) if can_write_coupon else None
    free_predictions_available = _available_free_predictions(request.user) if can_write_coupon else 0
    match.coupon_odds = build_match_winner_odds(match)
    match.is_watched = (
        request.user.is_authenticated
        and match.sync_scope != Match.SyncScope.FINISHED
        and MatchWatch.objects.filter(user=request.user, match=match).exists()
    )
    match._watched_for_request = match.is_watched
    _refresh_provider_predictions(match)

    context = {
        "match": match,
        "can_write_coupon": can_write_coupon,
        "latest_predictions": _latest_predictions(),
        "draft_coupon": _serialize_draft_coupon(draft_coupon) if draft_coupon else None,
        "free_predictions_available": free_predictions_available,
        "coupon_match_stale_seconds": settings.COUPON_MATCH_STALE_SECONDS,
        "odds_tabs": build_match_odds_tabs(match),
        "provider_prediction_panel": _provider_prediction_panel(match),
        "is_watched": match.is_watched,
    }
    return render(request, "game/match_detail.html", context)


@login_required
def rich_prediction_create(request):
    if not request.user.is_analyst:
        raise PermissionDenied("Расширенные прогнозы доступны только капперам.")

    source_coupon = _active_draft_coupon(request.user)
    context = build_prediction_editor_context(request, coupon=source_coupon)
    form = RichPredictionCouponForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
        coupon=source_coupon,
        initial=context["form_initial"],
    )

    if request.method == "POST" and context["has_coupon_positions"] and form.is_valid():
        try:
            coupon = create_rich_prediction(
                request.user,
                form.cleaned_data,
                request.FILES,
                source_coupon=source_coupon,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            # Publish checks may refresh coefficients in the draft: show the current ones.
            context = build_prediction_editor_context(request, coupon=_active_draft_coupon(request.user))
        else:
            return redirect("game:rich_prediction_edit", coupon_id=coupon.pk)

    context["form"] = form
    return render(request, "game/rich_prediction_form.html", context)


@login_required
def rich_prediction_edit(request, coupon_id):
    if not request.user.is_analyst:
        raise PermissionDenied("Расширенные прогнозы доступны только капперам.")

    coupon = get_object_or_404(
        PredictionCoupon.objects.select_related("cover_image"),
        pk=coupon_id,
    )
    context = build_prediction_editor_context(request, coupon=coupon)
    form = RichPredictionCouponForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
        coupon=coupon,
        initial=context["form_initial"],
    )

    if request.method == "POST" and form.is_valid():
        try:
            coupon = update_rich_prediction(
                request.user,
                coupon,
                form.cleaned_data,
                request.FILES,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            # Publish checks may refresh coefficients in the draft: show the current ones.
            coupon.refresh_from_db()
            context = build_prediction_editor_context(request, coupon=coupon)
        else:
            return redirect("game:rich_prediction_edit", coupon_id=coupon.pk)

    context["form"] = form
    return render(request, "game/rich_prediction_form.html", context)


@login_required
@require_POST
def create_coupon(request):
    if request.user.role != User.Role.ANALYST:
        raise PermissionDenied("Прогнозы могут создавать только аналитики.")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return JsonResponse({"ok": False, "error": "Некорректный JSON."}, status=400)

    autosave = bool(payload.get("autosave"))
    use_free_prediction = payload.get("use_free_prediction") is True and not autosave
    audience = PredictionCoupon.Audience.FREE

    items = payload.get("items")
    if not isinstance(items, list):
        return JsonResponse({"ok": False, "error": "Передайте список матчей."}, status=400)
    if len(items) > MAX_COUPON_ITEMS or (not autosave and len(items) < 1):
        return JsonResponse(
            {"ok": False, "error": f"В прогнозе должно быть от 1 до {MAX_COUPON_ITEMS} игр."},
            status=400,
        )

    coupon_id = _to_positive_int(payload.get("coupon_id"))
    if autosave and not items:
        if coupon_id:
            PredictionCoupon.objects.filter(
                pk=coupon_id,
                author=request.user,
                published_status=PredictionCoupon.PublishedStatus.DRAFT,
                prediction_format=PredictionCoupon.PredictionFormat.QUICK,
            ).delete()
        return JsonResponse(
            {
                "ok": True,
                "draft_id": None,
                "message": "Пустой Купон удален.",
                "autosaved": True,
            }
        )

    try:
        match_ids = extract_match_ids(items)
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": _validation_message(exc)}, status=400)

    if len(set(match_ids)) != len(items):
        return JsonResponse(
            {"ok": False, "error": "Один матч нельзя добавить дважды."},
            status=400,
        )

    matches = {
        match.id: match
        for match in Match.objects.filter(id__in=match_ids).select_related(
            "sport",
            "home_team",
            "away_team",
        )
    }
    if len(matches) != len(items):
        return JsonResponse({"ok": False, "error": "Один из матчей не найден."}, status=400)

    try:
        validate_match_timing(matches.values())
    except CouponMatchClosedError as exc:
        return JsonResponse({"ok": False, "error": _validation_message(exc)}, status=409)

    try:
        stake = parse_stake(payload.get("stake"), required=not autosave)
        confidence = parse_confidence(payload.get("confidence"))
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": _validation_message(exc)}, status=400)

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
        normalized_items = resolve_coupon_items(
            items,
            matches,
            accept_changed_odds=autosave,
        )
    except CouponOddsChangedError as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": _validation_message(exc),
                "odds_changed": exc.changes,
            },
            status=409,
        )
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": _validation_message(exc)}, status=400)

    total_coefficient = coupon_total_coefficient(normalized_items)
    possible_payout = stake * total_coefficient if stake > 0 else Decimal("0")
    coin_wallet = None
    coupon_created = False

    with transaction.atomic():
        coupon = _draft_for_update(request.user, coupon_id)
        if coupon is None:
            coupon = PredictionCoupon(
                author=request.user,
                prediction_format=PredictionCoupon.PredictionFormat.QUICK,
            )
            coupon_created = True

        coupon.prediction_format = PredictionCoupon.PredictionFormat.QUICK
        coupon.total_stake = stake
        coupon.possible_payout = possible_payout
        coupon.confidence = confidence
        coupon.published_status = (
            PredictionCoupon.PublishedStatus.DRAFT
            if autosave
            else PredictionCoupon.PublishedStatus.PUBLISHED
        )
        coupon.audience = audience
        coupon.published_at = None if autosave else timezone.now()
        coupon.save()

        if not autosave:
            try:
                if use_free_prediction:
                    _consume_free_prediction(request.user)
                    coin_wallet = cover_prediction_stake_with_free_reward(
                        request.user,
                        coupon,
                        note=f"Бесплатный прогноз из рулетки #{coupon.pk}",
                    )
                else:
                    coin_wallet = charge_prediction_stake(request.user, coupon, stake)
            except InsufficientCoins as exc:
                transaction.set_rollback(True)
                return JsonResponse({"ok": False, "error": str(exc)}, status=402)
            except ValidationError as exc:
                transaction.set_rollback(True)
                return JsonResponse({"ok": False, "error": _validation_message(exc)}, status=400)

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
                )
                for item in normalized_items
            ]
        )
        coupon.sync_coupon_type()
        if not autosave:
            coupon.assign_cover_image()
        if not autosave:
            copy_published_coupon(coupon)

    coupon = (
        PredictionCoupon.objects.prefetch_related("predictions__match")
        .get(pk=coupon.pk)
    )
    if coupon_created:
        record_daily_task_action(
            request.user,
            DailyTask.TaskType.CREATE_PREDICTION,
            related_obj=coupon,
        )
    if not autosave:
        record_daily_task_action(
            request.user,
            DailyTask.TaskType.PUBLISH_PREDICTION,
            related_obj=coupon,
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
    if not autosave and coin_wallet is not None:
        coin_wallet.refresh_from_db()
        response["coin_balance"] = coin_wallet.balance
        response["coin_balance_display"] = format_coins(coin_wallet.balance)
        response["used_free_prediction"] = use_free_prediction
        response["free_predictions_remaining"] = _available_free_predictions(
            request.user
        )
    return JsonResponse(response)


def _draft_for_update(user: User, coupon_id: int | None) -> PredictionCoupon | None:
    _delete_expired_draft_coupons(user)
    cutoff = _draft_session_cutoff()
    queryset = PredictionCoupon.objects.select_for_update().filter(
        author=user,
        published_status=PredictionCoupon.PublishedStatus.DRAFT,
        prediction_format=PredictionCoupon.PredictionFormat.QUICK,
        updated_at__gte=cutoff,
    )
    if coupon_id is not None:
        return queryset.filter(pk=coupon_id).first()
    return queryset.order_by("-updated_at", "-id").first()


def _active_draft_coupon(user: User) -> PredictionCoupon | None:
    _delete_expired_draft_coupons(user)
    return (
        PredictionCoupon.objects.filter(
            author=user,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            prediction_format=PredictionCoupon.PredictionFormat.QUICK,
            updated_at__gte=_draft_session_cutoff(),
        )
        .prefetch_related("predictions__match__league__country", "predictions__match__home_team", "predictions__match__away_team")
        .order_by("-updated_at", "-id")
        .first()
    )


def _draft_session_cutoff():
    return timezone.now() - timedelta(seconds=DRAFT_SESSION_MAX_AGE_SECONDS)


def _delete_expired_draft_coupons(user: User) -> int:
    # Drafts that still carry followers' copied stakes (coupons unpublished before
    # that was forbidden) are kept until those stakes are refunded.
    deleted, _ = PredictionCoupon.objects.filter(
        author=user,
        published_status=PredictionCoupon.PublishedStatus.DRAFT,
        updated_at__lt=_draft_session_cutoff(),
        copied_bets__isnull=True,
    ).delete()
    return deleted


def _available_free_predictions(user: User) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    return (
        UserRouletteRewardState.objects.filter(user=user)
        .values_list("free_predictions", flat=True)
        .first()
        or 0
    )


def _consume_free_prediction(user: User) -> UserRouletteRewardState:
    reward_state = (
        UserRouletteRewardState.objects.select_for_update()
        .filter(user=user)
        .first()
    )
    if reward_state is None or reward_state.free_predictions <= 0:
        raise ValidationError("У вас нет доступных бесплатных прогнозов.")

    reward_state.free_predictions -= 1
    reward_state.save(update_fields=("free_predictions", "updated_at"))
    return reward_state


def _serialize_draft_coupon(coupon: PredictionCoupon) -> dict:
    predictions = list(coupon.predictions.all())
    stake = coupon.total_stake if coupon.total_stake and coupon.total_stake > 0 else None

    return {
        "id": coupon.id,
        "stake": _decimal_string(stake) if stake is not None else "",
        "confidence": coupon.confidence,
        "audience": coupon.audience,
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


def _latest_predictions():
    return (
        Prediction.objects.filter(
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            coupon__audience=PredictionCoupon.Audience.FREE,
        )
        .select_related("coupon__author", "match__league__country", "match__home_team", "match__away_team")
        .order_by("-coupon__published_at", "-coupon__created_at", "-created_at")[:6]
    )


def _refresh_provider_predictions(match: Match) -> None:
    try:
        MatchSyncService().sync_match_predictions(match)
    except (NeurokeffProviderError, ValueError) as exc:
        logger.info(
            "Provider predictions refresh skipped for match %s: %s",
            match.external_id,
            exc,
        )


def _provider_prediction_panel(match: Match) -> dict | None:
    payload = match.provider_predictions if isinstance(match.provider_predictions, dict) else {}
    predictions = payload.get("predictions")
    if not isinstance(predictions, dict) or not predictions.get("available"):
        return None

    snapshot = predictions.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    percent = snapshot.get("percent")
    if not isinstance(percent, dict):
        percent = {}

    outcomes = [
        {
            "key": "home",
            "label": "1",
            "name": match.home_team_name or "Хозяева",
            "percent": _percent_value(percent.get("home")),
        },
        {
            "key": "draw",
            "label": "X",
            "name": "Ничья",
            "percent": _percent_value(percent.get("draw")),
        },
        {
            "key": "away",
            "label": "2",
            "name": match.away_team_name or "Гости",
            "percent": _percent_value(percent.get("away")),
        },
    ]
    outcomes = [item for item in outcomes if item["percent"] is not None]
    if not outcomes:
        return None

    winner = snapshot.get("winner") if isinstance(snapshot.get("winner"), dict) else {}
    winner_side = str(winner.get("side") or "")
    for item in outcomes:
        item["is_winner"] = item["key"] == winner_side

    metrics = [
        metric
        for metric in predictions.get("metrics") or []
        if isinstance(metric, dict) and _percent_value(metric.get("value")) is not None
    ][:8]
    for metric in metrics:
        metric["value"] = _percent_value(metric.get("value"))
        metric["label"] = _provider_metric_label(metric)

    return {
        "outcomes": outcomes,
        "advice": snapshot.get("advice_ru") or snapshot.get("advice") or "",
        "updated_at": match.provider_predictions_updated_at,
        "metrics": metrics,
    }


def _percent_value(value) -> int | None:
    try:
        percent = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(percent, 100))


def _provider_metric_label(metric: dict) -> str:
    labels = {
        "att": "Атака",
        "def": "Защита",
        "form": "Форма",
        "goals": "Голы",
        "h2h": "Очные",
        "poisson_distribution": "Пуассон",
        "total": "Итог",
    }
    subject_labels = {
        "home": "1",
        "draw": "X",
        "away": "2",
    }
    code = str(metric.get("code") or "")
    subject = str(metric.get("subject") or "")
    label = labels.get(code, human_market_label(code))
    subject_label = subject_labels.get(subject)
    return f"{label} {subject_label}" if subject_label else label


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

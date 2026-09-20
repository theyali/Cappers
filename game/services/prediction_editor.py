from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from game.models import PredictionCoupon, PredictionCoverImage


MAX_RICH_PREDICTION_ITEMS = 15


def can_use_rich_prediction_fields(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_analyst", False)
        and getattr(user, "is_vip", False)
    )


def build_prediction_editor_context(request, coupon=None) -> dict:
    _ensure_editor_access(request.user)
    if coupon is not None:
        _ensure_coupon_access(request.user, coupon)

    can_use_rich_fields = can_use_rich_prediction_fields(request.user)
    predictions = _coupon_predictions(coupon) if coupon is not None else []
    has_coupon_positions = 1 <= len(predictions) <= MAX_RICH_PREDICTION_ITEMS
    available_covers = []
    if can_use_rich_fields:
        available_covers = list(
            PredictionCoverImage.objects.filter(
                is_active=True,
                placement=PredictionCoverImage.Placement.GRID,
            )
            .select_related("sport")
            .order_by("cover_type", "sport__name_ru", "sport__name", "id")
        )

    preview_prediction = _build_preview_prediction(coupon)
    form_initial = {}
    if coupon is not None:
        form_initial = {
            "total_stake": coupon.total_stake,
            "confidence": coupon.confidence,
            "is_paid": preview_prediction["is_paid"],
            "headline": coupon.headline,
            "description": coupon.description,
            "cover_image": coupon.cover_image_id,
            "tags": ", ".join(coupon.tags or []),
            "published_status": coupon.published_status,
        }

    return {
        "coupon": coupon,
        "can_use_rich_fields": can_use_rich_fields,
        "vip_upgrade_url": reverse("cabinet:profile"),
        "vip_locked_label": "Доступно VIP-капперам",
        "available_covers": available_covers,
        "preview_prediction": preview_prediction,
        "form_initial": form_initial,
        "submit_label": "Сохранить изменения" if coupon else "Создать прогноз",
        "is_editing": coupon is not None and coupon.prediction_format == PredictionCoupon.PredictionFormat.RICH,
        "has_coupon_positions": has_coupon_positions,
        "predictions": predictions,
        "coupon_total_coefficient": _coupon_total_coefficient(predictions),
        "rich_prediction_max_items": MAX_RICH_PREDICTION_ITEMS,
        "selected_cover_id": str(coupon.cover_image_id) if coupon and coupon.cover_image_id else "",
    }


@transaction.atomic
def create_rich_prediction(user, data, files, *, source_coupon=None) -> PredictionCoupon:
    _ensure_editor_access(user)
    if source_coupon is None or not getattr(source_coupon, "pk", None):
        raise ValidationError(
            "Сначала добавьте матчи в купон, затем откройте расширенный прогноз."
        )

    coupon = PredictionCoupon.objects.select_for_update().get(
        pk=source_coupon.pk,
        author=user,
        published_status=PredictionCoupon.PublishedStatus.DRAFT,
        prediction_format=PredictionCoupon.PredictionFormat.QUICK,
    )
    return _save_rich_prediction(user, coupon, data, files, is_new=True)


@transaction.atomic
def update_rich_prediction(user, coupon, data, files) -> PredictionCoupon:
    _ensure_editor_access(user)
    _ensure_coupon_edit_access(user, coupon)

    coupon = PredictionCoupon.objects.select_for_update().get(pk=coupon.pk)
    _ensure_coupon_edit_access(user, coupon)
    return _save_rich_prediction(user, coupon, data, files, is_new=False)


def _save_rich_prediction(user, coupon, data, files, *, is_new: bool) -> PredictionCoupon:
    can_use_rich_fields = can_use_rich_prediction_fields(user)
    files = files or {}
    _delete_removed_predictions(coupon, data.get("remove_prediction_ids"))
    predictions = _coupon_predictions(coupon)
    if not predictions:
        raise ValidationError(
            "Сначала добавьте матчи в купон, затем откройте расширенный прогноз."
        )
    if len(predictions) > MAX_RICH_PREDICTION_ITEMS:
        raise ValidationError(
            f"В расширенном прогнозе может быть максимум {MAX_RICH_PREDICTION_ITEMS} игр."
        )
    stale_matches = [
        prediction.match for prediction in predictions
        if prediction.match.sync_scope != prediction.match.SyncScope.PREMATCH
    ]
    if stale_matches:
        match = stale_matches[0]
        raise ValidationError(
            f"Матч «{match.home_team_name} — {match.away_team_name}» уже начался или завершен."
        )

    headline = _text_value(
        data.get("headline", "") if is_new else data.get("headline", coupon.headline)
    )
    if len(headline) > 160:
        raise ValidationError({"headline": "Заголовок должен быть не длиннее 160 символов."})

    if can_use_rich_fields:
        description = _text_value(
            data.get("description", "") if is_new else data.get("description", coupon.description)
        )
    else:
        description = "" if is_new else coupon.description

    audience = _resolve_audience(data, coupon, is_new=is_new)
    if audience == PredictionCoupon.Audience.PAID and not can_use_rich_fields:
        raise ValidationError({"is_paid": "Платные прогнозы доступны VIP-капперам."})
    if audience == PredictionCoupon.Audience.PAID and not description:
        raise ValidationError(
            {"description": "Для платного прогноза обязательно добавьте описание."}
        )

    tags = _normalize_tags(data.get("tags", [] if is_new else coupon.tags))
    status = _resolve_published_status(data, coupon, is_new=is_new)
    total_stake = _resolve_total_stake(data, coupon)
    confidence = _resolve_confidence(data, coupon)
    total_coefficient = _coupon_total_coefficient(predictions)

    coupon.prediction_format = PredictionCoupon.PredictionFormat.RICH
    coupon.headline = headline
    coupon.description = description
    coupon.tags = tags
    coupon.audience = audience
    coupon.total_stake = total_stake
    coupon.confidence = confidence
    coupon.possible_payout = total_stake * total_coefficient
    coupon.published_status = status
    coupon.published_at = (
        coupon.published_at or timezone.now()
        if status == PredictionCoupon.PublishedStatus.PUBLISHED
        else None
    )

    if can_use_rich_fields:
        if "cover_image" in data:
            coupon.cover_image = _resolve_cover_image(data.get("cover_image"))
        custom_cover_image = files.get("custom_cover_image") or data.get("custom_cover_image")
        if custom_cover_image:
            coupon.custom_cover_image = custom_cover_image
        elif _as_bool(data.get("clear_custom_cover_image")):
            coupon.custom_cover_image = ""

    coupon.save()

    coupon.sync_coupon_type()
    if not coupon.custom_cover_image and not coupon.cover_image_id:
        coupon.assign_cover_image()
    return coupon


def _ensure_editor_access(user) -> None:
    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Войдите, чтобы создавать прогнозы.")
    if not getattr(user, "is_analyst", False):
        raise PermissionDenied("Расширенные прогнозы доступны только капперам.")


def _ensure_coupon_edit_access(user, coupon: PredictionCoupon) -> None:
    if coupon is None or not getattr(coupon, "pk", None):
        raise ValidationError("Прогноз не найден.")
    if coupon.author_id != getattr(user, "pk", None):
        raise PermissionDenied("Нельзя редактировать чужой прогноз.")
    if coupon.prediction_format != PredictionCoupon.PredictionFormat.RICH:
        raise ValidationError("Быстрый купон нельзя редактировать в rich-редакторе.")


def _ensure_coupon_access(user, coupon: PredictionCoupon) -> None:
    if coupon is None or not getattr(coupon, "pk", None):
        raise ValidationError("Прогноз не найден.")
    if coupon.author_id != getattr(user, "pk", None):
        raise PermissionDenied("Нельзя редактировать чужой прогноз.")


def _resolve_audience(data, coupon: PredictionCoupon, *, is_new: bool) -> str:
    if "is_paid" in data:
        return (
            PredictionCoupon.Audience.PAID
            if _as_bool(data.get("is_paid"))
            else PredictionCoupon.Audience.FREE
        )

    if "audience" in data:
        audience = _text_value(data.get("audience")).lower()
        valid = {value for value, _label in PredictionCoupon.Audience.choices}
        if audience not in valid:
            raise ValidationError({"audience": "Выберите тип доступа к прогнозу."})
        return audience

    return PredictionCoupon.Audience.FREE if is_new else coupon.audience


def _resolve_cover_image(value) -> PredictionCoverImage | None:
    if value in (None, ""):
        return None

    cover_id = value.pk if isinstance(value, PredictionCoverImage) else value
    try:
        cover_id = int(cover_id)
    except (TypeError, ValueError):
        raise ValidationError({"cover_image": "Выберите корректную обложку."})

    cover = PredictionCoverImage.objects.filter(
        pk=cover_id,
        is_active=True,
        placement=PredictionCoverImage.Placement.GRID,
    ).first()
    if cover is None:
        raise ValidationError({"cover_image": "Эта обложка недоступна."})
    return cover


def _delete_removed_predictions(coupon: PredictionCoupon, raw_ids) -> None:
    if not raw_ids:
        return
    ids = raw_ids
    if isinstance(raw_ids, str):
        ids = [item for item in raw_ids.replace(" ", "").split(",") if item]
    ids = [int(prediction_id) for prediction_id in ids if str(prediction_id).isdigit()]
    if ids:
        coupon.predictions.filter(id__in=ids).delete()


def _resolve_total_stake(data, coupon: PredictionCoupon) -> Decimal:
    value = data.get("total_stake", coupon.total_stake)
    try:
        stake = Decimal(str(value))
    except Exception as exc:
        raise ValidationError({"total_stake": "Укажите корректную сумму."}) from exc
    if stake < Decimal("100"):
        raise ValidationError({"total_stake": "Минимальная сумма — 100 коинов."})
    if stake > Decimal("1000000"):
        raise ValidationError({"total_stake": "Максимальная сумма — 1 000 000 коинов."})
    return stake


def _resolve_confidence(data, coupon: PredictionCoupon) -> int:
    value = data.get("confidence", coupon.confidence)
    try:
        confidence = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"confidence": "Укажите уверенность от 0 до 100%."}) from exc
    if confidence < 0 or confidence > 100:
        raise ValidationError({"confidence": "Укажите уверенность от 0 до 100%."})
    return confidence


def _resolve_published_status(data, coupon: PredictionCoupon, *, is_new: bool) -> str:
    if data.get("published_status") not in (None, ""):
        status = _text_value(data.get("published_status")).lower()
    elif "publish" in data:
        status = (
            PredictionCoupon.PublishedStatus.PUBLISHED
            if _as_bool(data.get("publish"))
            else PredictionCoupon.PublishedStatus.DRAFT
        )
    else:
        return PredictionCoupon.PublishedStatus.DRAFT if is_new else coupon.published_status

    valid = {value for value, _label in PredictionCoupon.PublishedStatus.choices}
    if status not in valid:
        raise ValidationError({"published_status": "Неизвестный статус прогноза."})
    return status


def _normalize_tags(value) -> list[str]:
    if isinstance(value, str):
        raw_tags = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_tags = value
    else:
        raw_tags = []

    tags = []
    seen = set()
    for raw_tag in raw_tags:
        tag = _text_value(raw_tag).lstrip("#")
        normalized = tag.casefold()
        if not tag or normalized in seen:
            continue
        seen.add(normalized)
        tags.append(tag)
        if len(tags) == 7:
            break
    return tags


def _build_preview_prediction(coupon: PredictionCoupon | None) -> dict:
    if coupon is None:
        return {
            "coupon": None,
            "match": None,
            "prediction_text": "",
            "coefficient": None,
            "headline": "",
            "description": "",
            "tags": [],
            "cover_url": "",
            "is_paid": False,
        }

    prediction = coupon.predictions.select_related(
        "match",
        "match__sport",
        "match__league",
        "match__home_team",
        "match__away_team",
    ).order_by("id").first()

    cover = coupon.get_display_cover_image()
    cover_url = cover.url if cover else ""

    return {
        "coupon": coupon,
        "match": prediction.match if prediction is not None else None,
        "prediction_text": prediction.selection if prediction is not None else "",
        "coefficient": prediction.coefficient if prediction is not None else None,
        "headline": coupon.headline,
        "description": coupon.description,
        "tags": coupon.tags,
        "cover_url": cover_url,
        "is_paid": coupon.audience == PredictionCoupon.Audience.PAID,
    }


def _coupon_predictions(coupon: PredictionCoupon | None) -> list:
    if coupon is None:
        return []
    return list(
        coupon.predictions.select_related(
            "match",
            "match__sport",
            "match__league",
            "match__league__country",
            "match__home_team",
            "match__away_team",
        ).order_by("id")
    )


def _coupon_total_coefficient(predictions: list) -> Decimal:
    total = Decimal("1")
    if not predictions:
        return Decimal("0")
    for prediction in predictions:
        total *= prediction.coefficient
    return total


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "paid"}


def _text_value(value) -> str:
    return str(value or "").strip()

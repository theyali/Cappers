from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from game.models import Match, Prediction, PredictionCoupon, PredictionCoverImage


def can_use_rich_prediction_fields(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_analyst", False)
        and getattr(user, "is_vip", False)
    )


def build_prediction_editor_context(request, coupon=None) -> dict:
    _ensure_editor_access(request.user)
    if coupon is not None:
        _ensure_coupon_edit_access(request.user, coupon)

    can_use_rich_fields = can_use_rich_prediction_fields(request.user)
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
            "match": preview_prediction["match"],
            "coupon_type": coupon.coupon_type,
            "is_paid": preview_prediction["is_paid"],
            "coefficient": preview_prediction["coefficient"],
            "prediction_text": preview_prediction["prediction_text"],
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
        "is_editing": coupon is not None,
    }


@transaction.atomic
def create_rich_prediction(user, data, files) -> PredictionCoupon:
    _ensure_editor_access(user)
    coupon = PredictionCoupon(
        author=user,
        prediction_format=PredictionCoupon.PredictionFormat.RICH,
        total_stake=Decimal("0"),
        possible_payout=Decimal("0"),
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

    match = _resolve_match(data, coupon, is_new=is_new)
    coefficient = _resolve_coefficient(data, coupon, is_new=is_new)
    prediction_text = _resolve_prediction_text(data, coupon, is_new=is_new)
    tags = _normalize_tags(data.get("tags", [] if is_new else coupon.tags))
    status = _resolve_published_status(data, coupon, is_new=is_new)

    coupon.prediction_format = PredictionCoupon.PredictionFormat.RICH
    coupon.headline = headline
    coupon.description = description
    coupon.tags = tags
    coupon.audience = audience
    coupon.published_status = status
    coupon.total_stake = Decimal("0")
    coupon.possible_payout = Decimal("0")
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

    prediction = coupon.predictions.order_by("id").first()
    if prediction is None:
        prediction = Prediction(coupon=coupon)

    prediction.match = match
    prediction.market = _text_value(data.get("market") or "Прогноз")[:80]
    prediction.selection = prediction_text
    prediction.coefficient = coefficient
    # Rich predictions do not use the quick-coupon virtual stake flow.
    prediction.stake = Decimal("0")
    prediction.save()

    coupon.sync_coupon_type()
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


def _resolve_match(data, coupon: PredictionCoupon, *, is_new: bool) -> Match:
    value = data.get("match")
    if value in (None, "") and not is_new:
        prediction = coupon.predictions.select_related("match").order_by("id").first()
        value = prediction.match if prediction is not None else None

    if isinstance(value, Match):
        match = value
    else:
        try:
            match_id = int(value)
        except (TypeError, ValueError):
            raise ValidationError({"match": "Выберите матч."})
        match = Match.objects.filter(pk=match_id).first()

    if match is None:
        raise ValidationError({"match": "Матч не найден."})
    if match.sync_scope != Match.SyncScope.PREMATCH:
        raise ValidationError({"match": "Прогноз можно создать только на предстоящий матч."})
    return match


def _resolve_coefficient(data, coupon: PredictionCoupon, *, is_new: bool) -> Decimal:
    value = data.get("coefficient")
    if value in (None, "") and not is_new:
        prediction = coupon.predictions.order_by("id").first()
        value = prediction.coefficient if prediction is not None else None

    try:
        coefficient = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"coefficient": "Укажите корректный коэффициент."})

    if coefficient <= 0:
        raise ValidationError({"coefficient": "Коэффициент должен быть больше нуля."})
    return coefficient


def _resolve_prediction_text(data, coupon: PredictionCoupon, *, is_new: bool) -> str:
    value = data.get("prediction_text")
    if value in (None, "") and "selection" in data:
        value = data.get("selection")
    if value in (None, "") and not is_new:
        prediction = coupon.predictions.order_by("id").first()
        value = prediction.selection if prediction is not None else ""

    prediction_text = _text_value(value)
    if not prediction_text:
        raise ValidationError({"prediction_text": "Укажите прогноз."})
    if len(prediction_text) > 120:
        raise ValidationError({"prediction_text": "Прогноз должен быть не длиннее 120 символов."})
    return prediction_text


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


def _resolve_published_status(data, coupon: PredictionCoupon, *, is_new: bool) -> str:
    if "published_status" in data:
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

    cover_url = ""
    if coupon.custom_cover_image:
        cover_url = coupon.custom_cover_image.url
    elif coupon.cover_image_id and coupon.cover_image and coupon.cover_image.image:
        cover_url = coupon.cover_image.image.url

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


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "paid"}


def _text_value(value) -> str:
    return str(value or "").strip()

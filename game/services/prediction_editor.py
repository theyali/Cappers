from decimal import Decimal
from types import SimpleNamespace

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from front.popular_matches import build_popular_matches
from cabinet.paid_predictions import profile_paid_predictions_enabled, profile_single_coupon_sales_enabled
from game.services.coupon_draft import CouponDraftConflict, check_draft_revision, serialize_draft_coupon
from game.cover_images import prediction_editor_covers
from game.models import Match, Prediction, PredictionCoupon, PredictionCoverImage
from game.services.bet_options import bet_option_key, build_match_winner_odds
from game.services.match_timing import match_timing_payload
from game.services.coupon_validation import (
    CouponMatchVerificationError,
    CouponOddsChangedError,
    coupon_total_coefficient,
    parse_stake,
    resolve_coupon_items,
    validate_match_timing,
    verify_matches_for_coupon,
)
from wallets.services import charge_prediction_stake


MAX_RICH_PREDICTION_ITEMS = 15
MIN_PAID_DESCRIPTION_LENGTH = 300


def can_use_rich_prediction_fields(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_analyst", False)
        and getattr(user, "is_vip", False)
    )


def validate_paid_prediction_settings(user, coupon=None):
    existing_paid = coupon is not None and _is_published(coupon) and coupon.audience == PredictionCoupon.Audience.PAID
    if not existing_paid and not profile_paid_predictions_enabled(user):
        raise ValidationError({"is_paid": "Включите платные прогнозы и настройте подписку или разовую покупку в профиле."})


def validate_paid_prediction_content(headline, description):
    errors = {}
    if not (headline or "").strip():
        errors["headline"] = "Для платного прогноза обязательно укажите заголовок."
    if len((description or "").strip()) < MIN_PAID_DESCRIPTION_LENGTH:
        errors["description"] = f"Для платного прогноза добавьте описание от {MIN_PAID_DESCRIPTION_LENGTH} символов."
    if errors:
        raise ValidationError(errors)


def build_editor_positions(coupon):
    predictions = _coupon_predictions(coupon) if coupon is not None else []
    moment = timezone.now()
    prediction_timing = {}
    for prediction in predictions:
        timing = match_timing_payload(prediction.match, now=moment)
        prediction.editor_prediction_closed = not timing["prediction_open"] and not _is_published(coupon)
        prediction.editor_timing_message = (
            "Время начала не указано — публикация недоступна."
            if not timing["starts_at"] else "Матч уже начался или завершён — публикация недоступна."
        )
        if not _is_published(coupon):
            prediction_timing[str(prediction.match_id)] = timing
    coupon_timing_blocked = any(item.editor_prediction_closed for item in predictions)
    return predictions, prediction_timing, coupon_timing_blocked


def build_prediction_editor_context(request, coupon=None) -> dict:
    _ensure_editor_access(request.user)
    if coupon is not None:
        _ensure_coupon_access(request.user, coupon)

    can_use_rich_fields = can_use_rich_prediction_fields(request.user)
    predictions, prediction_timing, coupon_timing_blocked = build_editor_positions(coupon)
    has_coupon_positions = 1 <= len(predictions) <= MAX_RICH_PREDICTION_ITEMS
    available_covers = []
    if can_use_rich_fields:
        available_covers = list(prediction_editor_covers())

    preview_prediction = _build_preview_prediction(coupon)
    suggested_matches = []
    if not has_coupon_positions:
        suggested_matches = _build_suggested_matches()
    form_initial = {}
    if coupon is not None:
        form_initial = {
            "draft_revision": coupon.updated_at.isoformat(),
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
        "draft_coupon": serialize_draft_coupon(coupon) if coupon and coupon.prediction_format == PredictionCoupon.PredictionFormat.QUICK else None,
        "can_publish_paid": can_use_rich_fields and profile_paid_predictions_enabled(request.user),
        "single_purchase_price": (
            coupon.single_purchase_price if coupon is not None and _is_published(coupon)
            else request.user.analyst_profile.single_coupon_price if profile_single_coupon_sales_enabled(request.user)
            else None
        ),
        "paid_settings_url": reverse("cabinet:profile") + "?tab=settings#paid-predictions-settings",
        "shared_coupon_draft": coupon is None or coupon.prediction_format == PredictionCoupon.PredictionFormat.QUICK,
        "rich_prediction_timing": prediction_timing,
        "coupon_timing_blocked": coupon_timing_blocked,
        "paid_description_min_length": MIN_PAID_DESCRIPTION_LENGTH,
        "can_use_rich_fields": can_use_rich_fields,
        "vip_upgrade_url": reverse("cabinet:profile"),
        "vip_locked_label": "Доступно VIP-капперам",
        "available_covers": available_covers,
        "preview_prediction": preview_prediction,
        "form_initial": form_initial,
        "submit_label": "Сохранить изменения" if coupon else "Создать прогноз",
        "is_editing": coupon is not None and coupon.prediction_format == PredictionCoupon.PredictionFormat.RICH,
        "is_published": _is_published(coupon),
        "has_coupon_positions": has_coupon_positions,
        "predictions": predictions,
        "coupon_total_coefficient": _coupon_total_coefficient(predictions),
        "rich_prediction_max_items": MAX_RICH_PREDICTION_ITEMS,
        "selected_cover_id": str(coupon.cover_image_id) if coupon and coupon.cover_image_id else "",
        "suggested_matches": suggested_matches,
        "predictable_matches_url": (
            reverse(
                "game:match_list_filtered",
                kwargs={
                    "sport": "all",
                    "scope": "all",
                    "selected_date": timezone.localdate().isoformat(),
                },
            )
            + "?match_filter=predictable"
        ),
    }


def _build_suggested_matches() -> list:
    """Use the same popular, future, odds-backed matches as the public match list."""
    popular_matches = build_popular_matches(limit=12)

    matches_by_id = {
        match.pk: match
        for match in Match.objects.filter(pk__in=[item.id for item in popular_matches])
        .select_related("sport", "league", "odds")
    }
    suggestions = []
    used_ids = set()
    for item in popular_matches:
        match = matches_by_id.get(item.id)
        if match is None:
            continue
        winner_odds = build_match_winner_odds(match)
        if not winner_odds["has_any"]:
            continue
        item.winner_odds = winner_odds
        item.primary_odd = (
            winner_odds["home"] or winner_odds["away"] or winner_odds["draw"]
        )
        item.sport_image = match.sport.image_url if match.sport else ""
        suggestions.append(item)
        used_ids.add(match.pk)
        if len(suggestions) == 3:
            break

    if len(suggestions) < 3:
        fallback_matches = (
            Match.objects.filter(
                sync_scope=Match.SyncScope.PREMATCH,
                starts_at__gte=timezone.now(),
            )
            .exclude(pk__in=used_ids)
            .select_related("sport", "league", "odds")
            .order_by("starts_at", "id")[:200]
        )
        for match in fallback_matches:
            winner_odds = build_match_winner_odds(match)
            if not winner_odds["has_any"]:
                continue
            local_start = timezone.localtime(match.starts_at)
            suggestions.append(
                SimpleNamespace(
                    id=match.pk,
                    url=match.get_absolute_url(),
                    starts_at=local_start,
                    date_label=(
                        "сегодня"
                        if local_start.date() == timezone.localdate()
                        else local_start.strftime("%d.%m")
                    ),
                    league_name=match.league_name,
                    home_name=match.home_team_name,
                    away_name=match.away_team_name,
                    sport_image=match.sport.image_url if match.sport else "",
                    winner_odds=winner_odds,
                    primary_odd=(
                        winner_odds["home"] or winner_odds["away"] or winner_odds["draw"]
                    ),
                )
            )
            if len(suggestions) == 3:
                break
    return suggestions


def create_rich_prediction(user, data, files, *, source_coupon=None) -> PredictionCoupon:
    _ensure_editor_access(user)
    if source_coupon is None or not getattr(source_coupon, "pk", None):
        raise ValidationError(
            "Сначала добавьте матчи в купон, затем откройте расширенный прогноз."
        )

    draft_coupons = PredictionCoupon.objects.filter(
        pk=source_coupon.pk,
        author=user,
        published_status=PredictionCoupon.PublishedStatus.DRAFT,
        prediction_format=PredictionCoupon.PredictionFormat.QUICK,
    )
    if _resolve_published_status(data, source_coupon, is_new=True) == PredictionCoupon.PublishedStatus.PUBLISHED:
        current = draft_coupons.first()
        if current is None:
            raise ValidationError("Купон уже опубликован или очищен. Обновите страницу.")
        _confirm_coupon_for_publish(current, data)

    with transaction.atomic():
        coupon = draft_coupons.select_for_update().first()
        if coupon is None:
            raise ValidationError("Купон уже опубликован или очищен. Обновите страницу.")
        if data.get("draft_revision"):
            try:
                check_draft_revision(coupon, data["draft_revision"])
            except CouponDraftConflict:
                raise ValidationError("Состав купона изменён в другой вкладке. Проверьте матчи и повторите публикацию.")
        return _save_rich_prediction(user, coupon, data, files, is_new=True)


def update_rich_prediction(user, coupon, data, files) -> PredictionCoupon:
    _ensure_editor_access(user)
    _ensure_coupon_edit_access(user, coupon)
    if (
        not _is_published(coupon)
        and _resolve_published_status(data, coupon, is_new=False) == PredictionCoupon.PublishedStatus.PUBLISHED
    ):
        _confirm_coupon_for_publish(coupon, data)

    with transaction.atomic():
        coupon = PredictionCoupon.objects.select_for_update().get(pk=coupon.pk)
        _ensure_coupon_edit_access(user, coupon)
        return _save_rich_prediction(user, coupon, data, files, is_new=False)


@transaction.atomic
def remove_draft_prediction(user, coupon_id, prediction_id) -> dict:
    _ensure_editor_access(user)
    coupon = PredictionCoupon.objects.select_for_update().filter(pk=coupon_id).first()
    if coupon is None:
        raise ValidationError("Купон уже опубликован или очищен. Обновите страницу.")
    _ensure_coupon_access(user, coupon)
    if coupon.published_status != PredictionCoupon.PublishedStatus.DRAFT:
        raise ValidationError("Позиции опубликованного прогноза изменить нельзя.")
    predictions = list(coupon.predictions.order_by("id"))
    target = next((item for item in predictions if item.pk == prediction_id), None)
    if target is not None:
        if len(predictions) <= 1:
            raise ValidationError("В купоне должна остаться минимум одна позиция.")
        target.delete()
        predictions = [item for item in predictions if item is not target]
    coefficient = _coupon_total_coefficient(predictions)
    coupon.possible_payout = coupon.total_stake * coefficient
    coupon.save(update_fields=["possible_payout", "updated_at"])
    return {"positions_count": len(predictions), "total_coefficient": str(coefficient)}


def _confirm_coupon_for_publish(coupon: PredictionCoupon, data) -> None:
    """Run the quick-coupon publish checks before a rich coupon is saved.

    This runs outside the save transaction on purpose: when the line has moved,
    the current coefficients are stored in the draft so the author sees them,
    and publishing stops until the author confirms the new prices.
    """
    removed_ids = set(_prediction_ids(data.get("remove_prediction_ids")))
    predictions = [
        prediction for prediction in _coupon_predictions(coupon)
        if prediction.pk not in removed_ids
    ]
    if not predictions:
        return

    matches = {prediction.match_id: prediction.match for prediction in predictions}
    validate_match_timing(matches.values())
    try:
        verify_matches_for_coupon(list(matches.values()))
    except CouponMatchVerificationError as exc:
        raise ValidationError(str(exc)) from exc

    items = [
        {
            "match_id": prediction.match_id,
            "market": prediction.market,
            "selection": prediction.selection,
            "outcome_code": prediction.outcome_code,
            "coefficient": prediction.coefficient,
        }
        for prediction in predictions
    ]
    try:
        resolved_items = resolve_coupon_items(items, matches, accept_changed_odds=False)
    except CouponOddsChangedError as exc:
        _store_current_odds(coupon, predictions, exc.changes)
        raise ValidationError(_odds_changed_message(matches, exc.changes)) from exc

    # Drafts saved before outcome codes existed get them here, so they are settled by code.
    for prediction, item in zip(predictions, resolved_items):
        if not prediction.outcome_code and item["outcome_code"]:
            Prediction.objects.filter(pk=prediction.pk).update(outcome_code=item["outcome_code"])


def _store_current_odds(coupon: PredictionCoupon, predictions: list, changes: list[dict]) -> None:
    by_code = {
        (change["match_id"], change["market"], change["outcome_code"]): Decimal(change["coefficient"])
        for change in changes
    }
    by_text = {
        (change["match_id"], *bet_option_key(change["market"], change["selection"])): Decimal(change["coefficient"])
        for change in changes
    }
    with transaction.atomic():
        for prediction in predictions:
            coefficient = by_code.get(
                (prediction.match_id, prediction.market, prediction.outcome_code)
            ) or by_text.get(
                (prediction.match_id, *bet_option_key(prediction.market, prediction.selection))
            )
            if coefficient is None:
                continue
            prediction.coefficient = coefficient
            Prediction.objects.filter(pk=prediction.pk).update(coefficient=coefficient)
        PredictionCoupon.objects.filter(pk=coupon.pk).update(
            possible_payout=coupon.total_stake * coupon_total_coefficient(
                [{"coefficient": prediction.coefficient} for prediction in predictions]
            ),
            updated_at=timezone.now(),
        )


def _odds_changed_message(matches: dict, changes: list[dict]) -> str:
    parts = []
    for change in changes:
        match = matches.get(change["match_id"])
        title = (
            f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}"
            if match is not None
            else "матч"
        )
        previous = change["previous"] or "—"
        parts.append(f"{title}: {previous} → {change['coefficient']}")
    return (
        "Коэффициенты изменились: "
        + "; ".join(parts)
        + ". Купон обновлён, проверьте его и опубликуйте прогноз ещё раз."
    )


def _save_rich_prediction(user, coupon, data, files, *, is_new: bool) -> PredictionCoupon:
    can_use_rich_fields = can_use_rich_prediction_fields(user)
    files = files or {}
    was_published = _is_published(coupon)
    removed_ids = _prediction_ids(data.get("remove_prediction_ids"))
    if was_published and removed_ids:
        raise ValidationError("Позиции опубликованного прогноза изменить нельзя.")
    if removed_ids:
        coupon.predictions.filter(id__in=removed_ids).delete()
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
    if was_published and audience != coupon.audience:
        raise ValidationError({"is_paid": "Тип доступа опубликованного прогноза изменить нельзя."})
    if audience == PredictionCoupon.Audience.PAID and not can_use_rich_fields:
        raise ValidationError({"is_paid": "Платные прогнозы доступны VIP-капперам."})
    if audience == PredictionCoupon.Audience.PAID:
        validate_paid_prediction_settings(user, coupon)
        validate_paid_prediction_content(headline, description)

    tags = _normalize_tags(data.get("tags", [] if is_new else coupon.tags))
    status = _resolve_published_status(data, coupon, is_new=is_new)
    if was_published and status != PredictionCoupon.PublishedStatus.PUBLISHED:
        raise ValidationError("Опубликованный прогноз нельзя вернуть в черновик.")
    total_stake = _resolve_total_stake(data, coupon)
    if was_published and total_stake != coupon.total_stake:
        raise ValidationError({"total_stake": "Сумму опубликованного прогноза изменить нельзя."})
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

    if status == PredictionCoupon.PublishedStatus.PUBLISHED and not was_published:
        coupon.single_purchase_enabled = (audience == PredictionCoupon.Audience.PAID
                                          and profile_single_coupon_sales_enabled(user))
        coupon.single_purchase_price = user.analyst_profile.single_coupon_price if coupon.single_purchase_enabled else None
    elif audience != PredictionCoupon.Audience.PAID:
        coupon.single_purchase_enabled = False
        coupon.single_purchase_price = None
    coupon.save()
    if status == PredictionCoupon.PublishedStatus.PUBLISHED and not was_published:
        charge_prediction_stake(user, coupon, total_stake)

    coupon.sync_coupon_type()
    if not coupon.custom_cover_image and not coupon.cover_image_id:
        coupon.assign_cover_image()
    return coupon


def _ensure_editor_access(user) -> None:
    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Войдите, чтобы создавать прогнозы.")
    if not getattr(user, "is_analyst", False):
        raise PermissionDenied("Расширенные прогнозы доступны только капперам.")
    if not getattr(user, "is_vip", False):
        raise PermissionDenied("Расширенные прогнозы доступны только VIP-капперам.")


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

    cover = prediction_editor_covers().filter(pk=cover_id).first()
    if cover is None:
        raise ValidationError({"cover_image": "Эта обложка недоступна."})
    return cover


def _prediction_ids(raw_ids) -> list[int]:
    if not raw_ids:
        return []
    ids = raw_ids
    if isinstance(raw_ids, str):
        ids = [item for item in raw_ids.replace(" ", "").split(",") if item]
    return [int(prediction_id) for prediction_id in ids if str(prediction_id).isdigit()]


def _resolve_total_stake(data, coupon: PredictionCoupon) -> Decimal:
    try:
        return parse_stake(data.get("total_stake", coupon.total_stake), required=True)
    except ValidationError as exc:
        raise ValidationError({"total_stake": exc.messages}) from exc


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

    # Canceling a published coupon refunds stakes and goes through cancel_published_coupon().
    valid = {PredictionCoupon.PublishedStatus.DRAFT, PredictionCoupon.PublishedStatus.PUBLISHED}
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


def _is_published(coupon: PredictionCoupon | None) -> bool:
    return coupon is not None and coupon.published_status == PredictionCoupon.PublishedStatus.PUBLISHED


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "paid"}


def _text_value(value) -> str:
    return str(value or "").strip()

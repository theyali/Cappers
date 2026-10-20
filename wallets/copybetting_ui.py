"""Read-only contexts for choosing a capper and previewing copy settings."""
from types import SimpleNamespace
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Count, Exists, IntegerField, OuterRef, Prefetch, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.urls import reverse

from cabinet.models import AnalystFollow, User
from cabinet.paid_predictions import user_has_paid_prediction_subscription
from cabinet.services.copybetting import coins
from front.prediction_metrics import annotate_author_roi
from game.models import Prediction, PredictionCoupon
from game.services.coupon_validation import PREDICTION_STAKE_MIN_COINS
from .models import CopyBettingSubscription, CopyBettingBlock
from .services import _copy_stake, _copybetting_allows_coupon, _coupon_is_tournament, _coupon_total_coefficient

SEARCH_PAGE_SIZE = 6


def capper_queryset():
    # Independent counts avoid multiplying every coupon by every follower.
    coupons = PredictionCoupon.objects.filter(author_id=OuterRef("pk"), published_status="published").order_by().values("author_id")
    followers = AnalystFollow.objects.filter(analyst_id=OuterRef("pk")).order_by().values("analyst_id")
    users = User.objects.filter(role=User.Role.ANALYST, is_active=True).select_related("analyst_profile").annotate(
        ui_coupons=Coalesce(Subquery(coupons.annotate(total=Count("pk")).values("total"), output_field=IntegerField()), Value(0)),
        ui_wins=Coalesce(Subquery(coupons.filter(state_status="win").annotate(total=Count("pk")).values("total"), output_field=IntegerField()), Value(0)),
        ui_followers=Coalesce(Subquery(followers.annotate(total=Count("pk")).values("total"), output_field=IntegerField()), Value(0)),
    )
    return annotate_author_roi(users, author_outer_ref="pk", annotation_name="ui_roi", period_days=90)


def capper_card(user):
    profile = user.analyst_profile
    roi = user.ui_roi or Decimal("0")
    return {
        "id": user.pk, "username": user.username,
        "name": profile.display_name or user.get_full_name() or user.username,
        "avatar": user.avatar.url if user.avatar else "", "initial": user.username[:1].upper(),
        "trust": profile.trust_index, "verified": profile.is_verified,
        "joined": user.date_joined, "roi": f"{roi:+.1f}%".replace(".", ","), "roi_positive": roi >= 0,
        "win_rate": round(user.ui_wins * 100 / user.ui_coupons) if user.ui_coupons else 0,
        "coupons": user.ui_coupons, "profile_url": reverse("front:expert_profile", args=[user.username]),
        "setup_url": reverse("wallets:copybetting_setup", args=[user.pk]),
    }


def build_capper_search_context(reader, params):
    query = str(params.get("q", "")).strip()[:150]
    sort = params.get("sort", "roi")
    sort = sort if sort in {"roi", "trust", "date", "followers"} else "roi"
    users = capper_queryset().filter(analyst_profile__is_public=True).exclude(pk=reader.pk)
    email_search = "@" in query and not query.startswith("@")
    if query:
        if email_search:
            # Email lookup is exact. No address is exposed by name search or browsing.
            users = users.filter(email__iexact=query)
        else:
            term = query.lstrip("@")
            users = users.filter(Q(username__icontains=term) | Q(analyst_profile__display_name__icontains=term) |
                                 Q(first_name__icontains=term) | Q(last_name__icontains=term))
    if params.get("verified") == "1":
        users = users.filter(analyst_profile__is_verified=True)
    users = users.annotate(ui_copying=Exists(CopyBettingSubscription.objects.filter(user=reader, analyst_id=OuterRef("pk"), status="active")))
    order = {"roi": "-ui_roi", "trust": "-analyst_profile__trust_index", "date": "-date_joined", "followers": "-ui_followers"}
    page_size = 4 if str(params.get("page_size", "")) == "4" else SEARCH_PAGE_SIZE
    page = Paginator(users.order_by(order[sort], "-id"), page_size).get_page(params.get("page", 1))
    cards = []
    for user in page.object_list:
        card = capper_card(user)
        card["copying"] = user.ui_copying
        if email_search:
            local, _, domain = user.email.partition("@")
            card["email_mask"] = f"{local[:1]}****{local[-1:] if len(local) > 1 else ''}@{domain}"
        cards.append(card)
    return {"search_cappers": cards, "search_total": page.paginator.count, "search_end": page.end_index(),
            "search_has_more": page.has_next(), "search_next_page": page.number + 1}


def build_setup_context(reader, analyst, form, *, balance):
    enriched = capper_queryset().get(pk=analyst.pk)
    fields = ("bank_amount", "stake_percent", "max_single_stake", "stop_loss_amount", "min_total_coefficient")
    if form.is_bound:
        form.is_valid()
    cleaned = form.cleaned_data if form.is_bound and all(key in form.cleaned_data for key in (*fields, "copy_regular_coupons", "copy_tournament_coupons", "allowed_sports")) else None
    if cleaned is None and not form.is_bound and form.instance.pk:
        cleaned = {name: getattr(form.instance, name) for name in fields}
        cleaned.update(copy_regular_coupons=form.instance.copy_regular_coupons,
                       copy_tournament_coupons=form.instance.copy_tournament_coupons,
                       allowed_sports=form.instance.allowed_sports.all())
    settings = SimpleNamespace(user=reader, **cleaned) if cleaned else None
    stake = _copy_stake(settings) if settings else None
    can_view_paid = user_has_paid_prediction_subscription(reader, analyst.pk)
    positions = Prediction.objects.select_related("match__home_team", "match__away_team", "match__sport")
    coupons = PredictionCoupon.objects.filter(author=analyst, published_status="published").select_related("tournament_link").prefetch_related(
        Prefetch("predictions", queryset=positions, to_attr="preview_positions"),
    )
    if not can_view_paid:
        coupons = coupons.filter(audience="free")
    coupons = coupons.order_by("-published_at", "-created_at", "-id")[:3]
    history = []
    for coupon in coupons:
        title, subtitle = f"Купон #{coupon.pk}", ""
        items = coupon.preview_positions
        if items:
            match = items[0].match
            title = f"{match.home_team_name} — {match.away_team_name}"
            subtitle = f"{items[0].selection} · кф {_coupon_total_coefficient(coupon):.2f}"
            if match.sport:
                subtitle += f" · {match.sport.name_ru or match.sport.name}"
            if len(items) > 1:
                title = f"Экспресс · {len(items)} игр"
        elif coupon.headline:
            title = coupon.headline
        eligible = bool(settings and stake >= PREDICTION_STAKE_MIN_COINS and coupon.total_stake > 0 and _copybetting_allows_coupon(settings, coupon, positions=coupon.preview_positions))
        reason = "Заполните параметры" if not settings else "Не соответствует фильтрам"
        if settings and not eligible:
            if stake < PREDICTION_STAKE_MIN_COINS:
                reason = f"Минимум {int(PREDICTION_STAKE_MIN_COINS)} C"
            elif coupon.total_stake <= 0:
                reason = "Нет суммы исходной ставки"
            elif (_coupon_is_tournament(coupon) and not settings.copy_tournament_coupons) or (not _coupon_is_tournament(coupon) and not settings.copy_regular_coupons):
                reason = "Тип прогноза не выбран"
            elif settings.min_total_coefficient > _coupon_total_coefficient(coupon):
                reason = "Коэффициент ниже порога"
            else:
                reason = "Вид спорта не выбран"
        history.append({"title": title, "subtitle": subtitle,
                        "eligible": eligible, "result": coins(stake) + " C" if eligible else reason})
    blocked = CopyBettingBlock.objects.filter(user=reader, analyst=analyst, revoked_at__isnull=True).exists()
    errors = [message for messages in form.errors.values() for message in messages] if form.is_bound else []
    if blocked:
        errors.insert(0, "Автор запретил вам копировать его прогнозы.")
    return {"setup_copy_blocked": blocked, "setup_capper": capper_card(enriched), "setup_balance": coins(balance), "setup_history": history,
            "setup_valid": bool(settings), "setup_stake_too_low": stake is not None and stake < PREDICTION_STAKE_MIN_COINS,
            "setup_min_stake": int(PREDICTION_STAKE_MIN_COINS),
            "setup_validation_errors": errors, "setup_stake": coins(stake) if stake is not None else "—",
            "setup_bank": coins(settings.bank_amount) if settings else "—",
            "setup_percent": format(settings.stake_percent.normalize(), "f") if settings else "—",
            "setup_capped": bool(settings and settings.max_single_stake > 0 and settings.bank_amount * settings.stake_percent / 100 > stake),
            "setup_balance_short": bool(stake and stake > balance),
            "setup_max_stakes": int(balance // stake) if stake and stake > 0 else 0}

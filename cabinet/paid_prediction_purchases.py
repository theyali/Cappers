"""Sale eligibility shared by checkout and payment delivery.

No purchase can be charged until the rollout and financial terms are configured.
Existing access is intentionally independent of this switch.
"""
from django.conf import settings
from django.utils import timezone

from cabinet.paid_predictions import profile_single_coupon_sales_enabled
from game.models import PredictionCoupon
from game.services.match_timing import prediction_window_open


def single_coupon_sale_blocker(coupon, *, at=None, positions=None):
    if not getattr(settings, "SINGLE_COUPON_SALES_ENABLED", False):
        return "Разовые покупки пока недоступны."
    if coupon.published_status != PredictionCoupon.PublishedStatus.PUBLISHED:
        return "Купон не опубликован."
    if coupon.audience != PredictionCoupon.Audience.PAID:
        return "Этот купон доступен бесплатно."
    if coupon.state_status != PredictionCoupon.StateStatus.PENDING or coupon.settled_at:
        return "Купон уже рассчитан."
    if not coupon.author.is_active or not coupon.author.is_analyst or not profile_single_coupon_sales_enabled(coupon.author):
        return "Автор отключил разовые продажи."
    if positions is None:
        positions = list(coupon.predictions.select_related("match"))
    if not positions:
        return "В купоне нет матчей."
    moment = at or timezone.now()
    if any(not prediction_window_open(position.match, now=moment) for position in positions):
        return "Матч начался, покупка недоступна."
    if not coupon.single_purchase_enabled or not coupon.single_purchase_price or coupon.single_purchase_price <= 0:
        return "Купон опубликован без разовой продажи. Цена применяется к новым купонам."
    return ""


def _lock_participants(buyer, analyst):
    from cabinet.models import User
    list(User.objects.select_for_update(no_key=True).filter(pk__in=[buyer.pk, analyst.pk]).order_by("pk"))


def _purchase_terms(coupon):
    from decimal import Decimal, ROUND_HALF_UP
    from django.core.exceptions import ValidationError
    from back.models import WebsiteSettings

    config = WebsiteSettings.load()
    price = coupon.single_purchase_price
    if not (config.single_coupon_min_price <= price <= config.single_coupon_max_price):
        raise ValidationError("Цена купона вне разрешённых пределов.")
    fee = (price * config.single_coupon_fee_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return dict(price=price, currency="RUB", platform_fee_percent=config.single_coupon_fee_percent,
                platform_fee_amount=fee, capper_income=price-fee,
                income_hold_days=config.single_coupon_income_hold_days)


def _prepare_locked_purchase(buyer, coupon):
    from django.core.exceptions import ValidationError
    from cabinet.models import PaidPredictionPurchase
    from cabinet.paid_predictions import user_can_view_paid_coupon

    existing = PaidPredictionPurchase.objects.select_for_update().filter(buyer=buyer, coupon=coupon).first()
    if existing and existing.analyst_id != coupon.author_id:
        raise ValidationError("Автор купона изменился. Покупка требует проверки.")
    if existing and existing.status == PaidPredictionPurchase.Status.REFUNDED:
        raise ValidationError("Повторная покупка после возврата недоступна.")
    if user_can_view_paid_coupon(buyer, coupon):
        return existing, True
    positions = list(coupon.predictions.select_related("match"))
    reason = single_coupon_sale_blocker(coupon, positions=positions)
    if reason:
        raise ValidationError(reason)
    if existing is None:
        existing = PaidPredictionPurchase.objects.create(buyer=buyer, analyst=coupon.author, coupon=coupon, **_purchase_terms(coupon))
    existing.sale_deadline = min(position.match.starts_at for position in positions)
    return existing, False


def prepare_coupon_purchase(buyer, coupon):
    from django.db import transaction
    from django.core.exceptions import ValidationError

    with transaction.atomic():
        _lock_participants(buyer, coupon.author)
        coupon = PredictionCoupon.objects.select_for_update(of=("self",)).select_related("author__analyst_profile").get(pk=coupon.pk)
        purchase, accessible = _prepare_locked_purchase(buyer, coupon)
        if accessible:
            raise ValidationError("Купон уже доступен. Откройте его без повторной оплаты.")
        return purchase


def _notify_purchase(purchase, *, refunded=False):
    from django.urls import reverse
    from notifications.models import Notification
    from notifications.services import create_notification

    for recipient in (purchase.buyer, purchase.analyst):
        create_notification(recipient=recipient, kind=Notification.Kind.COUPON_PURCHASE,
            title="Покупка купона возвращена" if refunded else "Купон оплачен",
            message=f"Купон #{purchase.coupon_id} · {purchase.price} ₽",
            event_key=f"coupon-purchase:{purchase.pk}:{'refunded' if refunded else 'paid'}:{recipient.pk}",
            url=reverse("front:prediction_detail", args=[purchase.coupon_id]))


def _grant_locked_purchase(purchase, *, payment=None):
    from cabinet.models import PaidPredictionPurchase
    from wallets.models import RealBalanceTransaction
    from wallets.services import credit_real_balance, debit_real_balance, ensure_real_balance

    # All wallet paths use the same order, including the two opposite transfers.
    for user in sorted([purchase.buyer, purchase.analyst], key=lambda user: user.pk):
        ensure_real_balance(user)
    if payment is None:
        debit_real_balance(purchase.buyer, purchase.price, RealBalanceTransaction.Kind.COUPON_PURCHASE,
            related_obj=purchase, note=f"Купон #{purchase.coupon_id}")
    if purchase.capper_income:
        credit_real_balance(purchase.analyst, purchase.capper_income, RealBalanceTransaction.Kind.COUPON_INCOME,
            related_obj=purchase, note=f"Продажа купона #{purchase.coupon_id}", hold_days=purchase.income_hold_days)
    purchase.status = PaidPredictionPurchase.Status.PAID
    purchase.payment = payment
    purchase.paid_at = payment.paid_at if payment is not None else timezone.now()
    purchase.save(update_fields=["status", "payment", "paid_at"])
    _notify_purchase(purchase)
    return purchase


def buy_coupon_with_balance(buyer, coupon):
    from django.db import transaction

    with transaction.atomic():
        _lock_participants(buyer, coupon.author)
        coupon = PredictionCoupon.objects.select_for_update(of=("self",)).select_related("author__analyst_profile").get(pk=coupon.pk)
        purchase, accessible = _prepare_locked_purchase(buyer, coupon)
        if accessible:
            return purchase
        return _grant_locked_purchase(purchase)


def fulfill_coupon_purchase(payment):
    from django.db import transaction
    from django.utils.dateparse import parse_datetime
    from cabinet.models import PaidPredictionPurchase
    from cabinet.paid_predictions import user_can_view_paid_coupon

    from payments.models import Payment
    from django.core.exceptions import ValidationError
    if payment.status != Payment.Status.SUCCEEDED:
        raise ValidationError("Доступ выдаётся только после подтверждения оплаты.")
    terms = payment.product_snapshot
    with transaction.atomic():
        purchase = PaidPredictionPurchase.objects.select_related("buyer", "analyst").get(pk=terms["purchase_id"])
        _lock_participants(purchase.buyer, purchase.analyst)
        purchase = PaidPredictionPurchase.objects.select_for_update().select_related("coupon__author", "buyer", "analyst").get(pk=purchase.pk)
        if purchase.payment_id == payment.pk and purchase.status == PaidPredictionPurchase.Status.PAID:
            return purchase
        deadline = parse_datetime(terms.get("sale_deadline", ""))
        reason = ""
        if (payment.user_id != purchase.buyer_id or terms.get("coupon_id") != purchase.coupon_id
                or terms.get("analyst_id") != purchase.analyst_id or payment.amount_rub != purchase.price
                or purchase.coupon.author_id != purchase.analyst_id):
            reason = "Снимок заказа не совпадает с покупкой."
        elif not deadline or not payment.paid_at or not payment.created_at <= payment.paid_at < deadline:
            # No provider-confirmed settlement timestamp is available in this integration.
            # Receipt before the deadline proves timeliness; a late receipt requires review.
            reason = "Оплата после срока продажи или время оплаты не подтверждено."
        elif purchase.status == PaidPredictionPurchase.Status.REFUNDED or user_can_view_paid_coupon(purchase.buyer, purchase.coupon):
            reason = "Купон уже доступен или покупка ранее возвращена: требуется возврат лишней оплаты."
        if reason:
            payment.requires_review = True
            payment.failure_reason = reason
            payment.save(update_fields=["requires_review", "failure_reason", "updated_at"])
            return None
        return _grant_locked_purchase(purchase, payment=payment)


def refund_coupon_purchase(purchase, *, provider_confirmed=False):
    from django.core.exceptions import ValidationError
    from django.db import transaction
    from cabinet.models import PaidPredictionPurchase
    from payments.models import Payment
    from wallets.services import reverse_paid_coupon_money

    with transaction.atomic():
        if purchase.payment_id:
            payment = Payment.objects.select_for_update().get(pk=purchase.payment_id)
            if not provider_confirmed or payment.status != Payment.Status.REFUNDED:
                raise ValidationError("Сначала подтвердите полный возврат у платёжного провайдера.")
        _lock_participants(purchase.buyer, purchase.analyst)
        purchase = PaidPredictionPurchase.objects.select_for_update().select_related("buyer", "analyst").get(pk=purchase.pk)
        if purchase.payment_id and not provider_confirmed:
            raise ValidationError("Сначала подтвердите полный возврат у платёжного провайдера.")
        if purchase.status != PaidPredictionPurchase.Status.PAID:
            return purchase
        reverse_paid_coupon_money(purchase, refund_to_balance=purchase.payment_id is None)
        purchase.status = PaidPredictionPurchase.Status.REFUNDED
        purchase.refunded_at = timezone.now()
        purchase.save(update_fields=["status", "refunded_at"])
        _notify_purchase(purchase, refunded=True)
        return purchase


def single_coupon_offer(coupon):
    from django.urls import reverse

    positions = next((getattr(coupon, attr) for attr in ("card_positions", "profile_positions", "detail_positions")
                      if hasattr(coupon, attr)), None)
    reason = single_coupon_sale_blocker(coupon, positions=positions)
    return {
        "single_purchase_available": not reason,
        "single_purchase_price": coupon.single_purchase_price,
        "single_purchase_reason": reason,
        "single_checkout_url": reverse("cabinet:single_coupon_checkout", args=[coupon.pk]),
    }


def build_single_checkout_context(user, coupon, *, in_telegram_app=False):
    from decimal import Decimal
    from django.urls import reverse
    from django.utils.formats import date_format
    from payments.utils import build_payment_options
    from wallets.services import ensure_real_balance, format_money
    from cabinet.paid_predictions import get_active_paid_plans, profile_paid_subscriptions_enabled

    positions = list(coupon.predictions.select_related("match__league", "match__home_team", "match__away_team"))
    reason = single_coupon_sale_blocker(coupon, positions=positions)
    can_use_balance = user.is_analyst
    balance = ensure_real_balance(user).balance if can_use_balance else Decimal("0")
    price = coupon.single_purchase_price
    previews = []
    total_coefficient = Decimal("1")
    for position in positions:
        match = position.match
        total_coefficient *= position.coefficient
        previews.append({
            "title": f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}",
            "league": match.league_name,
            "starts_label": date_format(timezone.localtime(match.starts_at), "d.m.Y · H:i") if match.starts_at else "",
        })
    profile = coupon.author.analyst_profile
    plan = get_active_paid_plans(coupon.author).first()
    subscription_offer = None
    if profile_paid_subscriptions_enabled(coupon.author):
        subscription_offer = {
            "price_label": format_money(plan.price if plan else profile.paid_predictions_price),
            "period": plan.period_label if plan else "30 дней",
            "url": reverse("cabinet:paid_predictions_subscribe", args=[coupon.author_id]),
        }
    return {
        "coupon": coupon, "sale_blocker": reason,
        "expert": coupon.author,
        "expert_name": profile.display_name or coupon.author.get_full_name() or coupon.author.username,
        "price": price, "real_balance_display": format_money(balance),
        "balance_after_display": format_money(balance - price) if price and balance >= price else "",
        "can_use_coupon_balance": can_use_balance,
        "can_pay": not reason and can_use_balance and balance >= price,
        "payment_options": build_payment_options(price, user, in_telegram_app=in_telegram_app) if not reason else [],
        "coupon_preview": previews,
        "total_coefficient": total_coefficient.quantize(Decimal("0.01")) if positions else "—",
        "subscription_offer": subscription_offer,
    }


def build_public_tariff_coupon_context(viewer, analyst, *, limit=6):
    """Public event names and purchase links; paid picks never enter this payload."""
    from django.db.models import Exists, OuterRef, Prefetch
    from django.urls import reverse
    from django.utils.formats import date_format
    from game.models import Prediction
    from .vip import plural_ru
    from cabinet.paid_predictions import accessible_paid_coupon_ids
    from wallets.services import format_money

    positions = Prediction.objects.filter(coupon_id=OuterRef("pk"))
    queryset = PredictionCoupon.objects.filter(
        author=analyst, audience=PredictionCoupon.Audience.PAID,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).filter(Exists(positions))
    total = queryset.count()
    position_query = Prediction.objects.select_related(
        "match__league", "match__home_team", "match__away_team",
    ).defer("selection", "outcome_code", "market", "stake", "coefficient").order_by("pk")
    coupons = list(queryset.defer("description", "headline").prefetch_related(
        Prefetch("predictions", queryset=position_query, to_attr="card_positions"),
    ).order_by("-published_at", "-pk")[:limit])
    accessible_ids = accessible_paid_coupon_ids(viewer, coupons)
    rows = []
    for coupon in coupons:
        coupon.author = analyst
        match = coupon.card_positions[0].match
        offer = single_coupon_offer(coupon)
        accessible = coupon.pk in accessible_ids
        title = f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}"
        if len(coupon.card_positions) > 1:
            title += f" + ещё {len(coupon.card_positions) - 1}"
        rows.append({
            "id": coupon.pk, "title": title, "league": match.league_name,
            "starts_label": date_format(timezone.localtime(match.starts_at), "d.m · H:i") if match.starts_at else "Время не указано",
            "is_completed": coupon.state_status != PredictionCoupon.StateStatus.PENDING or bool(coupon.settled_at),
            "accessible": accessible,
            "action_url": reverse("front:prediction_detail", args=[coupon.pk]) if accessible or not offer["single_purchase_available"] else offer["single_checkout_url"],
            "action_label": "Открыть" if accessible else f"{format_money(offer['single_purchase_price'])} ₽" if offer["single_purchase_available"] else "Подробнее",
            "mobile_action_label": "Открыть" if accessible else f"Купить {format_money(offer['single_purchase_price'])} ₽" if offer["single_purchase_available"] else "Подробнее",
        })
    return {"rows": rows, "total": total, "total_label": f"{total} {plural_ru(total, 'прогноз', 'прогноза', 'прогнозов')}", "has_more_desktop": total > limit, "has_more_mobile": total > 3}


def coupon_purchase_history(user, *, sales=False, refunded=False):
    from cabinet.models import PaidPredictionPurchase
    from django.db.models import Count, Sum

    base = PaidPredictionPurchase.objects.filter(**({"analyst": user} if sales else {"buyer": user}))
    paid = base.filter(status=PaidPredictionPurchase.Status.PAID)
    refunds = base.filter(status=PaidPredictionPurchase.Status.REFUNDED)
    totals = paid.aggregate(count=Count("pk"), revenue=Sum("price"), fee=Sum("platform_fee_amount"), income=Sum("capper_income"))
    totals["refunds"] = refunds.aggregate(total=Sum("price"))["total"] or 0
    rows = (refunds if refunded else paid).select_related("coupon", "analyst", "buyer").order_by("-paid_at", "-pk")
    return rows, {key: value or 0 for key, value in totals.items()}

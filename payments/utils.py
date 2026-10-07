from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from payments.models import Payment
from payments.services.checkout import can_pay_with_providers
from payments.services.providers.factory import PaymentProviderFactory

DONE_TEXTS = {
    Payment.Purpose.COIN_PACKAGE: "Коины зачислены на баланс.",
    Payment.Purpose.PAID_SUBSCRIPTION: "Подписка активна: закрытые прогнозы каппера уже доступны.",
    Payment.Purpose.VIP_PLAN: "VIP-тариф активирован.",
}


def build_payment_options(amount_rub, user) -> list[dict]:
    """Pay buttons for a product at this price; empty while payments are off."""
    if not can_pay_with_providers(user):
        return []
    return [
        {"code": provider.code, "label": provider.pay_label}
        for provider in PaymentProviderFactory.available_for(amount_rub)
    ]


def build_payment_status(payment: Payment) -> dict:
    """What the return page shows; also the JSON it polls."""
    status = payment.status
    status_context = {
        "state": "failed",
        "title": "Заказ закрыт",
        "text": "Срок оплаты истёк. Оформите покупку заново.",
        "retry_url": "",
    }
    if status == Payment.Status.SUCCEEDED and payment.fulfilled_at:
        status_context.update(state="done", title="Оплата прошла", text=DONE_TEXTS[payment.purpose])
    elif status == Payment.Status.SUCCEEDED:
        status_context.update(state="pending", title="Оплата получена", text="Зачисляем покупку, это займёт несколько секунд.")
    elif status in (Payment.Status.CREATED, Payment.Status.PENDING):
        status_context.update(
            state="pending",
            title="Ждём подтверждение оплаты",
            text="Обычно это занимает несколько секунд. Страница обновится сама.",
        )
    elif status == Payment.Status.PROCESSING:
        status_context.update(
            state="pending",
            title="Платёж подтверждается",
            text="Деньги получены и проходят подтверждение. Для криптовалюты это может занять до часа.",
        )
    elif status == Payment.Status.PARTIALLY_PAID:
        status_context.update(
            title="Оплачено не полностью",
            text="Пришла не вся сумма. Напишите в поддержку: поможем доплатить или вернуть деньги.",
        )
    elif status == Payment.Status.FAILED:
        can_retry = bool(payment.checkout_url) and payment.expires_at and payment.expires_at > timezone.now()
        status_context.update(
            title="Оплата не прошла",
            text=(
                "Банк отклонил платёж. Попробуйте ещё раз или оплатите другой картой."
                if payment.provider == Payment.Provider.CLOUDPAYMENTS
                else "Платёж не прошёл. Попробуйте ещё раз."
            ),
            retry_url=payment.checkout_url if can_retry else "",
        )
    elif status == Payment.Status.REFUNDED:
        status_context.update(title="Платёж возвращён", text="Деньги вернутся туда, откуда была оплата, в сроки банка или сети.")
    return status_context


def build_payment_return_context(payment: Payment) -> dict:
    back_url, back_label = reverse("wallets:top_up"), "К пакетам коинов"
    if payment.purpose == Payment.Purpose.VIP_PLAN:
        back_url, back_label = reverse("cabinet:vip_plans"), "К VIP-тарифам"
    elif payment.purpose == Payment.Purpose.PAID_SUBSCRIPTION:
        username = (
            User.objects.filter(pk=payment.product_snapshot.get("analyst_id")).values_list("username", flat=True).first()
        )
        back_url = reverse("front:expert_profile", kwargs={"username": username}) if username else reverse("front:index")
        back_label = "К профилю каппера"
    return {
        "payment": payment,
        "product_title": payment.product_snapshot.get("description") or payment.get_purpose_display(),
        "amount": payment.amount,
        "status": build_payment_status(payment),
        "status_url": reverse("payments:status", args=[payment.public_id]),
        "back_url": back_url,
        "back_label": back_label,
    }

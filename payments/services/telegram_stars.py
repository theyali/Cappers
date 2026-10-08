import logging

from payments.services.processing import apply_provider_event
from payments.services.providers.base import PaymentProviderError, Rejection
from payments.services.providers.factory import PaymentProviderFactory
from payments.services.providers.telegram_stars import TelegramStarsProvider

logger = logging.getLogger("payments")

# What the payer sees in Telegram when the payment is refused.
REFUSALS = {
    Rejection.EXPIRED: "Срок оплаты истёк. Оформите покупку заново в КапперХаб.",
    Rejection.NOT_PAYABLE: "Этот заказ уже нельзя оплатить. Оформите покупку заново в КапперХаб.",
}
DEFAULT_REFUSAL = "Не удалось принять оплату. Попробуйте ещё раз из КапперХаб."


def answer_pre_checkout_query(query: dict) -> None:
    """Telegram asks whether to take the Stars and waits about 10 seconds for the answer."""
    from notifications.telegram_bot import api_call

    try:
        provider = PaymentProviderFactory.create(TelegramStarsProvider.code)
        rejection = apply_provider_event(provider.code, provider.pre_checkout_event(query))
    except PaymentProviderError as error:
        logger.warning("Stars pre-checkout %s refused: %s", query.get("id"), error)
        rejection = Rejection.UNKNOWN_PAYMENT

    answer = {"pre_checkout_query_id": query["id"], "ok": rejection is None}
    if rejection is not None:
        answer["error_message"] = REFUSALS.get(rejection, DEFAULT_REFUSAL)
    api_call("answerPreCheckoutQuery", answer)


def record_successful_payment(successful_payment: dict) -> None:
    """The Stars are paid: mark the payment, which then delivers the product."""
    # Built from settings even if Stars were switched off since: arrived money is always recorded.
    provider = TelegramStarsProvider.from_settings()
    try:
        event = provider.payment_event(successful_payment)
    except PaymentProviderError as error:
        logger.error("Stars payment not recorded: %s (%s)", error, successful_payment)
        return
    try:
        apply_provider_event(provider.code, event)
    except Exception:
        # The bot has already confirmed this update to Telegram, which will not send it
        # again: the log line is what lets an admin record the payment by hand.
        logger.exception("Stars payment %s not saved: %s", event.external_id, successful_payment)
        raise

import logging
import math
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from payments.models import Payment

from .base import CheckoutSession, PaymentProvider, PaymentProviderError, ProviderEvent, Rejection

logger = logging.getLogger("payments")

STARS_CURRENCY = "XTR"
# Telegram limits on invoice texts.
TITLE_LIMIT = 32
DESCRIPTION_LIMIT = 255


@dataclass(frozen=True)
class TelegramStarsProvider(PaymentProvider):
    """Payment in Telegram Stars through the bot.

    There are no webhooks: Telegram sends pre_checkout_query and successful_payment
    to the bot, and payments/services/telegram_stars.py turns them into events.
    """

    code = Payment.Provider.TELEGRAM_STARS.value
    title = "Telegram Stars"
    pay_label = "Оплатить звёздами"
    # Stars invoices are paid only inside Telegram.
    telegram_only = True

    bot_token: str
    rub_per_star: Decimal
    order_ttl_minutes: int

    @classmethod
    def from_settings(cls) -> "TelegramStarsProvider":
        return cls(
            bot_token=settings.TG_BOT_TOKEN,
            rub_per_star=settings.TELEGRAM_STARS_RUB_RATE,
            order_ttl_minutes=settings.TELEGRAM_STARS_ORDER_TTL_MINUTES,
        )

    def is_enabled(self) -> bool:
        return bool(self.bot_token) and self.rub_per_star > 0

    def supports(self, amount_rub) -> bool:
        return amount_rub > 0

    def stars_for(self, amount_rub: Decimal) -> int:
        return max(1, math.ceil(Decimal(amount_rub) / self.rub_per_star))

    def create_checkout(self, payment, *, success_url: str, fail_url: str, webhook_url: str) -> CheckoutSession:
        from notifications.telegram_bot import api_call

        stars = self.stars_for(payment.amount)
        description = payment.product_snapshot.get("description") or payment.get_purpose_display()
        try:
            invoice_url = api_call(
                "createInvoiceLink",
                {
                    "title": _shorten(description, TITLE_LIMIT),
                    "description": _shorten(description, DESCRIPTION_LIMIT),
                    "payload": invoice_payload(payment, stars),
                    "currency": STARS_CURRENCY,
                    "prices": [{"label": _shorten(description, TITLE_LIMIT), "amount": stars}],
                },
            )
        except Exception as error:
            # The error text never holds the token: it is only in the request address.
            logger.error("Telegram did not create a Stars invoice for payment %s: %s", payment.public_id, error)
            raise PaymentProviderError("Не удалось создать оплату. Попробуйте позже.") from error
        if not isinstance(invoice_url, str) or not invoice_url.startswith("https://"):
            raise PaymentProviderError("Не удалось создать оплату. Попробуйте позже.")
        return CheckoutSession(
            redirect_url=invoice_url,
            expires_at=timezone.now() + timedelta(minutes=self.order_ttl_minutes),
        )

    def verify_signature(self, request) -> None:
        raise PaymentProviderError("Telegram Stars присылает оплаты боту, а не на webhook.")

    def parse_webhook(self, request, *, event_type: str) -> ProviderEvent:
        raise PaymentProviderError("Telegram Stars присылает оплаты боту, а не на webhook.")

    def fetch_status(self, payment) -> ProviderEvent | None:
        # Telegram keeps undelivered bot updates for a day, so nothing to ask for here.
        return None

    def webhook_response(self, *, rejection: Rejection | None = None):
        return HttpResponse(status=404)

    def pre_checkout_event(self, query: dict) -> ProviderEvent:
        """Telegram asks whether the payer may pay this invoice."""
        public_id = _checked_payload(query)
        return ProviderEvent(
            event_type="check",
            payment_public_id=public_id,
            status=Payment.Status.PENDING,
            dedup_key=f"check:{query.get('id', '')}",
            raw=query,
        )

    def payment_event(self, successful_payment: dict) -> ProviderEvent:
        """The Stars arrived; Telegram's charge id is what a refund needs later."""
        public_id = _checked_payload(successful_payment)
        charge_id = str(successful_payment.get("telegram_payment_charge_id") or "")
        if not charge_id:
            raise PaymentProviderError("Telegram Stars: нет telegram_payment_charge_id.")
        return ProviderEvent(
            event_type="pay",
            payment_public_id=public_id,
            status=Payment.Status.SUCCEEDED,
            external_id=charge_id,
            paid_amount=Decimal(successful_payment["total_amount"]),
            paid_currency=STARS_CURRENCY,
            dedup_key=f"pay:{charge_id}",
            raw=successful_payment,
        )


def invoice_payload(payment, stars: int) -> str:
    # Telegram returns the payload unchanged with the payment, so it carries the invoiced amount.
    return f"{payment.public_id}:{stars}"


def _checked_payload(data: dict) -> str:
    public_id, _, stars = str(data.get("invoice_payload") or "").partition(":")
    if data.get("currency") != STARS_CURRENCY or not stars.isdigit():
        raise PaymentProviderError("Telegram Stars: это не наш счёт.")
    if int(stars) != data.get("total_amount"):
        raise PaymentProviderError(f"Telegram Stars: сумма {data.get('total_amount')} не совпадает со счётом ({stars}).")
    return public_id


def _shorten(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

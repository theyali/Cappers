from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import ClassVar


class PaymentProviderError(Exception):
    """The provider is unavailable or answered with an error."""


class InvalidSignature(PaymentProviderError):
    """A webhook signature did not verify."""


class PaymentProviderDisabled(PaymentProviderError):
    """The provider is turned off in the settings."""


@dataclass(frozen=True)
class CheckoutSession:
    redirect_url: str = ""
    external_invoice_id: str = ""
    expires_at: datetime | None = None
    # Parameters for an on-page payment widget instead of a redirect.
    widget_params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderEvent:
    event_type: str  # check / pay / fail / refund / cancel / ipn / reconcile
    payment_public_id: str  # our Payment.public_id, sent to the provider as the order id
    status: str  # Payment.Status
    external_id: str = ""
    amount: Decimal | None = None  # in the invoice currency
    currency: str = ""
    paid_amount: Decimal | None = None
    paid_currency: str = ""
    is_test: bool = False
    dedup_key: str = ""
    failure_reason: str = ""
    raw: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    """What every payment provider offers; checkout, webhooks and reconciliation use only this."""

    code: ClassVar[str]
    title: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_settings(cls) -> "PaymentProvider":
        """Factory method: build the provider from django.conf.settings."""

    @abstractmethod
    def is_enabled(self) -> bool:
        """Whether the provider is configured well enough to take payments."""

    @abstractmethod
    def supports(self, payment) -> bool:
        """Whether this payment can be paid here (currency, minimum amount)."""

    @abstractmethod
    def create_checkout(self, payment, *, success_url: str, fail_url: str, webhook_url: str) -> CheckoutSession:
        """Create the provider's order or invoice for the payment."""

    @abstractmethod
    def verify_signature(self, request) -> None:
        """Check the signature against the raw request.body; raise InvalidSignature."""

    @abstractmethod
    def parse_webhook(self, request, *, event_type: str) -> ProviderEvent:
        """Turn a provider notification into a ProviderEvent."""

    @abstractmethod
    def fetch_status(self, payment) -> ProviderEvent | None:
        """Ask the provider for the current status (reconciliation, lost webhooks)."""

    @abstractmethod
    def webhook_response(self, *, accepted: bool, code: int = 0):
        """The HTTP response in the format the provider expects."""

    def refund(self, payment, amount: Decimal | None = None) -> None:
        raise PaymentProviderError(f"{self.title}: автоматический возврат не поддерживается.")

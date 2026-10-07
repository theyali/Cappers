from django.conf import settings

from .base import PaymentProvider, PaymentProviderDisabled, PaymentProviderError
from .cloudpayments import CloudPaymentsProvider


class UnknownPaymentProvider(PaymentProviderError):
    pass


class PaymentProviderFactory:
    """Creates the provider for a code; callers never name a concrete provider class.

    A plain dict instead of registration on import keeps the list of providers in
    one visible place. Adding a provider is one class and one line here.
    """

    _providers: dict[str, type[PaymentProvider]] = {
        CloudPaymentsProvider.code: CloudPaymentsProvider,
    }

    @classmethod
    def create(cls, code: str) -> PaymentProvider:
        provider_cls = cls._providers.get(code)
        if provider_cls is None:
            raise UnknownPaymentProvider(f"Неизвестный платёжный провайдер: {code}")
        if code not in settings.PAYMENTS_ENABLED_PROVIDERS:
            raise PaymentProviderDisabled(f"Провайдер {code} выключен.")
        provider = provider_cls.from_settings()
        if not provider.is_enabled():
            raise PaymentProviderDisabled(f"Провайдер {code} не настроен.")
        return provider

    @classmethod
    def available_for(cls, payment) -> list[PaymentProvider]:
        """Providers that can take this payment, for the buttons on the checkout page."""
        available = []
        for code in settings.PAYMENTS_ENABLED_PROVIDERS:
            try:
                provider = cls.create(code)
            except PaymentProviderError:
                continue
            if provider.supports(payment):
                available.append(provider)
        return available

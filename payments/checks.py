from django.conf import settings
from django.core.checks import Tags, Warning, register

from payments.services.providers.base import PaymentProviderDisabled
from payments.services.providers.factory import PaymentProviderFactory, UnknownPaymentProvider


@register(Tags.security)
def check_payment_settings(app_configs=None, **kwargs):
    """Warn at deploy (migrate and check run these) about a half-configured payment launch."""
    warnings = []
    for code in settings.PAYMENTS_ENABLED_PROVIDERS:
        try:
            PaymentProviderFactory.create(code)
        except UnknownPaymentProvider:
            warnings.append(
                Warning(f"PAYMENTS_ENABLED_PROVIDERS: неизвестный провайдер «{code}».", id="payments.W001")
            )
        except PaymentProviderDisabled:
            warnings.append(
                Warning(
                    f"Провайдер «{code}» включён, но не настроен: кнопок оплаты не будет.",
                    hint="Задайте ключи провайдера в .env (без «change-me»).",
                    id="payments.W002",
                )
            )
    if (
        settings.PAYMENTS_ENABLED_PROVIDERS
        and settings.PAYMENTS_ALLOW_TEST_PAYMENTS
        and not settings.PAYMENTS_STAFF_ONLY
        and not settings.DEBUG
    ):
        warnings.append(
            Warning(
                "Тестовые платежи принимаются от всех: любой получит товар за тестовую карту.",
                hint="Пока терминал в тестовом режиме, включите PAYMENTS_STAFF_ONLY; после запуска выключите PAYMENTS_ALLOW_TEST_PAYMENTS.",
                id="payments.W003",
            )
        )
    return warnings

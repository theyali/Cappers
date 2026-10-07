from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from payments.services.providers.base import CheckoutSession, PaymentProvider, PaymentProviderDisabled
from payments.services.providers.factory import PaymentProviderFactory, UnknownPaymentProvider


class FakeCardProvider(PaymentProvider):
    code = "fake_card"
    title = "Тестовая карта"
    configured = True
    min_amount_rub = Decimal("0")

    @classmethod
    def from_settings(cls):
        return cls()

    def is_enabled(self):
        return self.configured

    def supports(self, payment):
        return payment.amount_rub >= self.min_amount_rub

    def create_checkout(self, payment, *, success_url, fail_url, webhook_url):
        return CheckoutSession(redirect_url=f"https://pay.example/{payment.public_id}")

    def verify_signature(self, request):
        return None

    def parse_webhook(self, request, *, event_type):
        raise NotImplementedError

    def fetch_status(self, payment):
        return None

    def webhook_response(self, *, rejection=None):
        return {"rejection": rejection}


class FakeCryptoProvider(FakeCardProvider):
    code = "fake_crypto"
    title = "Тестовая крипта"
    min_amount_rub = Decimal("500")


PROVIDERS = {FakeCardProvider.code: FakeCardProvider, FakeCryptoProvider.code: FakeCryptoProvider}


@patch.dict(PaymentProviderFactory._providers, PROVIDERS, clear=True)
class PaymentProviderFactoryTests(SimpleTestCase):
    @override_settings(PAYMENTS_ENABLED_PROVIDERS=["fake_card"])
    def test_creates_the_provider_by_its_code(self):
        provider = PaymentProviderFactory.create("fake_card")

        self.assertIsInstance(provider, FakeCardProvider)
        payment = SimpleNamespace(public_id="abc", amount_rub=Decimal("100"))
        session = provider.create_checkout(payment, success_url="", fail_url="", webhook_url="")
        self.assertEqual(session.redirect_url, "https://pay.example/abc")

    @override_settings(PAYMENTS_ENABLED_PROVIDERS=["fake_card"])
    def test_unknown_code_is_rejected(self):
        with self.assertRaises(UnknownPaymentProvider):
            PaymentProviderFactory.create("paypal")

    @override_settings(PAYMENTS_ENABLED_PROVIDERS=[])
    def test_provider_not_enabled_in_settings_is_refused(self):
        with self.assertRaises(PaymentProviderDisabled):
            PaymentProviderFactory.create("fake_card")

    @override_settings(PAYMENTS_ENABLED_PROVIDERS=["fake_card"])
    def test_unconfigured_provider_is_refused(self):
        with patch.object(FakeCardProvider, "configured", False), self.assertRaises(PaymentProviderDisabled):
            PaymentProviderFactory.create("fake_card")

    @override_settings(PAYMENTS_ENABLED_PROVIDERS=["fake_card", "fake_crypto", "paypal"])
    def test_checkout_offers_only_providers_that_can_take_the_payment(self):
        cheap = SimpleNamespace(amount_rub=Decimal("199"))
        expensive = SimpleNamespace(amount_rub=Decimal("990"))

        self.assertEqual([p.code for p in PaymentProviderFactory.available_for(cheap)], ["fake_card"])
        self.assertEqual(
            [p.code for p in PaymentProviderFactory.available_for(expensive)],
            ["fake_card", "fake_crypto"],
        )

    def test_payments_are_off_by_default(self):
        self.assertEqual(PaymentProviderFactory.available_for(SimpleNamespace(amount_rub=Decimal("990"))), [])

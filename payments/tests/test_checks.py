from django.test import SimpleTestCase, override_settings

from payments.checks import check_payment_settings
from payments.tests.test_cloudpayments import CLOUDPAYMENTS_SETTINGS


def warning_ids():
    return [warning.id for warning in check_payment_settings()]


@override_settings(**CLOUDPAYMENTS_SETTINGS, DEBUG=False)
class PaymentSettingsCheckTests(SimpleTestCase):
    def test_a_configured_launch_is_quiet(self):
        self.assertEqual(warning_ids(), [])

    @override_settings(PAYMENTS_ENABLED_PROVIDERS=["cloudpayments", "paypal"])
    def test_unknown_providers_are_reported(self):
        self.assertEqual(warning_ids(), ["payments.W001"])

    @override_settings(CLOUDPAYMENTS_API_SECRET="change-me-cloudpayments-api-secret")
    def test_placeholder_credentials_are_reported(self):
        self.assertEqual(warning_ids(), ["payments.W002"])

    @override_settings(PAYMENTS_ALLOW_TEST_PAYMENTS=True)
    def test_test_payments_open_to_everyone_are_reported(self):
        self.assertEqual(warning_ids(), ["payments.W003"])

        with override_settings(PAYMENTS_STAFF_ONLY=True):
            self.assertEqual(warning_ids(), [])

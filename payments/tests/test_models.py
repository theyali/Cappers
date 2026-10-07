from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse

from cabinet.models import User
from payments.models import Payment, PaymentEvent


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def make_payment(user, **extra):
    values = {
        "user": user,
        "provider": Payment.Provider.CLOUDPAYMENTS,
        "purpose": Payment.Purpose.COIN_PACKAGE,
        "amount": Decimal("499.00"),
        "amount_rub": Decimal("499.00"),
        "product_snapshot": {"package_id": 1, "title": "Старт", "coins": 1000, "bonus_coins": 100, "price_rub": "499.00"},
    }
    values.update(extra)
    return Payment.objects.create(**values)


class PaymentModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="payer", password="safe-test-password")

    def test_new_payment_gets_a_public_id_and_starts_created(self):
        payment = make_payment(self.user)

        self.assertIsNotNone(payment.public_id)
        self.assertEqual(payment.status, Payment.Status.CREATED)
        self.assertNotEqual(make_payment(self.user).public_id, payment.public_id)

    def test_amount_must_be_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_payment(self.user, amount=Decimal("0"))

    def test_provider_payment_id_is_unique_per_provider(self):
        make_payment(self.user, external_id="tx-1")
        make_payment(self.user, external_id="")
        make_payment(self.user, external_id="")
        make_payment(self.user, provider=Payment.Provider.NOWPAYMENTS, external_id="tx-1")

        with self.assertRaises(IntegrityError), transaction.atomic():
            make_payment(self.user, external_id="tx-1")

    def test_repeated_webhook_cannot_be_logged_twice(self):
        payment = make_payment(self.user)
        PaymentEvent.objects.create(provider="cloudpayments", payment=payment, event_type="pay", dedup_key="pay:1")

        with self.assertRaises(IntegrityError), transaction.atomic():
            PaymentEvent.objects.create(provider="cloudpayments", payment=payment, event_type="pay", dedup_key="pay:1")

    def test_payer_with_payments_cannot_be_hard_deleted(self):
        make_payment(self.user)

        with self.assertRaises(ProtectedError):
            self.user.delete()


@override_settings(STORAGES=TEST_STORAGES)
class PaymentAdminTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username="payments-admin",
            password="safe-test-password",
            email="payments-admin@example.com",
        )
        self.payment = make_payment(self.admin_user, external_id="tx-admin")
        PaymentEvent.objects.create(provider="cloudpayments", payment=self.payment, event_type="pay", dedup_key="pay:tx-admin")
        self.client.force_login(self.admin_user)

    def test_payments_are_read_only(self):
        changelist = self.client.get(reverse("admin:payments_payment_changelist"))
        change = self.client.get(reverse("admin:payments_payment_change", args=[self.payment.pk]))

        self.assertContains(changelist, str(self.payment.public_id))
        self.assertEqual(change.status_code, 200)
        self.assertNotContains(change, 'name="_save"')
        self.assertEqual(self.client.get(reverse("admin:payments_payment_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:payments_paymentevent_changelist")).status_code, 200)

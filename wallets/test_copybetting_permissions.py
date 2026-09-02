from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from cabinet.models import User
from wallets.models import CopyBettingSubscription


class CopyBettingPermissionTests(TestCase):
    def setUp(self):
        self.source_capper = User.objects.create_user(
            username="source-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.viewer_capper = User.objects.create_user(
            username="viewer-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(
            username="copy-reader-permissions",
            password="safe-test-password",
            role=User.Role.READER,
        )

    def _subscription(self, user):
        return CopyBettingSubscription.objects.create(
            user=user,
            analyst=self.source_capper,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
        )

    def test_capper_cannot_open_another_cappers_copybetting_setup(self):
        self.client.force_login(self.viewer_capper)

        response = self.client.get(
            reverse("wallets:copybetting_setup", kwargs={"analyst_id": self.source_capper.pk})
        )

        self.assertEqual(response.status_code, 403)

    def test_capper_cannot_create_copybetting_subscription(self):
        with self.assertRaisesMessage(
            ValidationError,
            "Капперы не могут использовать копибеттинг.",
        ):
            self._subscription(self.viewer_capper)

        self.assertFalse(
            CopyBettingSubscription.objects.filter(user=self.viewer_capper).exists()
        )

    def test_existing_copybetting_stops_when_reader_becomes_capper(self):
        subscription = self._subscription(self.reader)
        self.assertEqual(subscription.status, CopyBettingSubscription.Status.ACTIVE)

        self.reader.role = User.Role.ANALYST
        self.reader.save(update_fields=["role"])

        subscription.refresh_from_db()
        self.assertEqual(subscription.status, CopyBettingSubscription.Status.STOPPED)
        self.assertIsNotNone(subscription.stopped_at)

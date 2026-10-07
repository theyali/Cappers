from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from cabinet.models import User
from game.models import PredictionCoupon
from wallets.models import CopiedBet
from wallets.services import activate_copybetting
from wallets.tasks import copy_coupon_to_followers


class CopyTaskTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(username="copy-task-capper", password="safe-test-password", role=User.Role.ANALYST)
        self.reader = User.objects.create_user(username="copy-task-reader", password="safe-test-password")
        activate_copybetting(user=self.reader, analyst=self.analyst, bank_amount=Decimal("1000"), stake_percent=Decimal("10"))

    def _publish(self):
        return PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100"),
            possible_payout=Decimal("200"),
            confidence=70,
            published_at=timezone.now(),
        )

    def test_copies_are_made_once_after_the_publish_commits(self):
        with patch("wallets.signals.copy_coupon_to_followers", wraps=copy_coupon_to_followers) as task:
            with self.captureOnCommitCallbacks(execute=True):
                coupon = self._publish()
                # Nothing is copied inside the publishing transaction.
                self.assertFalse(CopiedBet.objects.exists())
            with self.captureOnCommitCallbacks(execute=True):
                coupon.save()

        task.assert_called_once_with(coupon.pk)
        self.assertEqual(CopiedBet.objects.get().source_coupon, coupon)

    def test_copying_runs_in_a_worker(self):
        with (
            patch("wallets.signals.sys.argv", ["manage.py", "runserver"]),
            patch("wallets.signals.copy_coupon_to_followers") as task,
            self.captureOnCommitCallbacks(execute=True),
        ):
            coupon = self._publish()

        task.delay.assert_called_once_with(coupon.pk)
        task.assert_not_called()

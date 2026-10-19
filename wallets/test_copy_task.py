from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone

from cabinet.models import AnalystFollow, AnalystPaidSubscription, User
from game.models import PredictionCoupon
from wallets.models import CoinWallet, CopiedBet, CopyBettingSubscription
from wallets.services import activate_copybetting, copy_published_coupon
from wallets.tasks import copy_coupon_to_followers


class CopyTaskTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(username="copy-task-capper", password="safe-test-password", role=User.Role.ANALYST)
        self.reader = User.objects.create_user(username="copy-task-reader", password="safe-test-password")
        activate_copybetting(user=self.reader, analyst=self.analyst, bank_amount=Decimal("1000"), stake_percent=Decimal("10"))

    def _publish(self, audience="free"):
        return PredictionCoupon.objects.create(
            author=self.analyst, audience=audience,
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

    def test_paid_copies_require_current_subscription_not_ordinary_follow(self):
        AnalystFollow.objects.create(follower=self.reader, analyst=self.analyst)
        wallet = CoinWallet.objects.get(user=self.reader)
        original = wallet.balance
        coupon = self._publish(audience="paid")
        self.assertEqual(copy_published_coupon(coupon), [])
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, original)
        other = User.objects.create_user(username="another-paid-author", role=User.Role.ANALYST)
        paid = AnalystPaidSubscription.objects.create(subscriber=self.reader, analyst=other, price=100, expires_at=timezone.now()+timedelta(days=1))
        self.assertEqual(copy_published_coupon(coupon), [])
        paid.analyst = self.analyst
        paid.save(update_fields=["analyst"])
        self.assertEqual(len(copy_published_coupon(coupon)), 1)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, original-100)
        paid.expires_at = timezone.now()-timedelta(seconds=1)
        paid.save(update_fields=["expires_at"])
        self.assertEqual(copy_published_coupon(self._publish(audience="paid")), [])
        paid.expires_at = timezone.now()+timedelta(days=2)
        paid.starts_at = timezone.now()+timedelta(days=1)
        paid.save(update_fields=["expires_at", "starts_at"])
        self.assertEqual(copy_published_coupon(self._publish(audience="paid")), [])
        self.assertEqual(len(copy_published_coupon(self._publish())), 1)

    def test_under_minimum_legacy_stake_is_not_copied_or_charged(self):
        subscription = CopyBettingSubscription.objects.get(user=self.reader)
        wallet = CoinWallet.objects.get(user=self.reader)
        before = wallet.balance
        for changes in ({"stake_percent": 1}, {"stake_percent": 10, "max_single_stake": 99}):
            CopyBettingSubscription.objects.filter(pk=subscription.pk).update(**changes)
            self.assertEqual(copy_published_coupon(self._publish()), [])
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, before)
        with self.assertRaises(ValidationError):
            activate_copybetting(user=self.reader, analyst=self.analyst, bank_amount=1000, stake_percent=1)
        with self.assertRaises(ValidationError):
            activate_copybetting(user=self.reader, analyst=self.analyst, bank_amount=1000, stake_percent=10, min_total_coefficient=0)

from datetime import timedelta
from decimal import Decimal

from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystFollow, AnalystPaidSubscription, AnalystProfile, User
from game.models import PredictionCoupon
from notifications.models import TelegramAccount
from wallets.models import CoinTransaction, CopyBettingSubscription, RealBalanceTransaction
from wallets.services import activate_copybetting, credit_real_balance, ensure_real_balance


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class AccountDeletionTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="leaving-capper",
            password="safe-test-password",
            email="leaving@example.com",
            first_name="Иван",
            last_name="Петров",
            role=User.Role.ANALYST,
            telegram_id=555000111,
            telegram_username="leaving_tg",
        )
        self.profile, _ = AnalystProfile.objects.get_or_create(user=self.analyst)
        self.profile.display_name = "Иван Петров"
        self.profile.bio = "Пишу прогнозы"
        self.profile.instagram = "ivan.petrov"
        self.profile.save()
        self.reader = User.objects.create_user(username="leaving-reader", password="safe-test-password")
        TelegramAccount.objects.create(user=self.analyst, chat_id="555000111", username="leaving_tg")
        AnalystFollow.objects.create(follower=self.reader, analyst=self.analyst)
        activate_copybetting(
            user=self.reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000"),
            stake_percent=Decimal("10"),
        )
        self.coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100"),
            possible_payout=Decimal("200"),
            confidence=70,
        )
        self.client.force_login(self.analyst)

    def _delete(self):
        return self.client.post(reverse("cabinet:delete_account"), {"confirmation": "delete-account"})

    def test_account_is_anonymized_and_financial_history_is_kept(self):
        transactions_before = CoinTransaction.objects.filter(user=self.analyst).count()

        response = self._delete()

        self.assertRedirects(response, reverse("front:index"), fetch_redirect_response=False)
        user = User.objects.get(pk=self.analyst.pk)
        self.assertEqual(user.username, f"deleted-{user.pk}")
        self.assertEqual((user.email, user.first_name, user.last_name, user.telegram_username), ("", "", "", ""))
        self.assertIsNone(user.telegram_id)
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertIsNotNone(user.deleted_at)
        self.assertEqual(CoinTransaction.objects.filter(user=user).count(), transactions_before)
        self.assertTrue(PredictionCoupon.objects.filter(pk=self.coupon.pk).exists())

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.display_name, "Удалённый пользователь")
        self.assertEqual((self.profile.bio, self.profile.instagram), ("", ""))
        self.assertFalse(self.profile.is_public)
        self.assertFalse(TelegramAccount.objects.filter(user=user).exists())
        self.assertFalse(AnalystFollow.objects.filter(analyst=user).exists())
        self.assertEqual(
            CopyBettingSubscription.objects.get(analyst=user).status,
            CopyBettingSubscription.Status.STOPPED,
        )
        self.assertFalse(self.client.login(username="leaving-capper", password="safe-test-password"))

    def test_money_on_the_real_balance_blocks_deletion(self):
        balance = ensure_real_balance(self.analyst)
        balance.balance = Decimal("700.00")
        balance.save(update_fields=["balance", "updated_at"])

        page = self.client.get(reverse("cabinet:profile"), {"tab": "settings"})
        self.assertContains(page, "На реальном балансе 700 ₽: сначала выведите их.")
        self.assertNotContains(page, "Да, удалить аккаунт")

        self._delete()

        self.analyst.refresh_from_db()
        self.assertTrue(self.analyst.is_active)
        self.assertIsNone(self.analyst.deleted_at)

    def test_held_income_and_active_subscribers_block_deletion(self):
        credit_real_balance(
            self.analyst,
            Decimal("300.00"),
            RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
        )
        AnalystPaidSubscription.objects.create(
            subscriber=self.reader,
            analyst=self.analyst,
            price=Decimal("300.00"),
            duration_days=30,
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )

        self._delete()

        self.analyst.refresh_from_db()
        self.assertTrue(self.analyst.is_active)

    def test_hard_delete_is_refused(self):
        with self.assertRaises(ProtectedError):
            self.analyst.delete()

    def test_admin_action_deletes_accounts(self):
        admin_user = User.objects.create_superuser(
            username="deletion-admin",
            password="safe-test-password",
            email="deletion-admin@example.com",
        )
        self.client.force_login(admin_user)

        response = self.client.post(
            reverse("admin:cabinet_user_changelist"),
            {"action": "delete_accounts", "_selected_action": [self.analyst.pk]},
            follow=True,
        )

        self.assertContains(response, "Удалено аккаунтов: 1.")
        self.analyst.refresh_from_db()
        self.assertIsNotNone(self.analyst.deleted_at)

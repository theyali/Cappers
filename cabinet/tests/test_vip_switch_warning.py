from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User, UserVipSubscription, VipPlan
from cabinet.vip import purchase_vip, vip_switch_warning
from wallets.services import ensure_real_balance


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class VipSwitchWarningTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="vip-switch-user",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.monthly = VipPlan.objects.create(title="VIP 30", duration_days=30, price_rub=Decimal("300"))
        self.weekly = VipPlan.objects.create(title="VIP 7", duration_days=7, price_rub=Decimal("100"))
        balance = ensure_real_balance(self.user)
        balance.balance = Decimal("1000")
        balance.save(update_fields=["balance", "updated_at"])
        purchase_vip(self.user, self.monthly)
        # Ten of thirty paid days are used: twenty days worth 200 ₽ remain.
        UserVipSubscription.objects.filter(user=self.user).update(
            starts_at=timezone.now() - timedelta(days=10),
            ends_at=timezone.now() + timedelta(days=20),
        )

    def test_warning_names_the_burned_days_and_money(self):
        warning = vip_switch_warning(self.user)

        self.assertIn("Неиспользованные 20 дней", warning)
        self.assertIn("примерно 200 ₽", warning)

    def test_scheduled_periods_count_too(self):
        purchase_vip(self.user, self.monthly)

        self.assertIn("примерно 500 ₽", vip_switch_warning(self.user))

    def test_free_vip_days_are_reported_without_money(self):
        UserVipSubscription.objects.filter(user=self.user).update(source=UserVipSubscription.Source.ADMIN)
        user = User.objects.create_user(username="vip-gift-user", password="safe-test-password", role=User.Role.ANALYST)
        UserVipSubscription.objects.create(
            user=user,
            plan=self.monthly,
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=3, hours=1),
            duration_days=3,
            source=UserVipSubscription.Source.TOURNAMENT,
        )

        self.assertEqual(vip_switch_warning(user), "Неиспользованные 3 дня текущего VIP сгорят без возврата.")

    def test_unconfirmed_switch_is_refused_with_the_losses(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("cabinet:vip_purchase"),
            {"plan_id": self.weekly.pk},
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("примерно 200 ₽", response.json()["error"])
        self.assertIn("Подтвердите переход", response.json()["error"])

    def test_switch_dialog_shows_the_losses(self):
        self.client.force_login(self.user)

        page = self.client.get(reverse("cabinet:vip_plans"))

        self.assertContains(page, "Из них оплачено примерно 200 ₽, эти деньги не возвращаются.")

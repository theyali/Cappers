import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from back.models import WebsiteSettings
from cabinet.models import AnalystProfile, BonusEvent, ReferralBonusSettings, ReferralVisit, User
from cabinet.paid_predictions import subscribe_to_paid_predictions
from cabinet.services.referral_bonuses import REGISTRATION_BONUS_TITLE
from wallets.models import RealBalanceTransaction
from wallets.services import ensure_real_balance


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class _CaptchaResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def _analyst(username):
    user = User.objects.create_user(username=username, password="safe-test-password", role=User.Role.ANALYST)
    profile, _ = AnalystProfile.objects.get_or_create(user=user)
    return user, profile


class ReferralIncomeTests(TestCase):
    def setUp(self):
        settings = WebsiteSettings.load()
        settings.platform_fee_30_days_percent = Decimal("20")
        settings.referral_subscription_percent = Decimal("10")
        settings.income_hold_days = 0
        settings.save()
        self.seller, profile = _analyst("ref-seller")
        profile.paid_predictions_enabled = True
        profile.paid_predictions_price = Decimal("1000.00")
        profile.save()
        self.referrer, _ = _analyst("ref-referrer")
        self.buyer = User.objects.create_user(username="ref-buyer", password="safe-test-password")
        balance = ensure_real_balance(self.buyer)
        balance.balance = Decimal("5000.00")
        balance.save(update_fields=["balance", "updated_at"])

    def _invite(self, referrer, *, registered_at=None):
        return ReferralVisit.objects.create(
            referrer=referrer,
            visitor=self.buyer,
            session_key=f"ref-{referrer.pk}",
            registered_at=registered_at or timezone.now(),
        )

    def _referral_income(self, user):
        return list(
            RealBalanceTransaction.objects.filter(
                user=user,
                kind=RealBalanceTransaction.Kind.REFERRAL_SUBSCRIPTION,
            ).values_list("amount", flat=True)
        )

    def test_referral_share_is_taken_from_the_platform_fee(self):
        self._invite(self.referrer)

        subscribe_to_paid_predictions(self.buyer, self.seller)

        # Fee is 20% of 1000 = 200; the referrer gets 10% of the fee, not of the price.
        self.assertEqual(self._referral_income(self.referrer), [Decimal("20.00")])
        self.assertEqual(
            RealBalanceTransaction.objects.get(
                user=self.seller,
                kind=RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
            ).amount,
            Decimal("800.00"),
        )

    def test_seller_gets_no_referral_share_of_own_sale(self):
        self._invite(self.seller)

        subscribe_to_paid_predictions(self.buyer, self.seller)

        self.assertEqual(self._referral_income(self.seller), [])

    def test_referral_income_ends_after_the_configured_period(self):
        self._invite(self.referrer, registered_at=timezone.now() - timedelta(days=400))

        subscribe_to_paid_predictions(self.buyer, self.seller)

        self.assertEqual(self._referral_income(self.referrer), [])

    def test_zero_fee_pays_no_share_but_keeps_first_subscription_bonus(self):
        settings = WebsiteSettings.load()
        settings.platform_fee_30_days_percent = Decimal("0")
        settings.save()
        ReferralBonusSettings.objects.update_or_create(
            pk=1,
            defaults={"is_enabled": True, "first_subscription_reward_coins": 50},
        )
        self._invite(self.referrer)

        subscribe_to_paid_predictions(self.buyer, self.seller)

        self.assertEqual(self._referral_income(self.referrer), [])
        self.assertTrue(BonusEvent.objects.filter(user=self.referrer, event_type=BonusEvent.EventType.REFERRAL).exists())


@override_settings(STORAGES=TEST_STORAGES)
class RegistrationProtectionTests(TestCase):
    def setUp(self):
        self.referrer, _ = _analyst("guard-referrer")
        ReferralBonusSettings.objects.update_or_create(
            pk=1,
            defaults={"is_enabled": True, "registration_reward_coins": 30, "registration_reward_xp": 0},
        )

    def _register(self, username, **extra):
        return self.client.post(
            reverse("cabinet:register"),
            {
                "account_type": "user",
                "role": User.Role.READER,
                "username": username,
                "email": f"{username}@example.com",
                "first_name": "Guard",
                "last_name": "Reader",
                "password1": "GuardPass123!",
                "password2": "GuardPass123!",
                "accept_terms": "on",
                **extra,
            },
            REMOTE_ADDR="203.0.113.7",
        )

    def _registration_bonuses(self):
        return BonusEvent.objects.filter(user=self.referrer, title=REGISTRATION_BONUS_TITLE)

    def test_registration_bonus_waits_for_email_confirmation(self):
        self.client.get(
            reverse(
                "front:capper_referral_code",
                kwargs={"username": self.referrer.username, "code": self.referrer.referral_code},
            )
        )

        self._register("guard-invited")

        invited = User.objects.get(username="guard-invited")
        self.assertEqual(invited.registration_ip, "203.0.113.7")
        self.assertFalse(self._registration_bonuses().exists())

        verify_url = next(word for word in mail.outbox[-1].body.split() if "/verify/" in word)
        self.client.get(verify_url)

        self.assertEqual(self._registration_bonuses().count(), 1)

    def test_registrations_from_one_ip_are_limited(self):
        for index in range(5):
            self.assertEqual(self._register(f"guard-burst-{index}").status_code, 302)

        response = self._register("guard-burst-5")

        self.assertContains(response, "Слишком много регистраций")
        self.assertFalse(User.objects.filter(username="guard-burst-5").exists())

    @override_settings(SMARTCAPTCHA_CLIENT_KEY="client-key", SMARTCAPTCHA_SERVER_KEY="server-key")
    def test_captcha_is_required_when_configured(self):
        page = self.client.get(reverse("cabinet:register"), {"type": "user"})
        self.assertContains(page, 'data-sitekey="client-key"')

        response = self._register("guard-bot")
        self.assertContains(response, "Подтвердите, что вы не робот.")

        failed = self._captcha_response({"status": "failed"})
        with patch("cabinet.services.registration_guard.urllib.request.urlopen", return_value=failed):
            response = self._register("guard-bot", **{"smart-token": "bad"})
        self.assertContains(response, "Подтвердите, что вы не робот.")
        self.assertFalse(User.objects.filter(username="guard-bot").exists())

        passed = self._captcha_response({"status": "ok"})
        with patch("cabinet.services.registration_guard.urllib.request.urlopen", return_value=passed):
            response = self._register("guard-human", **{"smart-token": "good"})
        self.assertEqual(response.status_code, 302)

    @staticmethod
    def _captcha_response(payload):
        return _CaptchaResponse(payload)


@override_settings(STORAGES=TEST_STORAGES, TG_BOT_TOKEN="123456:test-token")
class TelegramReferralTests(TestCase):
    def test_telegram_sign_up_keeps_the_referral(self):
        referrer, _ = _analyst("tg-referrer")
        ReferralBonusSettings.objects.update_or_create(
            pk=1,
            defaults={"is_enabled": True, "registration_reward_coins": 30, "registration_reward_xp": 0},
        )
        self.client.get(
            reverse(
                "front:capper_referral_code",
                kwargs={"username": referrer.username, "code": referrer.referral_code},
            )
        )
        payload = {"id": "777000111", "first_name": "Tg", "username": "tg_invited", "auth_date": str(int(time.time()))}
        data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
        secret = hashlib.sha256(b"123456:test-token").digest()
        payload["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()

        with patch("cabinet.telegram_auth.connect_verified_telegram_account"):
            self.client.get(reverse("cabinet:telegram_login"), payload)

        invited = User.objects.get(telegram_id=777000111)
        self.assertTrue(ReferralVisit.objects.filter(referrer=referrer, visitor=invited, registered_at__isnull=False).exists())
        # Telegram confirms the account, so the referrer is rewarded at once.
        self.assertTrue(BonusEvent.objects.filter(user=referrer, title=REGISTRATION_BONUS_TITLE).exists())

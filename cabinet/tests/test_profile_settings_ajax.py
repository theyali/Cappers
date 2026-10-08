from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from cabinet.models import AnalystProfile, User, UserSportPreference
from cabinet.services.verification import MIN_PUBLISHED_COUPONS, verification_state
from game.models import PredictionCoupon, Sport

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class CapperSetupMixin:
    def setUp(self):
        self.sport = Sport.objects.create(code="football-ajax", name="Football", name_ru="Футбол")
        self.user = User.objects.create_user(
            username="ajax-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
            first_name="Иван",
            last_name="Петров",
        )
        # A profile is created for every capper by a signal.
        self.profile, _ = AnalystProfile.objects.update_or_create(
            user=self.user,
            defaults={
                "display_name": "Иван Прогноз",
                "specialization": "Футбол, тоталы",
                "bio": "Разбираю АПЛ.",
                "telegram_channel": "@ivan_tips",
            },
        )
        UserSportPreference.objects.create(user=self.user, sport=self.sport)
        self.client.force_login(self.user)

    def publish_coupons(self, count):
        for _ in range(count):
            PredictionCoupon.objects.create(
                author=self.user,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                audience=PredictionCoupon.Audience.FREE,
                total_stake=Decimal("100.00"),
                possible_payout=Decimal("180.00"),
                confidence=70,
            )

    def settings_payload(self, **overrides):
        payload = {
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "display_name": self.profile.display_name,
            "specialization": self.profile.specialization,
            "bio": self.profile.bio,
            "telegram_channel": self.profile.telegram_channel,
            "paid_predictions_price": "0",
            "is_public": "on",
            "sports": [self.sport.pk],
        }
        payload.update(overrides)
        return payload


@override_settings(STORAGES=TEST_STORAGES)
class ProfileSettingsAjaxTests(CapperSetupMixin, TestCase):
    def test_ajax_save_returns_json_instead_of_redirect(self):
        response = self.client.post(
            reverse("cabinet:profile"),
            self.settings_payload(first_name="Пётр", display_name="Пётр Прогноз"),
            **AJAX,
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["profile_name"], "Пётр Прогноз")
        self.assertIn("data-profile-verification", data["verification_html"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Пётр")
        # A background save must not leave a flash message for the next page.
        self.assertFalse(list(response.wsgi_request._messages))

    def test_ajax_save_returns_errors_keyed_by_input_name(self):
        response = self.client.post(
            reverse("cabinet:profile"),
            self.settings_payload(sports=[]),
            **AJAX,
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("sports", data["errors"])

    def test_regular_post_still_redirects(self):
        response = self.client.post(reverse("cabinet:profile"), self.settings_payload())

        self.assertRedirects(response, f"{reverse('cabinet:profile')}?tab=settings", fetch_redirect_response=False)

    def test_quick_access_ajax_save_returns_new_menu_grid(self):
        response = self.client.post(
            reverse("cabinet:profile"),
            {"profile_settings_action": "mobile_quick_access", "items": ["profile", "notifications"]},
            **AJAX,
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("data-mobile-quick-access-grid", data["quick_access_html"])

    def test_quick_access_ajax_errors(self):
        response = self.client.post(
            reverse("cabinet:profile"),
            {"profile_settings_action": "mobile_quick_access"},
            **AJAX,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("items", response.json()["errors"])


@override_settings(STORAGES=TEST_STORAGES)
class CapperVerificationTests(CapperSetupMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user.avatar = "avatars/ajax-capper.png"
        self.user.save(update_fields=["avatar"])

    def request_badge(self):
        return self.client.post(reverse("cabinet:request_verification"), **AJAX)

    def test_button_appears_only_when_everything_is_filled(self):
        self.publish_coupons(MIN_PUBLISHED_COUPONS - 1)
        self.assertEqual(verification_state(self.user, self.profile)["status"], "incomplete")

        self.publish_coupons(1)
        self.assertEqual(verification_state(self.user, self.profile)["status"], "ready")

        response = self.client.get(f"{reverse('cabinet:profile')}?tab=settings")
        self.assertContains(response, "Запросить галочку")

    def test_each_requirement_blocks_the_badge(self):
        self.publish_coupons(MIN_PUBLISHED_COUPONS)
        missing = {
            "specialization": ("profile", "specialization", " "),
            "display_name": ("profile", "display_name", ""),
            "bio": ("profile", "bio", ""),
            "socials": ("profile", "telegram_channel", ""),
            "first_name": ("user", "first_name", ""),
            "last_name": ("user", "last_name", ""),
            "avatar": ("user", "avatar", ""),
        }
        for name, (target, field, value) in missing.items():
            with self.subTest(requirement=name):
                user = User.objects.get(pk=self.user.pk)
                profile = AnalystProfile.objects.get(pk=self.profile.pk)
                setattr(profile if target == "profile" else user, field, value)
                self.assertFalse(verification_state(user, profile)["can_request"])

        UserSportPreference.objects.filter(user=self.user).delete()
        self.assertFalse(verification_state(self.user, self.profile)["can_request"])

    def test_drafts_and_cancelled_coupons_do_not_count(self):
        self.publish_coupons(MIN_PUBLISHED_COUPONS - 1)
        for status in (PredictionCoupon.PublishedStatus.DRAFT, PredictionCoupon.PublishedStatus.CANCELED):
            PredictionCoupon.objects.create(
                author=self.user,
                published_status=status,
                audience=PredictionCoupon.Audience.FREE,
                total_stake=Decimal("100.00"),
                possible_payout=Decimal("180.00"),
                confidence=70,
            )

        response = self.request_badge()

        self.assertEqual(response.status_code, 400)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_verified)

    def test_request_grants_the_badge_at_once(self):
        self.publish_coupons(MIN_PUBLISHED_COUPONS)

        response = self.request_badge()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("capper-verified-bg", data["badge_html"])
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_verified)
        self.assertIsNotNone(self.profile.verification_requested_at)
        page = self.client.get(f"{reverse('cabinet:profile')}?tab=settings")
        self.assertContains(page, "capper-verified-badge")
        self.assertNotContains(page, "Запросить галочку")

    def test_badge_removed_by_admin_cannot_be_requested_again(self):
        self.publish_coupons(MIN_PUBLISHED_COUPONS)
        self.request_badge()
        AnalystProfile.objects.filter(pk=self.profile.pk).update(is_verified=False)

        response = self.request_badge()

        self.assertEqual(response.status_code, 400)
        self.assertIn("модератор", response.json()["message"])
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_verified)

    def test_readers_cannot_get_the_badge(self):
        reader = User.objects.create_user(username="ajax-reader", password="x", role=User.Role.READER)
        self.client.force_login(reader)

        response = self.request_badge()

        self.assertEqual(response.status_code, 400)
        self.assertFalse(AnalystProfile.objects.filter(user=reader).exists())

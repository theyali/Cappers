from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from django.test import TestCase, override_settings
from django.urls import reverse

from cabinet.models import AnalystProfile, PresetAvatar, User, UserSportPreference
from cabinet.services.verification import MIN_PUBLISHED_COUPONS, verification_state
from game.models import Country, PredictionCoupon, Sport

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class CapperSetupMixin:
    def setUp(self):
        self.sport = Sport.objects.create(code="football-ajax", name="Football", name_ru="Футбол")
        self.country = Country.objects.create(
            code="TS",
            name="Testland",
            name_ru="Тестовая страна",
        )
        self.user = User.objects.create_user(
            username="ajax-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
            first_name="Иван",
            last_name="Петров",
            email="ajax-capper@example.com",
            email_verified=True,
            gender=User.Gender.MALE,
            country=self.country,
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
            "gender": self.user.gender,
            "country": self.user.country_id or "",
            "paid_predictions_price": "0",
            "is_public": "on",
            "sports": [self.sport.pk],
        }
        payload.update(overrides)
        return payload


@override_settings(STORAGES=TEST_STORAGES)
class ProfileSettingsAjaxTests(CapperSetupMixin, TestCase):
    def test_personal_hero_uses_default_cover_for_every_role(self):
        reader = User.objects.create_user(username="cover-reader", role=User.Role.READER)
        for user in (self.user, reader):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(reverse("cabinet:profile"))
                self.assertContains(response, 'class="profile-hero-cover"', count=1)
                self.assertContains(response, 'src="/static/front/img/profile_default_cover.png"', count=1)
                self.assertNotContains(response, "public_hero/publ_5")

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

    def test_profile_gender_and_country_save_and_render_in_public_profile(self):
        country = Country.objects.create(
            code="AZ",
            name="Azerbaijan",
            name_ru="Азербайджан",
            logo="country/flags/az.webp",
        )
        response = self.client.get(reverse("cabinet:profile"), {"tab": "settings"})
        self.assertContains(response, 'name="gender"')
        self.assertContains(response, 'name="country"')

        response = self.client.post(
            reverse("cabinet:profile"),
            self.settings_payload(gender=User.Gender.MALE, country=str(country.pk)),
            **AJAX,
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.gender, User.Gender.MALE)
        self.assertEqual(self.user.country_id, country.pk)

        public_response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": self.user.username})
        )
        self.assertContains(public_response, "Азербайджан")
        self.assertContains(public_response, "country/flags/az.webp")
        self.assertContains(public_response, "Мужской")

    def test_invalid_country_is_rejected(self):
        response = self.client.post(
            reverse("cabinet:profile"),
            self.settings_payload(country="999999999"),
            **AJAX,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("country", response.json()["errors"])

    def test_reader_public_profile_shows_country_and_flag(self):
        country = Country.objects.create(
            code="AZ",
            name_ru="Азербайджан",
            logo="country/flags/az.webp",
        )
        reader = User.objects.create_user(
            username="public-reader",
            password="safe-test-password",
            role=User.Role.READER,
            gender=User.Gender.FEMALE,
            country=country,
        )
        response = self.client.get(
            reverse("cabinet:user_profile", kwargs={"username": reader.username})
        )
        self.assertContains(response, "Азербайджан")
        self.assertContains(response, "country/flags/az.webp")
        self.assertContains(response, "Женский")
        self.assertContains(response, 'class="expert-mobile expert-mobile--user"', count=1)
        self.assertContains(response, 'class="expert-mobile-card-bg"', count=1)
        self.assertContains(response, 'src="/static/front/img/profile_default_cover.png"', count=1)
        self.assertContains(response, 'class="expert-public-hero-art"', count=1)
        self.assertContains(response, 'aria-label="Активность пользователя"', count=1)
        self.assertNotContains(response, 'class="expert-mobile-follow"')

        self.client.force_login(reader)
        self_response = self.client.get(
            reverse("cabinet:user_profile", kwargs={"username": reader.username})
        )
        self.assertContains(self_response, 'class="expert-mobile-follow"', count=1)
        self.assertContains(self_response, "Мой кабинет", count=2)

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
            "email_verified": ("user", "email_verified", False),
            "country": ("user", "country", None),
            "gender": ("user", "gender", ""),
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


@override_settings(STORAGES=TEST_STORAGES)
class ProfileAvatarTests(CapperSetupMixin, TestCase):
    def setUp(self):
        super().setUp()
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings_override = override_settings(MEDIA_ROOT=media.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.user.gender = User.Gender.MALE
        self.user.save(update_fields=["gender"])

    def test_pending_capper_can_choose_avatar_in_first_onboarding_step(self):
        self.user.role = User.Role.READER
        self.user.save(update_fields=["role"])
        self.profile.is_public = False
        self.profile.save(update_fields=["is_public"])
        preset = self.create_preset("Аватар для каппера")
        inactive = self.create_preset("Неактивный аватар", active=False)
        url = reverse("cabinet:capper_onboarding", kwargs={"step": 1})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-avatar-modal-open')
        self.assertContains(response, 'id="profile-avatar-modal"', count=1)
        self.assertContains(response, f'data-avatar-id="{preset.pk}"')
        self.assertNotContains(response, f'data-avatar-id="{inactive.pk}"')
        self.assertContains(response, 'front/js/profile.js')
        self.assertContains(response, "Профиль каппера")
        html = response.content.decode()
        self.assertLess(html.index('</form>', html.index('capper-onboarding-form')), html.index('id="profile-avatar-modal"'))
        saved = self.client.post(reverse("cabinet:avatar_upload"), {"preset_id": preset.pk})
        self.assertEqual(saved.status_code, 200)
        self.user.refresh_from_db()
        saved_name = self.user.avatar.name
        self.assertTrue(saved_name)
        self.assertEqual(self.user.role, User.Role.READER)
        next_step = self.client.post(url, {"first_name": "Иван", "last_name": "Иванов", "display_name": "Новый каппер"})
        self.assertRedirects(next_step, reverse("cabinet:capper_onboarding", kwargs={"step": 2}), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar.name, saved_name)
        self.assertNotContains(self.client.get(reverse("cabinet:capper_onboarding", kwargs={"step": 2})), 'id="profile-avatar-modal"')

    def test_pending_capper_can_upload_own_avatar(self):
        self.user.role = User.Role.READER
        self.user.save(update_fields=["role"])
        self.profile.is_public = False
        self.profile.save(update_fields=["is_public"])
        response = self.client.post(reverse("cabinet:avatar_upload"), {"avatar": self.image_upload("onboarding.png")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["avatar_url"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.avatar.name)
        self.assertEqual(self.user.role, User.Role.READER)

    @staticmethod
    def image_upload(name="avatar.png"):
        image = BytesIO()
        Image.new("RGB", (32, 32), "#0b56fa").save(image, format="PNG")
        return SimpleUploadedFile(name, image.getvalue(), content_type="image/png")

    def create_preset(self, title="Синий", gender=PresetAvatar.Gender.MALE, active=True):
        return PresetAvatar.objects.create(
            title=title,
            gender=gender,
            is_active=active,
            image=self.image_upload(f"{title}.png"),
        )

    def test_modal_shows_all_active_presets_with_gender_filters(self):
        male = self.create_preset()
        self.create_preset("Женский", gender=PresetAvatar.Gender.FEMALE)
        self.create_preset("Универсальный", gender=PresetAvatar.Gender.ALL)
        response = self.client.get(reverse("cabinet:profile"), {"tab": "profile"})
        self.assertContains(response, 'id="profile-avatar-modal"')
        self.assertContains(response, 'data-avatar-modal-open')
        self.assertContains(response, male.title)
        self.assertContains(response, "Универсальный")
        self.assertContains(response, 'data-avatar-filter="female"')
        self.assertContains(response, 'title="Женский"')

    def test_preset_image_is_copied_and_custom_upload_still_works(self):
        preset = self.create_preset()
        endpoint = reverse("cabinet:avatar_upload")
        response = self.client.post(endpoint, {"preset_id": str(preset.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.user.refresh_from_db()
        previous_image = self.user.avatar.name
        self.assertNotEqual(previous_image, preset.image.name)
        with self.user.avatar.open("rb") as saved, preset.image.open("rb") as original:
            self.assertEqual(saved.read(), original.read())

        response = self.client.post(endpoint, {"avatar": self.image_upload("own.png")})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.avatar.name, previous_image)
        self.assertTrue(self.user.avatar.storage.exists(self.user.avatar.name))
        self.assertFalse(self.user.avatar.storage.exists(previous_image))

    def test_rejects_inactive_and_invalid_presets_but_allows_any_gender(self):
        female = self.create_preset("Женский", gender=PresetAvatar.Gender.FEMALE)
        inactive = self.create_preset("Скрытый", active=False)
        endpoint = reverse("cabinet:avatar_upload")
        for preset_id in (str(inactive.pk), "bad", "9" * 100):
            with self.subTest(preset_id=preset_id):
                response = self.client.post(endpoint, {"preset_id": preset_id})
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
        self.user.refresh_from_db()
        self.assertFalse(bool(self.user.avatar))
        self.assertEqual(self.client.post(endpoint, {"preset_id": str(female.pk)}).status_code, 200)

    def test_reader_can_change_avatar_and_unset_gender_sees_all(self):
        reader = User.objects.create_user(
            username="avatar-reader", password="safe-test-password", role=User.Role.READER
        )
        self.client.force_login(reader)
        preset = self.create_preset("Любой", gender=PresetAvatar.Gender.FEMALE)
        response = self.client.get(reverse("cabinet:profile"))
        self.assertContains(response, 'data-avatar-modal-open')
        self.assertContains(response, f'data-avatar-id="{preset.pk}"')
        response = self.client.post(reverse("cabinet:avatar_upload"), {"preset_id": str(preset.pk)})
        self.assertEqual(response.status_code, 200)
        reader.refresh_from_db()
        self.assertTrue(bool(reader.avatar))

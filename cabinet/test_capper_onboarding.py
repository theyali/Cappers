from django.test import TestCase
from django.urls import reverse

from .models import AnalystProfile, User


class CapperRegistrationTests(TestCase):
    def test_register_starts_with_visual_account_type_choice(self):
        response = self.client.get(reverse("cabinet:register"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Я пользователь")
        self.assertContains(response, "Я каппер")
        self.assertNotContains(response, "<select", html=False)

    def test_capper_registration_stays_reader_until_onboarding_finishes(self):
        response = self.client.post(
            reverse("cabinet:register"),
            {
                "account_type": "capper",
                "role": User.Role.ANALYST,
                "username": "new-capper",
                "email": "capper@example.com",
                "first_name": "Новый",
                "last_name": "Каппер",
                "password1": "Strong-test-password-492!",
                "password2": "Strong-test-password-492!",
            },
        )

        user = User.objects.get(username="new-capper")
        profile = AnalystProfile.objects.get(user=user)
        self.assertEqual(user.role, User.Role.READER)
        self.assertFalse(profile.is_public)
        self.assertIsNone(profile.onboarding_completed_at)
        self.assertRedirects(
            response,
            reverse("cabinet:capper_onboarding", kwargs={"step": 1}),
        )

    def test_reader_registration_goes_to_regular_profile(self):
        response = self.client.post(
            reverse("cabinet:register"),
            {
                "account_type": "user",
                "role": User.Role.READER,
                "username": "new-reader",
                "email": "reader@example.com",
                "first_name": "Обычный",
                "last_name": "Пользователь",
                "password1": "Strong-test-password-493!",
                "password2": "Strong-test-password-493!",
            },
        )

        user = User.objects.get(username="new-reader")
        self.assertEqual(user.role, User.Role.READER)
        self.assertFalse(AnalystProfile.objects.filter(user=user).exists())
        self.assertRedirects(response, reverse("cabinet:profile"))


class CapperOnboardingTests(TestCase):
    def setUp(self):
        self.reader = User.objects.create_user(
            username="telegram-reader",
            password="safe-test-password",
            role=User.Role.READER,
            telegram_id=712345,
            telegram_username="telegram_alias",
        )
        self.client.force_login(self.reader)

    def test_telegram_reader_can_start_capper_flow_without_new_registration(self):
        response = self.client.get(reverse("cabinet:become_capper_start"))

        profile = AnalystProfile.objects.get(user=self.reader)
        self.assertEqual(profile.telegram_account, "@telegram_alias")
        self.assertFalse(profile.is_public)
        self.assertEqual(self.reader.role, User.Role.READER)
        self.assertRedirects(
            response,
            reverse("cabinet:capper_onboarding", kwargs={"step": 1}),
        )

    def test_cannot_skip_required_profile_steps_and_activate(self):
        AnalystProfile.objects.create(
            user=self.reader,
            display_name="Telegram Reader",
            is_public=False,
        )

        response = self.client.get(
            reverse("cabinet:capper_onboarding", kwargs={"step": 5})
        )

        self.assertRedirects(
            response,
            reverse("cabinet:capper_onboarding", kwargs={"step": 2}),
        )
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.role, User.Role.READER)

    def test_completed_profile_is_promoted_only_on_final_confirmation(self):
        profile = AnalystProfile.objects.create(
            user=self.reader,
            display_name="TG Expert",
            specialization="Футбольная аналитика",
            bio="Проверяю форму команд, составы и движения линии перед матчами.",
            favorite_sports="Футбол",
            favorite_leagues="АПЛ, Ла Лига",
            telegram_account="@telegram_alias",
            is_public=False,
        )

        response = self.client.post(
            reverse("cabinet:capper_onboarding", kwargs={"step": 5}),
            {"action": "profile"},
        )

        self.reader.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(self.reader.role, User.Role.ANALYST)
        self.assertTrue(profile.is_public)
        self.assertIsNotNone(profile.onboarding_completed_at)
        self.assertRedirects(
            response,
            reverse("cabinet:expert_profile", kwargs={"username": self.reader.username}),
        )

    def test_final_action_can_send_new_capper_to_first_prediction(self):
        profile = AnalystProfile.objects.create(
            user=self.reader,
            display_name="TG Expert",
            specialization="Футбольная аналитика",
            bio="Системный разбор prematch матчей.",
            favorite_sports="Футбол",
            is_public=False,
        )

        response = self.client.post(
            reverse("cabinet:capper_onboarding", kwargs={"step": 5}),
            {"action": "prediction"},
        )

        profile.refresh_from_db()
        self.assertTrue(profile.is_public)
        self.assertRedirects(
            response,
            f"{reverse('game:match_list')}?scope=prematch&onboarding=done",
        )

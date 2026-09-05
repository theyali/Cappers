from django.test import TestCase
from django.urls import reverse

from cabinet.models import AnalystProfile, User

from .models import BotAccount


class BotAccountManagementViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin_bot_manager",
            password="test-password",
            is_staff=True,
        )
        self.bot_user = User.objects.create_user(
            username="reader_bot",
            password="test-password",
            role=User.Role.READER,
        )
        self.bot = BotAccount.objects.create(
            user=self.bot_user,
            kind=BotAccount.Kind.READER,
        )

    def test_staff_can_open_bot_management(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("bots:manage_accounts"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Пользователи-боты")
        self.assertContains(response, "reader_bot")
        self.assertContains(response, 'name="bot_id"')
        self.assertContains(response, f'name="bot-{self.bot.pk}-username"')
        self.assertContains(response, f'for="id_bot-{self.bot.pk}-avatar"')

    def test_regular_user_cannot_open_bot_management(self):
        regular_user = User.objects.create_user(
            username="regular_user",
            password="test-password",
        )
        self.client.force_login(regular_user)

        response = self.client.get(reverse("bots:manage_accounts"))

        self.assertEqual(response.status_code, 403)

    def test_staff_can_update_bot_identity_from_table_row(self):
        self.client.force_login(self.admin)
        prefix = f"bot-{self.bot.pk}"

        response = self.client.post(
            reverse("bots:manage_accounts"),
            {
                "bot_id": self.bot.pk,
                f"{prefix}-username": "reader_bot_new",
                f"{prefix}-first_name": "Иван",
                f"{prefix}-last_name": "Ботов",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.bot_user.refresh_from_db()
        self.assertEqual(self.bot_user.username, "reader_bot_new")
        self.assertEqual(self.bot_user.first_name, "Иван")
        self.assertEqual(self.bot_user.last_name, "Ботов")

    def test_invalid_row_is_rendered_with_errors(self):
        other_user = User.objects.create_user(
            username="taken_login",
            password="test-password",
        )
        self.client.force_login(self.admin)
        prefix = f"bot-{self.bot.pk}"

        response = self.client.post(
            reverse("bots:manage_accounts"),
            {
                "bot_id": self.bot.pk,
                f"{prefix}-username": other_user.username,
                f"{prefix}-first_name": "Иван",
                f"{prefix}-last_name": "Ботов",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Пользователь с таким логином уже существует.")

    def test_expert_display_name_is_synced(self):
        expert_user = User.objects.create_user(
            username="expert_bot",
            password="test-password",
            role=User.Role.ANALYST,
        )
        expert_bot = BotAccount.objects.create(
            user=expert_user,
            kind=BotAccount.Kind.EXPERT,
        )
        self.client.force_login(self.admin)
        prefix = f"bot-{expert_bot.pk}"

        response = self.client.post(
            reverse("bots:manage_accounts"),
            {
                "bot_id": expert_bot.pk,
                f"{prefix}-username": "expert_bot",
                f"{prefix}-first_name": "Алексей",
                f"{prefix}-last_name": "Бот",
            },
        )

        self.assertEqual(response.status_code, 302)
        analyst_profile = AnalystProfile.objects.get(user=expert_user)
        self.assertEqual(analyst_profile.display_name, "Алексей Бот")

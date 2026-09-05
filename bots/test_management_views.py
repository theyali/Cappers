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
        self.assertContains(response, "@reader_bot")

    def test_regular_user_cannot_open_bot_management(self):
        regular_user = User.objects.create_user(
            username="regular_user",
            password="test-password",
        )
        self.client.force_login(regular_user)

        response = self.client.get(reverse("bots:manage_accounts"))

        self.assertEqual(response.status_code, 403)

    def test_staff_can_update_bot_identity(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("bots:manage_accounts"),
            {
                "bot_id": self.bot.pk,
                "username": "reader_bot_new",
                "first_name": "Иван",
                "last_name": "Ботов",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.bot_user.refresh_from_db()
        self.assertEqual(self.bot_user.username, "reader_bot_new")
        self.assertEqual(self.bot_user.first_name, "Иван")
        self.assertEqual(self.bot_user.last_name, "Ботов")

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

        response = self.client.post(
            reverse("bots:manage_accounts"),
            {
                "bot_id": expert_bot.pk,
                "username": "expert_bot",
                "first_name": "Алексей",
                "last_name": "Бот",
            },
        )

        self.assertEqual(response.status_code, 302)
        analyst_profile = AnalystProfile.objects.get(user=expert_user)
        self.assertEqual(analyst_profile.display_name, "Алексей Бот")

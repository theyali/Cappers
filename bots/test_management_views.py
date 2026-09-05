import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from cabinet.models import AnalystProfile, User

from .models import BotAccount


class BotAccountManagementViewTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.addCleanup(self.media_override.disable)

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

    @staticmethod
    def _png_upload(name="bot-avatar.png"):
        image_data = BytesIO()
        Image.new("RGB", (4, 4)).save(image_data, format="PNG")
        return SimpleUploadedFile(
            name,
            image_data.getvalue(),
            content_type="image/png",
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
        self.assertContains(
            response,
            f'data-avatar-upload-url="{reverse("bots:upload_avatar", args=[self.bot.pk])}"',
        )
        self.assertContains(response, "admin/js/vendor/jquery/jquery.min.js")
        self.assertContains(response, "bots/js/manage_accounts.js")

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

    def test_staff_can_upload_bot_avatar_without_saving_row(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("bots:upload_avatar", args=[self.bot.pk]),
            {"avatar": self._png_upload()},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["avatar_url"])

        self.bot_user.refresh_from_db()
        self.assertTrue(self.bot_user.avatar.name)

    def test_regular_user_cannot_upload_bot_avatar(self):
        regular_user = User.objects.create_user(
            username="regular_avatar_user",
            password="test-password",
        )
        self.client.force_login(regular_user)

        response = self.client.post(
            reverse("bots:upload_avatar", args=[self.bot.pk]),
            {"avatar": self._png_upload("forbidden.png")},
        )

        self.assertEqual(response.status_code, 403)

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

    def test_expert_ajax_avatar_is_synced_to_public_profile(self):
        expert_user = User.objects.create_user(
            username="expert_avatar_bot",
            password="test-password",
            role=User.Role.ANALYST,
        )
        expert_bot = BotAccount.objects.create(
            user=expert_user,
            kind=BotAccount.Kind.EXPERT,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("bots:upload_avatar", args=[expert_bot.pk]),
            {"avatar": self._png_upload("expert-avatar.png")},
        )

        self.assertEqual(response.status_code, 200)
        expert_user.refresh_from_db()
        analyst_profile = AnalystProfile.objects.get(user=expert_user)
        self.assertTrue(expert_user.avatar.name)
        self.assertEqual(analyst_profile.avatar.name, expert_user.avatar.name)

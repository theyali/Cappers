import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User


class ReaderAvatarTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.user = User.objects.create_user(
            username="reader-avatar",
            password="test-password-123",
            role=User.Role.READER,
        )
        self.client.force_login(self.user)

    def test_reader_can_upload_avatar(self):
        upload = SimpleUploadedFile(
            "avatar.png",
            b"reader-avatar-content",
            content_type="image/png",
        )
        response = self.client.post(reverse("cabinet:avatar_upload"), {"avatar": upload})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.user.refresh_from_db()
        self.assertTrue(bool(self.user.avatar))

    def test_reader_avatar_can_be_read_by_ajax(self):
        response = self.client.get(reverse("cabinet:avatar_upload"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "avatar_url": ""})

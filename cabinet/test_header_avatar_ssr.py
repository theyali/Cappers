import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from cabinet.models import User


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class HeaderAvatarSSRTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.media_dir.cleanup)
        self.user = User.objects.create_user(
            username="header-avatar-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.client.force_login(self.user)

    @staticmethod
    def _png_upload():
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        return SimpleUploadedFile(
            "avatar.png",
            buffer.getvalue(),
            content_type="image/png",
        )

    def test_reader_avatar_is_rendered_in_initial_header_html(self):
        self.user.avatar.save("avatar.png", self._png_upload(), save=True)

        response = self.client.get(reverse("front:index"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        header_start = html.index('<header class="site-header">')
        header_end = html.index("</header>", header_start)
        header_html = html[header_start:header_end]

        self.assertEqual(header_html.count(self.user.avatar.url), 2)
        self.assertNotIn("front/svgs/profile.svg", header_html)

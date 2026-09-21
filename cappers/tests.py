import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.test import RequestFactory, TestCase, override_settings
from PIL import Image

from achievements.models import AchievementCategory
from back.models import Bookmaker

from cappers.admin_dashboard import build_admin_dashboard_context, group_admin_apps
from cabinet.models import User


class AdminDashboardTests(TestCase):
    def test_group_admin_apps_moves_page_seo_to_separate_group(self):
        grouped = group_admin_apps(
            [
                {
                    "app_label": "pages",
                    "name": "Pages",
                    "app_url": "/admin/pages/",
                    "models": [
                        {
                            "name": "Страницы",
                            "object_name": "StaticPage",
                            "admin_url": "/admin/pages/staticpage/",
                        },
                        {
                            "name": "SEO",
                            "object_name": "PageSEO",
                            "admin_url": "/admin/pages/pageseo/",
                        },
                    ],
                }
            ]
        )

        keys = [app["key"] for app in grouped]
        self.assertIn("pages", keys)
        self.assertIn("seo", keys)
        seo_group = next(app for app in grouped if app["key"] == "seo")
        self.assertEqual(seo_group["model_count"], 1)
        self.assertEqual(seo_group["models"][0]["object_name"], "PageSEO")

    def test_dashboard_context_filters_quick_actions_by_permissions(self):
        user = User.objects.create_user(
            username="admin-dashboard-user",
            password="test-password",
            is_staff=True,
        )
        request = RequestFactory().get("/admin/")
        request.user = user

        context = build_admin_dashboard_context(request, [])

        self.assertEqual(
            [action["title"] for action in context["quick_actions"]],
            ["Открыть сайт"],
        )


def _image_upload(name: str, *, mode: str = "RGB", image_format: str = "JPEG"):
    image = Image.new(mode, (32, 24), (255, 0, 0, 128) if "A" in mode else (255, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type=f"image/{image_format.lower()}",
    )


@override_settings(
    MEDIA_WEBP_CONVERSION_ENABLED=True,
    MEDIA_WEBP_QUALITY=80,
    MEDIA_WEBP_MAX_WIDTH=128,
    MEDIA_WEBP_MAX_HEIGHT=128,
    MEDIA_WEBP_DELETE_ORIGINAL=True,
)
class MediaWebPConversionTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)

    def test_uploaded_jpeg_is_converted_to_webp(self):
        bookmaker = Bookmaker.objects.create(
            name="WebP Test",
            link="https://example.com",
            icon=_image_upload("bookmaker.jpg"),
        )
        bookmaker.refresh_from_db()

        self.assertTrue(bookmaker.icon.name.endswith(".webp"))
        self.assertTrue(default_storage.exists(bookmaker.icon.name))
        self.assertFalse(default_storage.exists("bookmakers/bookmaker.jpg"))

        with default_storage.open(bookmaker.icon.name, "rb") as converted:
            self.assertEqual(Image.open(converted).format, "WEBP")

    def test_uploaded_png_transparency_is_preserved(self):
        category = AchievementCategory.objects.create(
            title="Transparent",
            slug="transparent",
            icon=_image_upload("transparent.png", mode="RGBA", image_format="PNG"),
        )
        category.refresh_from_db()

        self.assertTrue(category.icon.name.endswith(".webp"))
        with default_storage.open(category.icon.name, "rb") as converted:
            image = Image.open(converted)
            self.assertEqual(image.format, "WEBP")
            self.assertIn(image.mode, {"RGBA", "RGBa"})

    def test_svg_is_not_converted(self):
        upload = SimpleUploadedFile(
            "vector.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>',
            content_type="image/svg+xml",
        )
        bookmaker = Bookmaker.objects.create(
            name="SVG Test",
            link="https://example.com",
            icon=upload,
        )
        bookmaker.refresh_from_db()

        self.assertTrue(bookmaker.icon.name.endswith(".svg"))
        self.assertTrue(default_storage.exists(bookmaker.icon.name))

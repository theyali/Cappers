import tempfile
from datetime import timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from cabinet.models import AnalystProfile, User, UserVipSubscription, VipPlan
from cabinet.vip import annotate_vip_status


class VipStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="vip-status-user",
            password="test-password",
        )
        self.plan = VipPlan.objects.create(
            title="VIP 30",
            duration_days=30,
            price_coins=100,
        )

    def create_subscription(self, *, starts_at, ends_at, is_active=True):
        return UserVipSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            starts_at=starts_at,
            ends_at=ends_at,
            duration_days=30,
            is_active=is_active,
        )

    def test_user_is_vip_for_active_subscription(self):
        now = timezone.now()
        self.create_subscription(
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=29),
        )

        self.assertTrue(self.user.is_vip)

    def test_user_is_not_vip_for_inactive_future_or_expired_subscription(self):
        now = timezone.now()
        self.create_subscription(
            starts_at=now - timedelta(days=30),
            ends_at=now - timedelta(seconds=1),
        )
        self.create_subscription(
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=31),
        )
        self.create_subscription(
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=29),
            is_active=False,
        )

        self.assertFalse(self.user.is_vip)

    def test_vip_annotations_prepare_status_and_dates(self):
        now = timezone.now()
        latest_start = now - timedelta(hours=2)
        furthest_end = now + timedelta(days=40)
        self.create_subscription(
            starts_at=now - timedelta(days=10),
            ends_at=furthest_end,
        )
        self.create_subscription(
            starts_at=latest_start,
            ends_at=now + timedelta(days=10),
        )

        annotated_user = annotate_vip_status(
            User.objects.filter(pk=self.user.pk),
            at=now,
        ).get()

        self.assertTrue(annotated_user.is_vip_active)
        self.assertEqual(annotated_user.vip_ends_at, furthest_end)
        self.assertEqual(annotated_user.vip_activated_at, latest_start)

        with self.assertNumQueries(0):
            self.assertTrue(annotated_user.is_vip)

    def test_unsaved_user_is_not_vip_without_query(self):
        user = User(username="unsaved-vip-user")

        with self.assertNumQueries(0):
            self.assertFalse(user.is_vip)


class ProfileCoverTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.media_dir.cleanup)

        self.user = User.objects.create_user(
            username="cover-capper",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.profile = AnalystProfile.objects.create(user=self.user)
        self.plan = VipPlan.objects.create(
            title="VIP cover",
            duration_days=30,
            price_coins=100,
        )
        self.client.force_login(self.user)

    def _image_upload(self, name):
        buffer = BytesIO()
        Image.new("RGB", (64, 32), "white").save(buffer, format="JPEG")
        return SimpleUploadedFile(
            name,
            buffer.getvalue(),
            content_type="image/jpeg",
        )

    def _activate_vip(self):
        now = timezone.now()
        UserVipSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(days=30),
            duration_days=30,
        )

    def test_non_vip_capper_cannot_upload_cover_and_sees_locked_state(self):
        response = self.client.post(
            reverse("cabinet:cover_upload"),
            {"cover_image": self._image_upload("cover.jpg")},
        )

        self.assertEqual(response.status_code, 403)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.cover_image)

        page = self.client.get(reverse("cabinet:profile"), {"tab": "profile"})
        self.assertContains(page, "Обложка профиля")
        self.assertContains(page, "Добавьте персональную обложку после подключения VIP.")
        self.assertContains(page, reverse("cabinet:vip_purchase"))
        self.assertNotContains(page, 'id="profileCoverInput"')

    def test_reader_cannot_upload_cover(self):
        reader = User.objects.create_user(
            username="cover-reader",
            password="test-password",
        )
        self.client.force_login(reader)

        response = self.client.post(
            reverse("cabinet:cover_upload"),
            {"cover_image": self._image_upload("reader-cover.jpg")},
        )

        self.assertEqual(response.status_code, 403)

    def test_vip_capper_can_replace_cover_and_old_file_is_deleted(self):
        self._activate_vip()

        first_response = self.client.post(
            reverse("cabinet:cover_upload"),
            {"cover_image": self._image_upload("first-cover.jpg")},
        )
        self.assertEqual(first_response.status_code, 200)
        self.profile.refresh_from_db()
        first_name = self.profile.cover_image.name
        storage = self.profile.cover_image.storage
        self.assertTrue(storage.exists(first_name))

        second_response = self.client.post(
            reverse("cabinet:cover_upload"),
            {"cover_image": self._image_upload("second-cover.jpg")},
        )

        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(second_response.json()["cover_url"])
        self.profile.refresh_from_db()
        self.assertNotEqual(self.profile.cover_image.name, first_name)
        self.assertFalse(storage.exists(first_name))
        self.assertTrue(storage.exists(self.profile.cover_image.name))

        page = self.client.get(reverse("cabinet:profile"), {"tab": "profile"})
        self.assertContains(page, 'id="profileHeroCoverImage"')
        self.assertContains(page, 'id="profileCoverInput"')
        self.assertContains(page, "Сменить обложку")

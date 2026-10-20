from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystPaidSubscription, User
from front.metric_models import PredictionCouponOpen, PredictionMetrics
from front.metrics import record_coupon_open, refresh_prediction_metrics, increment_prediction_views
from front.templatetags.prediction_reactions import coupon_opens_label
from game.models import PredictionCoupon

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


class OpensFixture:
    def setUp(self):
        self.author = User.objects.create_user(username="open-author", role=User.Role.ANALYST)
        self.reader = User.objects.create_user(username="open-reader")
        self.coupon = PredictionCoupon.objects.create(author=self.author, total_stake=1, audience="free", published_status="published")
        self.url = reverse("front:prediction_open", args=[self.coupon.pk])


@override_settings(STORAGES=STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}, CELERY_TASK_ALWAYS_EAGER=True)
class CouponOpenTests(OpensFixture, TestCase):
    def test_only_first_authorized_visible_content_event_counts(self):
        self.assertIsNone(record_coupon_open(AnonymousUser(), self.coupon))
        self.assertIsNone(record_coupon_open(self.author, self.coupon))
        for _ in range(2):
            self.assertEqual(record_coupon_open(self.reader, self.coupon).unique_opens_count, 1)
        self.assertEqual(PredictionCouponOpen.objects.count(), 1)

    def test_locked_paid_coupon_and_unpublished_coupon_cannot_record(self):
        self.coupon.audience = "paid"
        self.coupon.save()
        with self.assertRaises(PermissionDenied):
            record_coupon_open(self.reader, self.coupon)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertFalse(PredictionCouponOpen.objects.exists())
        AnalystPaidSubscription.objects.create(subscriber=self.reader, analyst=self.author, price=100, expires_at=timezone.now()+timedelta(days=1))
        self.assertEqual(self.client.post(self.url).json()["unique_opens_count"], 1)
        self.coupon.published_status = "draft"
        self.coupon.save()
        self.assertEqual(self.client.post(self.url).status_code, 404)

    def test_authenticated_post_requires_csrf_and_get_never_counts(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reader)
        self.assertEqual(client.get(self.url).status_code, 405)
        self.assertEqual(client.post(self.url).status_code, 403)
        detail = client.get(reverse("front:prediction_detail", args=[self.coupon.pk]))
        self.assertContains(detail, 'data-coupon-open-url=')
        self.assertIn("private", detail.headers["Cache-Control"])
        self.assertFalse(PredictionCouponOpen.objects.exists())
        self.assertEqual(client.post(self.url, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value).json()["unique_opens_count"], 1)

    def test_account_deletion_anonymizes_rows_and_rebuild_preserves_count(self):
        record_coupon_open(self.reader, self.coupon)
        # The project's startup coin wallet is separately protected financial history.
        # Remove that fixture to isolate the opens relation's deletion policy.
        from wallets.models import CoinTransaction, CoinWallet
        CoinTransaction.objects.filter(user=self.reader).delete()
        CoinWallet.objects.filter(user=self.reader).delete()
        self.reader.delete()
        self.assertIsNone(PredictionCouponOpen.objects.get().user_id)
        PredictionMetrics.objects.filter(coupon=self.coupon).update(unique_opens_count=99)
        self.assertEqual(refresh_prediction_metrics(self.coupon.pk).unique_opens_count, 1)
        call_command("rebuild_coupon_opens", stdout=StringIO())
        self.assertEqual(PredictionMetrics.objects.get(coupon=self.coupon).unique_opens_count, 1)
        self.coupon.delete()
        self.assertFalse(PredictionCouponOpen.objects.exists())

    def test_actual_account_deletion_unlinks_opens_and_a_stale_request_cannot_relink(self):
        from cabinet.services.account_deletion import delete_user_account
        record_coupon_open(self.reader, self.coupon)
        delete_user_account(self.reader)
        self.assertIsNone(PredictionCouponOpen.objects.get().user_id)
        self.assertIsNone(record_coupon_open(self.reader, self.coupon))
        self.assertEqual(refresh_prediction_metrics(self.coupon.pk).unique_opens_count, 1)

    def test_view_count_is_not_used_as_unique_opens(self):
        increment_prediction_views(self.coupon.pk)
        metrics = refresh_prediction_metrics(self.coupon.pk)
        self.assertEqual(metrics.views_count, 1)
        self.assertEqual(metrics.unique_opens_count, 0)

    def test_russian_plural_labels(self):
        for count, expected in [(0, "0 человек"), (1, "1 человек"), (2, "2 человека"), (5, "5 человек"), (11, "11 человек"), (21, "21 человек"), (112, "112 человек")]:
            self.assertEqual(coupon_opens_label(count), "Открыли " + expected)


@override_settings(STORAGES=STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}, CELERY_TASK_ALWAYS_EAGER=True)
class CouponOpenConcurrencyTests(OpensFixture, TransactionTestCase):
    def test_two_tabs_create_one_open(self):
        barrier = Barrier(2)
        def record():
            try:
                user = User.objects.get(pk=self.reader.pk)
                coupon = PredictionCoupon.objects.get(pk=self.coupon.pk)
                barrier.wait(timeout=10)
                return record_coupon_open(user, coupon).unique_opens_count
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(lambda _: record(), range(2))), [1, 1])
        self.assertEqual(PredictionCouponOpen.objects.count(), 1)

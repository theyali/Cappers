from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from cabinet.models import (
    AnalystFollow,
    AnalystPaidSubscription,
    AnalystPaidSubscriptionPayment,
    User,
)
from cabinet.paid_predictions import paid_subscription_display
from cabinet.views import _profile_social_context


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
)
class ProfilePaidSubscriptionsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.now = timezone.now()
        self.reader = User.objects.create_user(username="subscription-reader")
        self.analyst = User.objects.create_user(
            username="paid-capper", role=User.Role.ANALYST
        )
        self.subscription = AnalystPaidSubscription.objects.create(
            subscriber=self.reader,
            analyst=self.analyst,
            price=Decimal("350.00"),
            duration_days=30,
            starts_at=self.now - timedelta(days=10),
            expires_at=self.now + timedelta(days=2, hours=3),
        )
        AnalystFollow.objects.create(follower=self.reader, analyst=self.analyst)
        for price in ("200", "350"):
            AnalystPaidSubscriptionPayment.objects.create(
                subscription=self.subscription,
                subscriber=self.reader,
                analyst=self.analyst,
                price=Decimal(price),
                capper_income=Decimal(price),
                duration_days=30,
                starts_at=self.now - timedelta(days=10),
                expires_at=self.subscription.expires_at,
            )
        self.client.force_login(self.reader)

    def context(self, **params):
        with patch("django.utils.timezone.now", return_value=self.now):
            return _profile_social_context(self.reader, kind="following", **params)

    def test_reader_panel_shows_own_paid_subscriptions_with_amount_expiry_and_remaining(
        self,
    ):
        context = self.context()
        row = context["profile_social_rows"][0]
        self.assertEqual(context["profile_social_metrics"]["paid"], 1)
        self.assertEqual(context["profile_social_paid_label"], "Платные подписки")
        self.assertEqual(row["paid_subscription"]["amount_label"], "550")
        self.assertEqual(
            row["paid_subscription"]["remaining_label"], "Осталось: 2 дн. 3 ч."
        )
        self.assertIn(
            self.subscription.expires_at.isoformat(),
            row["paid_subscription"]["expires_iso"],
        )
        html = render_to_string(
            "cabinet/includes/_profile_social_panel.html", {"profile_social": context}
        )
        for text in (
            "Платные подписки",
            "Платных подписок",
            "Всего оплачено",
            "550 ₽",
            "Действует до",
            "Осталось: 2 дн. 3 ч.",
        ):
            self.assertIn(text, html)
        self.assertNotIn("Платные подписчики", html)
        self.assertNotIn("Платных подписчиков", html)
        self.assertNotIn("?tab=earnings", html)

    def test_ajax_paid_filter_and_preview_have_the_same_payment_details(self):
        with patch("django.utils.timezone.now", return_value=self.now):
            response = self.client.get(
                reverse("cabinet:profile_social"),
                {"kind": "following", "filter": "paid"},
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        for html in (data["html"], data["paid_preview_html"]):
            self.assertIn("550 ₽", html)
            self.assertIn("Осталось: 2 дн. 3 ч.", html)
            self.assertIn(self.subscription.expires_at.isoformat(), html)

    def test_reader_cabinet_renders_the_outgoing_subscription_details(self):
        with patch("django.utils.timezone.now", return_value=self.now):
            response = self.client.get(reverse("cabinet:profile"), {"tab": "following"})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Платные подписки", html)
        self.assertIn("550 ₽", html)
        self.assertIn("Осталось: 2 дн. 3 ч.", html)
        self.assertNotIn("Платные подписчики", html)

    def test_paid_filter_pagination_has_no_duplicates(self):
        for index in range(9):
            analyst = User.objects.create_user(
                username=f"paged-capper-{index}", role=User.Role.ANALYST
            )
            AnalystPaidSubscription.objects.create(
                subscriber=self.reader,
                analyst=analyst,
                price=Decimal("100.00"),
                expires_at=self.now + timedelta(days=5),
            )
        first = self.context(filter_key="paid")
        second = self.context(
            filter_key="paid", offset=first["profile_social_next_offset"]
        )
        self.assertEqual(first["profile_social_total"], 10)
        self.assertTrue(first["profile_social_has_more"])
        self.assertFalse(second["profile_social_has_more"])
        ids = [
            row["id"] for page in (first, second) for row in page["profile_social_rows"]
        ]
        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)

    def test_paid_access_is_listed_even_after_free_follow_was_removed(self):
        AnalystFollow.objects.filter(follower=self.reader).delete()
        context = self.context(filter_key="paid")
        self.assertEqual(context["profile_social_total"], 1)
        self.assertEqual(
            context["profile_social_rows"][0]["username"], self.analyst.username
        )
        self.assertFalse(context["profile_social_rows"][0]["is_following"])
        self.assertIsNotNone(context["profile_social_rows"][0]["paid_subscription"])

    def test_other_readers_payments_never_enter_the_amount_or_preview(self):
        other = User.objects.create_user(username="other-reader")
        private = User.objects.create_user(
            username="other-private-capper", role=User.Role.ANALYST
        )
        for analyst in (self.analyst, private):
            subscription = AnalystPaidSubscription.objects.create(
                subscriber=other,
                analyst=analyst,
                price=Decimal("999.00"),
                expires_at=self.now + timedelta(days=3),
            )
            AnalystPaidSubscriptionPayment.objects.create(
                subscription=subscription,
                subscriber=other,
                analyst=analyst,
                price=Decimal("999.00"),
                capper_income=Decimal("999.00"),
                duration_days=30,
                starts_at=self.now,
                expires_at=subscription.expires_at,
            )
        html = render_to_string(
            "cabinet/includes/_profile_social_panel.html",
            {"profile_social": self.context()},
        )
        self.assertNotIn("999", html)
        self.assertNotIn(private.username, html)
        self.assertIn("550 ₽", html)

    def test_expired_subscription_leaves_free_follow_but_no_paid_access(self):
        self.subscription.expires_at = self.now
        self.subscription.save(update_fields=["expires_at"])
        context = self.context()
        self.assertEqual(context["profile_social_total"], 1)
        self.assertEqual(context["profile_social_metrics"]["paid"], 0)
        self.assertIsNone(context["profile_social_rows"][0]["paid_subscription"])
        self.assertEqual(self.context(filter_key="paid")["profile_social_total"], 0)

    def test_legacy_cost_is_honest_when_no_payment_ledger_exists(self):
        self.subscription.payments.all().delete()
        details = self.context()["profile_social_rows"][0]["paid_subscription"]
        self.assertEqual(details["amount_caption"], "Стоимость подписки")
        self.assertEqual(details["amount_label"], "350")

    def test_countdown_boundaries(self):
        for delta, label in (
            (timedelta(minutes=59), "Осталось менее часа"),
            (timedelta(hours=24), "Осталось: 1 дн. 0 ч."),
            (timedelta(0), "Подписка завершена"),
        ):
            self.subscription.expires_at = self.now + delta
            self.assertEqual(
                paid_subscription_display(self.subscription, at=self.now)[
                    "remaining_label"
                ],
                label,
            )

    def test_reader_cannot_open_someone_elses_paid_audience(self):
        self.assertEqual(
            self.client.get(
                reverse("cabinet:profile_social"), {"kind": "paid"}
            ).status_code,
            403,
        )

    def test_capper_followers_keep_the_incoming_paid_subscribers_label(self):
        context = _profile_social_context(self.analyst, kind="followers")
        self.assertEqual(context["profile_social_paid_label"], "Платные подписчики")
        self.assertEqual(context["profile_social_metrics"]["paid"], 1)
        self.assertEqual(context["profile_social_paid_preview"], [])

    def test_payment_details_do_not_add_per_row_queries(self):
        with CaptureQueriesContext(connection) as one:
            self.context()
        for index in range(7):
            analyst = User.objects.create_user(
                username=f"more-capper-{index}", role=User.Role.ANALYST
            )
            AnalystFollow.objects.create(follower=self.reader, analyst=analyst)
            AnalystPaidSubscription.objects.create(
                subscriber=self.reader,
                analyst=analyst,
                price=Decimal("100.00"),
                expires_at=self.now + timedelta(days=5),
            )
        with CaptureQueriesContext(connection) as eight:
            context = self.context()
        self.assertEqual(len(context["profile_social_rows"]), 8)
        self.assertEqual(len(one), len(eight))

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
        self.assertNotIn("999 ₽", html)
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

    def test_public_tariffs_require_paid_settings_and_use_active_real_plans(self):
        from cabinet.models import AnalystPaidPlan
        from cabinet.paid_predictions import build_public_paid_tariffs_context, get_active_paid_plans
        profile = self.analyst.analyst_profile
        plans = [AnalystPaidPlan.objects.create(analyst=self.analyst, title=str(days), duration_days=days, price=Decimal(price))
                 for days, price in ((1, "100"), (7, "600"), (30, "2000"), (90, "5000"))]
        AnalystPaidPlan.objects.create(analyst=self.analyst, title="Выключен", duration_days=180, price=Decimal("9999"), is_active=False)
        url = reverse("front:expert_profile", args=[self.analyst.username])
        self.assertNotContains(self.client.get(url), 'class="expert-public-paid-tariffs"')
        profile.paid_predictions_enabled = True
        profile.save(update_fields=["paid_predictions_enabled"])
        page = self.client.get(url)
        self.assertContains(page, 'class="expert-public-paid-tariffs"')
        self.assertContains(page, 'id="expert-paid-tariffs-title"')
        self.assertEqual(len(page.context["expert_paid_tariffs"]["plans"]), 4)
        body = page.content.decode()
        self.assertLess(body.index('expert-public-stats expert-public-stats-compact'), body.index('class="expert-public-paid-tariffs"'))
        self.assertLess(body.index('class="expert-public-paid-tariffs"'), body.index('class="expert-public-analytics"'))
        context = build_public_paid_tariffs_context(self.reader, profile, list(get_active_paid_plans(self.analyst)), next_url=url, subscription=self.subscription)
        self.assertEqual(context["subscribers_label"], "1 подписчик")
        best = [choice for choice in context["plans"] if choice["is_best_value"]]
        self.assertEqual([choice["id"] for choice in best], [str(plans[-1].pk)])
        self.assertTrue(all(choice["action_label"] == "Продлить" for choice in context["plans"]))
        self.assertIn(f"plan_id={plans[0].pk}", context["plans"][0]["action_url"])

    def test_tariff_choice_is_preselected_in_modal_and_preserved_by_direct_link(self):
        from cabinet.models import AnalystPaidPlan
        profile = self.analyst.analyst_profile
        profile.paid_predictions_enabled = True
        profile.save(update_fields=["paid_predictions_enabled"])
        day = AnalystPaidPlan.objects.create(analyst=self.analyst, title="День", duration_days=1, price=Decimal("100"))
        AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("2000"))
        url = reverse("cabinet:paid_predictions_subscribe", args=[self.analyst.pk])
        page = self.client.get(url, {"plan_id": day.pk}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(page, f'name="plan_id" value="{day.pk}" checked>')
        self.assertEqual(page.context["subscription_default"]["id"], str(day.pk))
        response = self.client.get(url, {"plan_id": day.pk, "next": "/predictions/"})
        self.assertRedirects(response, f"/predictions/?paid_subscribe={self.analyst.pk}&paid_plan={day.pk}", fetch_redirect_response=False)

    def test_own_tariffs_link_to_settings_and_single_only_profile_has_no_subscription_block(self):
        from cabinet.models import AnalystPaidPlan
        from cabinet.paid_predictions import build_public_paid_tariffs_context
        profile = self.analyst.analyst_profile
        profile.paid_predictions_enabled = profile.single_coupon_sales_enabled = True
        profile.single_coupon_price = Decimal("100")
        profile.paid_predictions_price = Decimal("0")
        profile.save()
        url = reverse("front:expert_profile", args=[self.analyst.username])
        self.assertNotContains(self.client.get(url), 'class="expert-public-paid-tariffs"')
        plan = AnalystPaidPlan.objects.create(analyst=self.analyst, title="День", duration_days=1, price=Decimal("100"))
        context = build_public_paid_tariffs_context(self.analyst, profile, [plan], next_url=url)
        self.assertEqual(context["plans"][0]["action_label"], "Настроить")
        self.assertEqual(context["plans"][0]["action_url"], reverse("cabinet:profile") + "?tab=settings#paid-predictions-settings")

    @override_settings(SINGLE_COUPON_SALES_ENABLED=True)
    def test_tariffs_tab_follows_statistics_and_has_only_public_coupon_previews(self):
        from cabinet.models import AnalystPaidPlan
        from game.models import Match, Prediction, PredictionCoupon
        profile = self.analyst.analyst_profile
        profile.paid_predictions_enabled = profile.single_coupon_sales_enabled = True
        profile.single_coupon_price = Decimal("100")
        profile.save()
        AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("2000"))
        match = Match.objects.create(external_id=8899471, sync_scope="prematch", starts_at=timezone.now() + timedelta(days=1))
        coupon = PredictionCoupon.objects.create(author=self.analyst, total_stake=1, audience="paid", published_status="published", single_purchase_enabled=True, single_purchase_price=100, headline="PRIVATE_HEADLINE_123", description="PRIVATE_ANALYSIS_123")
        Prediction.objects.create(coupon=coupon, match=match, market="winner", selection="PRIVATE_PICK_123", coefficient=2, stake=1)
        self.client.logout()
        response = self.client.get(reverse("front:expert_profile", args=[self.analyst.username]))
        self.assertContains(response, 'data-expert-public-tab="tariffs"')
        self.assertContains(response, 'data-expert-public-panel="tariffs"')
        body = response.content.decode()
        self.assertLess(body.index('data-expert-public-tab="stats"'), body.index('data-expert-public-tab="tariffs"'))
        self.assertLess(body.index('data-expert-public-tab="tariffs"'), body.index('data-expert-public-tab="bank"'))
        self.assertEqual(response.context["expert_tariff_coupons"]["total"], 1)
        self.assertEqual(response.context["expert_tariff_coupons"]["rows"][0]["id"], coupon.pk)
        self.assertContains(response, "Купить 100 ₽")
        for secret in ("PRIVATE_HEADLINE_123", "PRIVATE_ANALYSIS_123", "PRIVATE_PICK_123"):
            self.assertNotContains(response, secret)
        profile.paid_predictions_enabled = False
        profile.save(update_fields=["paid_predictions_enabled"])
        disabled = self.client.get(reverse("front:expert_profile", args=[self.analyst.username]))
        self.assertNotContains(disabled, 'data-expert-public-tab="tariffs"')
        self.assertNotContains(disabled, 'data-expert-public-panel="tariffs"')

    @override_settings(SINGLE_COUPON_SALES_ENABLED=True)
    def test_tariff_coupon_list_includes_started_and_finished_coupons_without_allowing_late_purchase(self):
        from cabinet.paid_prediction_purchases import build_public_tariff_coupon_context
        from game.models import Match, Prediction, PredictionCoupon
        profile = self.analyst.analyst_profile
        profile.paid_predictions_enabled = profile.single_coupon_sales_enabled = True
        profile.single_coupon_price = Decimal("100")
        profile.save()
        future = Match.objects.create(external_id=8899472, sync_scope="prematch", starts_at=timezone.now() + timedelta(days=1))
        past = Match.objects.create(external_id=8899473, sync_scope="prematch", starts_at=timezone.now() - timedelta(minutes=1))
        valid = PredictionCoupon.objects.create(author=self.analyst, total_stake=1, audience="paid", published_status="published", single_purchase_enabled=True, single_purchase_price=100)
        invalid = PredictionCoupon.objects.create(author=self.analyst, total_stake=1, audience="paid", published_status="published", single_purchase_enabled=True, single_purchase_price=100)
        for coupon, match in ((valid, future), (invalid, future), (invalid, past)):
            Prediction.objects.create(coupon=coupon, match=match, market="winner", selection="private", coefficient=2, stake=1)
        context = build_public_tariff_coupon_context(self.reader, self.analyst, limit=1)
        self.assertEqual(context["total"], 2)
        self.assertEqual(context["total_label"], "2 прогноза")
        self.assertEqual(context["rows"][0]["id"], invalid.pk)
        self.assertEqual(context["rows"][0]["action_label"], "Открыть")
        self.assertTrue(context["rows"][0]["accessible"])
        valid.metrics.refresh_from_db()
        self.assertEqual(valid.metrics.unique_opens_count, 0)
        from django.contrib.auth.models import AnonymousUser
        valid.state_status = "win"
        valid.settled_at = timezone.now()
        valid.save(update_fields=["state_status", "settled_at"])
        public_rows = build_public_tariff_coupon_context(AnonymousUser(), self.analyst)["rows"]
        self.assertEqual(len(public_rows), 2)
        finished = next(row for row in public_rows if row["id"] == valid.pk)
        self.assertTrue(finished["is_completed"])
        for row in public_rows:
            self.assertEqual(row["action_label"], "Подробнее")
            self.assertEqual(row["action_url"], reverse("front:prediction_detail", args=[row["id"]]))
        future.starts_at = None
        future.save(update_fields=["starts_at"])
        self.assertEqual(build_public_tariff_coupon_context(self.reader, self.analyst)["total"], 2)
        future.starts_at = timezone.now() + timedelta(days=1)
        future.sync_scope = "live"
        future.save(update_fields=["starts_at", "sync_scope"])
        self.assertEqual(build_public_tariff_coupon_context(self.reader, self.analyst)["total"], 2)

    def test_single_only_profile_has_tariffs_tab_without_subscription_rail(self):
        profile = self.analyst.analyst_profile
        profile.paid_predictions_enabled = profile.single_coupon_sales_enabled = True
        profile.single_coupon_price = Decimal("100")
        profile.paid_predictions_price = 0
        profile.save()
        response = self.client.get(reverse("front:expert_profile", args=[self.analyst.username]))
        self.assertContains(response, 'data-expert-public-tab="tariffs"')
        self.assertContains(response, 'expert-tariffs-panel has-no-subscription')
        self.assertNotContains(response, 'data-expert-tariff-picker')
        self.assertContains(response, 'Платных прогнозов пока нет.')

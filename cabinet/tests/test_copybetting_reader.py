from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from cabinet.services.copybetting import build_public_copybetting_context, build_reader_copybetting_context
from game.models import PredictionCoupon
from wallets.models import CopiedBet, CopyBettingSubscription


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class CopybettingReaderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reader = User.objects.create_user(username="cu-reader")
        cls.other = User.objects.create_user(username="cu-other")
        cls.subscriptions = []
        for number in range(11):
            analyst = User.objects.create_user(username=f"cu-capper-{number:02d}", role=User.Role.ANALYST)
            profile = analyst.analyst_profile
            profile.display_name = f"Аналитик {number}"
            profile.trust_index = Decimal("8.4")
            profile.save(update_fields=["display_name", "trust_index"])
            subscription = CopyBettingSubscription.objects.create(
                user=cls.reader, analyst=analyst,
                status="active" if number < 7 else "paused" if number < 9 else "stopped",
                bank_amount=10000, stake_percent=10, max_single_stake=500,
                total_profit=Decimal(number * 100),
            )
            cls.subscriptions.append(subscription)
        cls.foreign_analyst = User.objects.create_user(username="cu-foreign-capper", role=User.Role.ANALYST)
        cls.foreign = CopyBettingSubscription.objects.create(
            user=cls.other, analyst=cls.foreign_analyst, bank_amount=1000, stake_percent=10, total_profit=90000,
        )
        for index, profit in enumerate([Decimal("100"), Decimal("-50"), Decimal("200")]):
            coupon = PredictionCoupon.objects.create(author=cls.subscriptions[0].analyst, published_status="published",
                                                     audience="paid", total_stake=100, possible_payout=200,
                                                     headline="СЕКРЕТНЫЙ ЗАГОЛОВОК", description="СЕКРЕТНОЕ ОПИСАНИЕ")
            CopiedBet.objects.create(subscription=cls.subscriptions[0], user=cls.reader,
                                     analyst=cls.subscriptions[0].analyst, source_coupon=coupon,
                                     stake=500, possible_payout=1000, profit=profit, state_status="win",
                                     settled_at=timezone.now() - timedelta(days=3-index))
        cls.old_copy = CopiedBet.objects.order_by("id").first()
        CopiedBet.objects.filter(pk=cls.old_copy.pk).update(created_at=timezone.now()-timedelta(days=40))

    def setUp(self):
        self.client.force_login(self.reader)

    def get(self, **params):
        return self.client.get(reverse("cabinet:copybetting_reader"), params)

    def test_private_endpoint_and_roles(self):
        self.client.logout()
        self.assertEqual(self.get().status_code, 302)
        self.client.force_login(self.foreign_analyst)
        self.assertEqual(self.get().status_code, 403)
        self.client.force_login(self.reader)
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("cu-foreign-capper", response.json()["html"])

    def test_summary_counts_and_real_thirty_day_turnover(self):
        context = build_reader_copybetting_context(self.reader, {})
        self.assertEqual(context["copybetting_reader_active"], 7)
        self.assertEqual(context["copybetting_reader_paused"], 2)
        self.assertEqual(context["copybetting_reader_turnover"], "1 000")
        self.assertEqual(context["copybetting_reader_profit"], "+5 500")
        self.assertEqual([s["count"] for s in context["copybetting_reader_statuses"]], [11, 7, 2, 2])

    def test_filter_search_sort_before_paging_and_page_clamping(self):
        first = build_reader_copybetting_context(self.reader, {})
        second = build_reader_copybetting_context(self.reader, {"copy_page": 2})
        self.assertEqual([row["profit"] for row in first["copybetting_reader_rows"]], [f"+{i * 100:,}".replace(",", " ") for i in range(10, 2, -1)])
        self.assertEqual(len(second["copybetting_reader_rows"]), 3)
        for state, count in [("active", 7), ("paused", 2), ("stopped", 2)]:
            context = build_reader_copybetting_context(self.reader, {"copy_status": state})
            self.assertEqual(context["copybetting_reader_total"], count)
            self.assertTrue(all(row["status"] == state for row in context["copybetting_reader_rows"]))
        for query in ("@cu-capper-10", "Аналитик 10"):
            context = build_reader_copybetting_context(self.reader, {"copy_q": query})
            self.assertEqual(context["copybetting_reader_total"], 1)
        self.assertEqual(self.get(copy_sort="invalid", copy_status="invalid", copy_page="invalid").status_code, 200)

    def test_rows_use_actual_capped_stakes_and_real_profit_history(self):
        context = build_reader_copybetting_context(self.reader, {"copy_q": "cu-capper-00"})
        row = context["copybetting_reader_rows"][0]
        self.assertEqual(row["stake"], "500")
        self.assertEqual(row["sparkline_count"], 3)
        self.assertEqual(len(row["sparkline"].split()), 4)
        self.assertNotEqual(row["sparkline"], "2.0,15.0 82.0,15.0")
        html = self.get(copy_q="cu-capper-00").json()["html"]
        self.assertIn(reverse("wallets:copybetting_pause", args=[row["id"]]), html)
        self.assertIn(reverse("wallets:copybetting_stop", args=[row["id"]]), html)
        self.assertNotIn("СЕКРЕТНЫЙ", html)

    def test_copied_history_is_owned_and_does_not_leak_paid_source_content(self):
        response = self.get(copy_view="bets")
        html = response.json()["html"]
        self.assertIn("Копия купона #", html)
        self.assertNotIn("СЕКРЕТНЫЙ", html)
        self.assertNotIn("cu-foreign-capper", html)
        self.assertEqual(build_reader_copybetting_context(self.other, {"copy_view": "bets"})["copybetting_reader_total"], 0)

    def test_existing_status_endpoints_preserve_return_filters_and_ownership(self):
        active = self.subscriptions[1]
        next_url = reverse("cabinet:profile") + "?tab=copybetting&copy_status=paused&copy_q=cu-capper-01"
        pause = self.client.post(reverse("wallets:copybetting_pause", args=[active.pk]), {"next": next_url})
        self.assertRedirects(pause, next_url, fetch_redirect_response=False)
        active.refresh_from_db()
        self.assertEqual(active.status, "paused")
        resume = self.client.post(reverse("wallets:copybetting_resume", args=[active.pk]), {"next": "https://example.com/"})
        self.assertRedirects(resume, reverse("cabinet:profile") + "?tab=copybetting", fetch_redirect_response=False)
        self.assertEqual(self.client.post(reverse("wallets:copybetting_stop", args=[self.foreign.pk])).status_code, 404)

    def test_reader_full_page_and_empty_state(self):
        response = self.client.get(reverse("cabinet:profile"), {"tab": "copybetting"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-copy-role="reader"')
        self.assertContains(response, "Кого я копирую")
        self.assertContains(response, 'id="copybetting-limits-modal"', count=1)
        self.assertNotContains(response, "profile-copy-table")
        self.assertContains(response, 'id="copybetting-search-modal"', count=1)
        self.assertContains(response, '<button type="button" class="copybetting-button is-primary" aria-label="Добавить каппера"')
        self.assertContains(response, 'data-copy-sort="trust"')
        self.client.force_login(self.other)
        response = self.get(copy_q="nothing-here")
        self.assertIn("По выбранным условиям стратегий нет", response.json()["html"])
        self.assertIn('data-copy-discovery-open', response.json()["html"])
        self.assertNotIn('href="/cappers-table/"', response.json()["html"])

    def test_public_copy_strip_uses_only_viewers_strategy_and_real_stake(self):
        analyst = self.subscriptions[0].analyst
        CopyBettingSubscription.objects.create(user=self.other, analyst=analyst, bank_amount=20000, stake_percent=20, total_profit=90000)
        with self.assertNumQueries(3):
            data = build_public_copybetting_context(self.reader, analyst)["public_copybetting"]
        self.assertEqual(data["status"], "active")
        self.assertEqual(data["stake"], "500")
        self.assertEqual(data["profit"], "0")
        self.assertEqual(data["sparkline_count"], 3)
        self.assertTrue(data["can_pause"])
        self.assertTrue(data["can_stop"])
        self.assertEqual(data["return_url"], reverse("front:expert_profile", args=[analyst.username]))
        self.assertEqual(build_public_copybetting_context(self.reader, self.foreign_analyst)["public_copybetting"]["status"], "none")
        with self.assertNumQueries(0):
            anonymous = build_public_copybetting_context(AnonymousUser(), analyst)["public_copybetting"]
        self.assertEqual(anonymous["status"], "none")
        self.assertIn(reverse("cabinet:login"), anonymous["setup_url"])
        self.assertNotIn("profit", anonymous)
        self.assertFalse(build_public_copybetting_context(analyst, analyst)["public_copybetting"]["visible"])
        self.assertFalse(build_public_copybetting_context(self.foreign_analyst, analyst)["public_copybetting"]["visible"])

    def test_public_copy_strip_paused_stopped_and_pending(self):
        paused = build_public_copybetting_context(self.reader, self.subscriptions[7].analyst)["public_copybetting"]
        self.assertEqual(paused["status"], "paused")
        self.assertTrue(paused["can_resume"])
        self.assertFalse(paused["can_pause"])
        stopped = build_public_copybetting_context(self.reader, self.subscriptions[9].analyst)["public_copybetting"]
        self.assertEqual(stopped["status"], "stopped")
        self.assertFalse(stopped["can_resume"])
        self.assertEqual(stopped["hero_url"], stopped["setup_url"])
        subscription = self.subscriptions[0]
        subscription.pending_status = "paused"
        subscription.save(update_fields=["pending_status"])
        pending = build_public_copybetting_context(self.reader, subscription.analyst)["public_copybetting"]
        self.assertTrue(pending["pending_label"])
        self.assertFalse(pending["can_pause"])
        self.assertTrue(pending["can_stop"])
        self.assertTrue(pending["can_resume"])

    def test_public_page_copy_actions_and_help_render_without_paid_source_leaks(self):
        analyst = self.subscriptions[0].analyst
        profile = analyst.analyst_profile
        profile.is_public = True
        profile.save(update_fields=["is_public"])
        url = reverse("front:expert_profile", args=[analyst.username])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, 'id="expert-copybetting"', count=1)
        self.assertContains(response, 'id="expert-copybetting-mobile"', count=1)
        self.assertContains(response, 'id="copybetting-how-modal"', count=1)
        self.assertContains(response, 'class="expert-copy-button is-active"')
        self.assertContains(response, reverse("wallets:copybetting_pause", args=[self.subscriptions[0].pk]))
        self.assertNotContains(response, "СЕКРЕТНЫЙ")
        self.client.logout()
        response = self.client.get(url)
        self.assertContains(response, 'class="expert-copy-button is-none"')
        self.assertNotContains(response, reverse("wallets:copybetting_pause", args=[self.subscriptions[0].pk]))

    def test_public_copy_actions_return_to_profile_and_change_owned_strategy(self):
        subscription = self.subscriptions[1]
        target = reverse("front:expert_profile", args=[subscription.analyst.username])
        for action, state in (("pause", "paused"), ("resume", "active"), ("stop", "stopped")):
            response = self.client.post(reverse(f"wallets:copybetting_{action}", args=[subscription.pk]), {"next": target})
            self.assertRedirects(response, target, fetch_redirect_response=False)
            subscription.refresh_from_db()
            self.assertEqual(subscription.status, state)
        self.assertEqual(build_public_copybetting_context(self.reader, subscription.analyst)["public_copybetting"]["status"], "stopped")

    def test_status_ajax_returns_updated_public_strips_and_buttons(self):
        subscription = self.subscriptions[1]
        for action, state in (("pause", "paused"), ("resume", "active"), ("stop", "stopped")):
            response = self.client.post(reverse(f"wallets:copybetting_{action}", args=[subscription.pk]), {"surface": "public"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("Location", response)
            payload = response.json()
            self.assertEqual(payload["status"], state)
            self.assertIn(f'is-{state} is-desktop', payload["desktop_html"])
            self.assertIn(f'is-{state} is-mobile', payload["mobile_html"])
            self.assertIn('data-copy-hero-button="desktop"', payload["desktop_button_html"])
            self.assertIn('data-copy-hero-button="mobile"', payload["mobile_button_html"])
            self.assertIn("message", payload)
        # The endpoint still scopes every operation to the current reader.
        response = self.client.post(reverse("wallets:copybetting_pause", args=[self.foreign.pk]), {"surface": "reader"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 404)

    def test_status_ajax_updates_reader_filters_and_summary_without_redirect(self):
        subscription = self.subscriptions[1]
        next_url = reverse("cabinet:profile") + "?tab=copybetting&copy_status=active&copy_sort=date"
        response = self.client.post(reverse("wallets:copybetting_pause", args=[subscription.pk]), {"surface": "reader", "next": next_url}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "paused")
        self.assertNotIn(f'data-copy-reader-id="{subscription.pk}"', payload["reader_html"])
        self.assertIn("6", payload["summary_html"])
        self.assertIn("3 на паузе", payload["summary_html"])
        self.assertIn('data-copy-status-form', payload["reader_html"])
        self.assertIn('class="expert-copy-more"', payload["reader_html"])
        self.assertNotIn("Location", response)

    def test_status_ajax_is_csrf_protected(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reader)
        response = client.post(reverse("wallets:copybetting_pause", args=[self.subscriptions[1].pk]), {"surface": "public"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)

    def test_pending_pause_keeps_resume_and_stop_controls_after_ajax(self):
        from unittest.mock import patch
        subscription = self.subscriptions[1]
        next_url = reverse("cabinet:profile") + f"?tab=copybetting&copy_q={subscription.analyst.username}"
        with patch("wallets.services._has_started_pending_copied_bets", return_value=True):
            response = self.client.post(reverse("wallets:copybetting_pause", args=[subscription.pk]), {"surface": "reader", "next": next_url}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["pending_status"], "paused")
        self.assertIn(reverse("wallets:copybetting_resume", args=[subscription.pk]), payload["reader_html"])
        self.assertIn(reverse("wallets:copybetting_stop", args=[subscription.pk]), payload["reader_html"])
        self.assertIn("Продолжить", payload["reader_html"])
        from django.template.loader import render_to_string
        context = build_public_copybetting_context(self.reader, subscription.analyst)
        public_html = render_to_string("cabinet/includes/_expert_copybetting_bar.html", context)
        self.assertIn(reverse("wallets:copybetting_resume", args=[subscription.pk]), public_html)
        self.assertIn(reverse("wallets:copybetting_stop", args=[subscription.pk]), public_html)
        response = self.client.post(reverse("wallets:copybetting_resume", args=[subscription.pk]), {"surface": "reader", "next": next_url}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.json()["pending_status"], "")
        self.assertIn(reverse("wallets:copybetting_pause", args=[subscription.pk]), response.json()["reader_html"])

    def test_pending_stop_keeps_stop_icon_and_allows_cancelling(self):
        subscription = self.subscriptions[1]
        subscription.pending_status = "stopped"
        subscription.save(update_fields=["pending_status"])
        data = build_public_copybetting_context(self.reader, subscription.analyst)["public_copybetting"]
        self.assertTrue(data["can_stop"])
        self.assertTrue(data["stop_pending"])
        self.assertTrue(data["can_resume"])

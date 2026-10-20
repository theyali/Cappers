from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from decimal import Decimal
from threading import Event
from uuid import uuid4
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystPaidSubscription, DirectMessage, User
from cabinet.services.copybetting import build_copybetting_context, build_public_copybetting_context
from cabinet.services.messages import send_direct_message
from cabinet.trust_index import CapperTrustIndexService
from notifications.models import Notification
from wallets.capper_bank import calculate_capper_bank_stats
from wallets.models import CoinWallet, CopiedBet, CopyBettingAudiencePreference, CopyBettingBlock, CopyBettingLimits, CopyBettingSubscription
from wallets.services import activate_copybetting, block_copybetting_user, copy_published_coupon, pause_copybetting, resume_copybetting, settle_copied_bets_for_coupon, stop_copybetting, unblock_copybetting_user
from game.models import PredictionCoupon

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


class Fixtures:
    def make_fixtures(self):
        self.author = User.objects.create_user(username="control-author", role=User.Role.ANALYST)
        self.reader = User.objects.create_user(username="control-reader")
        self.other = User.objects.create_user(username="control-other", role=User.Role.ANALYST)
        self.subscription = activate_copybetting(user=self.reader, analyst=self.author, bank_amount=1000, stake_percent=10)

    def coupon(self, author=None, state="pending"):
        coupon = PredictionCoupon.objects.create(author=author or self.author, total_stake=100, possible_payout=200)
        PredictionCoupon.objects.filter(pk=coupon.pk).update(published_status="published", published_at=timezone.now(), state_status=state)
        coupon.refresh_from_db()
        return coupon


@override_settings(STORAGES=STORAGES)
class CopybettingControlTests(Fixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def test_block_is_idempotent_retains_bets_and_prevents_all_activation_paths(self):
        coupon = self.coupon()
        accepted = copy_published_coupon(coupon)[0]
        before = CoinWallet.objects.get(user=self.reader).balance
        block = block_copybetting_user(analyst=self.author, user=self.reader)
        self.assertEqual(block_copybetting_user(analyst=self.author, user=self.reader).pk, block.pk)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "stopped")
        self.assertEqual(self.subscription.pending_status, "")
        for call in (lambda: activate_copybetting(user=self.reader, analyst=self.author, bank_amount=1000, stake_percent=10), lambda: resume_copybetting(self.subscription)):
            with self.assertRaisesMessage(ValidationError, "запретил"):
                call()
        # Even a stale worker or direct status change cannot bypass the separate block.
        CopyBettingSubscription.objects.filter(pk=self.subscription.pk).update(status="active")
        self.assertEqual(copy_published_coupon(self.coupon()), [])
        self.assertEqual(CoinWallet.objects.get(user=self.reader).balance, before)
        self.assertTrue(CopiedBet.objects.filter(pk=accepted.pk).exists())
        settle_copied_bets_for_coupon(coupon, outcome="lose")
        accepted.refresh_from_db()
        self.assertEqual(accepted.profit, -100)
        self.assertEqual(Notification.objects.filter(event_key__startswith=f"copybetting-block:{block.pk}:created:").count(), 2)

    def test_unblock_preserves_history_does_not_auto_activate(self):
        block_copybetting_user(analyst=self.author, user=self.reader)
        unblock_copybetting_user(analyst=self.author, user=self.reader)
        unblock_copybetting_user(analyst=self.author, user=self.reader)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "stopped")
        self.assertIsNotNone(CopyBettingBlock.objects.get().revoked_at)
        self.assertEqual(copy_published_coupon(self.coupon()), [])
        activate_copybetting(user=self.reader, analyst=self.author, bank_amount=1000, stake_percent=10)
        self.assertEqual(len(copy_published_coupon(self.coupon())), 1)
        self.assertEqual(Notification.objects.filter(event_key__startswith="copybetting-block:").count(), 4)
        self.assertGreaterEqual(self.subscription.transitions.count(), 3)

    def test_author_endpoints_scope_csrf_and_server_hidden_preference(self):
        url = reverse("cabinet:copybetting_block", args=[self.reader.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.author)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.author)
        self.assertEqual(csrf.post(url).status_code, 403)
        hide = reverse("cabinet:copybetting_hide", args=[self.reader.pk])
        self.assertEqual(self.client.post(hide).status_code, 200)
        self.assertEqual(build_copybetting_context(self.author, {})["copybetting_people"], [])
        shown = build_copybetting_context(self.author, {"copy_show_hidden": "1"})
        self.assertTrue(shown["copybetting_people"][0]["hidden"])
        self.assertEqual(shown["copybetting_audience_total_count"], 1)
        another_session = Client(); another_session.force_login(self.author)
        self.assertNotIn(f'data-copy-person="{self.reader.pk}"', another_session.get(reverse("cabinet:copybetting_audience")).json()["html"])
        self.client.post(reverse("cabinet:copybetting_unhide", args=[self.reader.pk]))
        self.assertEqual(len(build_copybetting_context(self.author, {})["copybetting_people"]), 1)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertTrue(build_copybetting_context(self.author, {})["copybetting_people"][0]["blocked"])
        self.assertTrue(build_public_copybetting_context(self.reader, self.author)["public_copybetting"]["blocked"])
        payload = self.client.get(reverse("cabinet:copybetting_audience")).json()
        self.assertIn("summary_html", payload)
        self.assertIn("Копирование запрещено", payload["html"])
        self.assertEqual(build_copybetting_context(self.author, {})["copybetting_audience_active_count"], 0)

    def test_reader_sees_block_reason_and_cannot_access_foreign_history(self):
        block_copybetting_user(analyst=self.author, user=self.reader)
        self.client.force_login(self.reader)
        response = self.client.get(reverse("wallets:copybetting_setup", args=[self.author.pk]))
        self.assertContains(response, "Автор запретил")
        self.assertContains(response, 'data-copy-blocked="true"')
        self.assertEqual(self.client.get(reverse("cabinet:copybetting_history", args=[self.subscription.pk])).status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("cabinet:copybetting_history", args=[self.subscription.pk])).status_code, 404)

    def test_global_budget_is_shared_by_authors_and_rolls_over_each_day(self):
        activate_copybetting(user=self.reader, analyst=self.other, bank_amount=1000, stake_percent=10)
        CopyBettingLimits.objects.create(user=self.reader, daily_budget=150)
        first = copy_published_coupon(self.coupon())[0]
        self.assertEqual(copy_published_coupon(self.coupon(self.other)), [])
        self.assertEqual(CoinWallet.objects.get(user=self.reader).balance, 900)
        CopiedBet.objects.filter(pk=first.pk).update(created_at=timezone.now()-timedelta(days=1))
        self.assertEqual(len(copy_published_coupon(self.coupon(self.other))), 1)

    def test_daily_limits_use_site_timezone_regardless_of_reader_timezone(self):
        from wallets.services import copybetting_day_start
        with timezone.override("Asia/Baku"):
            expected = copybetting_day_start()
        with timezone.override("Pacific/Auckland"):
            self.assertEqual(copybetting_day_start(), expected)

    def test_global_stop_loss_uses_real_settled_net_profit(self):
        CopyBettingLimits.objects.create(user=self.reader, daily_stop_loss=100)
        coupon = self.coupon()
        copy_published_coupon(coupon)
        settle_copied_bets_for_coupon(coupon, outcome="lose")
        self.assertEqual(copy_published_coupon(self.coupon()), [])
        CopiedBet.objects.update(settled_at=timezone.now()-timedelta(days=1))
        self.assertEqual(len(copy_published_coupon(self.coupon())), 1)

    def test_limits_endpoint_is_scoped_and_validated(self):
        self.client.force_login(self.reader)
        url = reverse("cabinet:copybetting_limits")
        self.assertEqual(self.client.post(url, {"daily_budget": -1, "daily_stop_loss": 0}).status_code, 400)
        self.assertEqual(self.client.post(url, {"daily_budget": 100, "daily_stop_loss": 50}).status_code, 200)
        self.assertEqual(CopyBettingLimits.objects.get(user=self.reader).daily_budget, 100)
        self.client.force_login(self.author)
        self.assertEqual(self.client.post(url, {"daily_budget": 0, "daily_stop_loss": 0}).status_code, 403)

    def test_active_and_paused_count_towards_thirty(self):
        authors = User.objects.bulk_create([User(username=f"quota-author-{i}", role=User.Role.ANALYST) for i in range(30)])
        CopyBettingSubscription.objects.bulk_create([CopyBettingSubscription(user=self.reader, analyst=author, bank_amount=1000, stake_percent=10, status="paused") for author in authors[:29]])
        with self.assertRaisesMessage(ValidationError, "30"):
            activate_copybetting(user=self.reader, analyst=authors[29], bank_amount=1000, stake_percent=10)
        pause_copybetting(self.subscription)
        resume_copybetting(self.subscription)
        stop_copybetting(self.subscription)
        activate_copybetting(user=self.reader, analyst=authors[29], bank_amount=1000, stake_percent=10)
        with self.assertRaisesMessage(ValidationError, "30"):
            resume_copybetting(self.subscription)

    def test_trust_roi_distance_and_drawdown_ignore_followers_and_paid_access(self):
        coupon = self.coupon(state="win")
        baseline = CapperTrustIndexService(self.author.pk).calculate()
        bank = calculate_capper_bank_stats(self.author.pk)
        copy_published_coupon(coupon)
        CopyBettingSubscription.objects.filter(pk=self.subscription.pk).update(total_profit=999999, status="stopped")
        CopiedBet.objects.update(profit=-100000)
        AnalystPaidSubscription.objects.create(subscriber=self.reader, analyst=self.author, price=99999, expires_at=timezone.now()+timedelta(days=1))
        self.assertEqual(CapperTrustIndexService(self.author.pk).calculate(), baseline)
        self.assertEqual(calculate_capper_bank_stats(self.author.pk), bank)
        PredictionCoupon.objects.filter(pk=coupon.pk).update(state_status="lose")
        changed = CapperTrustIndexService(self.author.pk).calculate()
        self.assertNotEqual(changed.metrics["roi"], baseline.metrics["roi"])

    def test_direct_messages_private_idempotent_escaped_and_notification_once(self):
        cache.clear()
        token = uuid4()
        message = send_direct_message(sender=self.author, recipient=self.reader, body='<script>alert(1)</script>', client_id=token)
        self.assertEqual(send_direct_message(sender=self.author, recipient=self.reader, body=message.body, client_id=token).pk, message.pk)
        self.assertEqual(Notification.objects.filter(event_key=f"direct-message:{message.pk}").count(), 1)
        self.client.force_login(self.other)
        response = self.client.get(reverse("cabinet:dialog", args=[self.author.username]))
        self.assertNotContains(response, "alert(1)")
        self.client.force_login(self.reader)
        response = self.client.get(reverse("cabinet:dialog", args=[self.author.username]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        message.refresh_from_db(); self.assertIsNotNone(message.read_at)
        with self.assertRaises(ValidationError):
            send_direct_message(sender=self.author, recipient=self.reader, body="another", client_id=token)

    def test_promoting_reader_preserves_bets_and_records_stop(self):
        bet = copy_published_coupon(self.coupon())[0]
        self.reader.role = User.Role.ANALYST
        self.reader.save(update_fields=["role"])
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "stopped")
        self.assertEqual(self.subscription.transitions.last().reason, "Пользователь стал каппером")
        self.assertTrue(CopiedBet.objects.filter(pk=bet.pk).exists())

    def test_message_csrf_rate_limit_and_notification_preference(self):
        cache.clear()
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.author)
        self.assertEqual(csrf.post(reverse("cabinet:dialog", args=[self.reader.username]), {"body": "hello", "client_id": uuid4()}).status_code, 403)
        with mock.patch("cabinet.services.messages.rate_limited", return_value=True):
            with self.assertRaisesMessage(ValidationError, "Слишком много"):
                send_direct_message(sender=self.author, recipient=self.reader, body="hello", client_id=uuid4())
        self.assertFalse(DirectMessage.objects.exists())
        self.client.force_login(self.reader)
        self.client.post(reverse("notifications:preferences"), {"in_app_enabled": "on"})
        message = send_direct_message(sender=self.author, recipient=self.reader, body="hello", client_id=uuid4())
        self.assertFalse(Notification.objects.filter(event_key=f"direct-message:{message.pk}").exists())
        self.assertContains(self.client.get(reverse("notifications:center")), 'name="direct_messages"')


@override_settings(STORAGES=STORAGES)
class CopybettingConcurrencyTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.make_fixtures()

    def in_thread(self, fn):
        close_old_connections()
        try:
            return fn()
        finally:
            connections.close_all()

    @skipUnlessDBFeature("has_select_for_update")
    def test_block_commits_before_worker_creates_copy(self):
        coupon = self.coupon()
        entered, release = Event(), Event()
        def block():
            with transaction.atomic():
                block_copybetting_user(analyst=self.author, user=self.reader)
                entered.set()
                if not release.wait(5): raise AssertionError("release timeout")
        with ThreadPoolExecutor(max_workers=2) as pool:
            blocker = pool.submit(self.in_thread, block)
            self.assertTrue(entered.wait(5))
            worker = pool.submit(self.in_thread, lambda: copy_published_coupon(coupon))
            try:
                with self.assertRaises(TimeoutError): worker.result(timeout=.15)
            finally:
                release.set()
            blocker.result(timeout=5)
            self.assertEqual(worker.result(timeout=5), [])
        self.assertEqual(CoinWallet.objects.get(user=self.reader).balance, 1000)
        self.assertFalse(CopiedBet.objects.exists())

    @skipUnlessDBFeature("has_select_for_update")
    def test_copy_already_accepted_is_retained_when_block_waits(self):
        coupon = self.coupon()
        entered, release = Event(), Event()
        def copy():
            with transaction.atomic():
                result = copy_published_coupon(coupon)
                entered.set()
                if not release.wait(5): raise AssertionError("release timeout")
                return result
        with ThreadPoolExecutor(max_workers=2) as pool:
            worker = pool.submit(self.in_thread, copy)
            self.assertTrue(entered.wait(5))
            blocker = pool.submit(self.in_thread, lambda: block_copybetting_user(analyst=self.author, user=self.reader))
            try:
                with self.assertRaises(TimeoutError): blocker.result(timeout=.15)
            finally:
                release.set()
            self.assertEqual(len(worker.result(timeout=5)), 1)
            blocker.result(timeout=5)
        self.assertEqual(CopiedBet.objects.count(), 1)
        self.assertEqual(CopyBettingSubscription.objects.get(pk=self.subscription.pk).status, "stopped")

    @skipUnlessDBFeature("has_select_for_update")
    def test_parallel_copies_cannot_overrun_shared_budget(self):
        CopyBettingLimits.objects.create(user=self.reader, daily_budget=100)
        coupons = [self.coupon(), self.coupon()]
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(self.in_thread, lambda coupon=coupon: copy_published_coupon(coupon)) for coupon in coupons]
            self.assertEqual(sum(len(job.result(timeout=10)) for job in jobs), 1)
        self.assertEqual(CoinWallet.objects.get(user=self.reader).balance, 900)

    @skipUnlessDBFeature("has_select_for_update")
    def test_parallel_activation_cannot_exceed_thirty_strategies(self):
        authors = User.objects.bulk_create([User(username=f"parallel-quota-{i}", role=User.Role.ANALYST) for i in range(30)])
        CopyBettingSubscription.objects.bulk_create([
            CopyBettingSubscription(user=self.reader, analyst=author, bank_amount=1000, stake_percent=10, status="paused")
            for author in authors[:28]
        ])
        def activate(author):
            try:
                activate_copybetting(user=self.reader, analyst=author, bank_amount=1000, stake_percent=10)
                return True
            except ValidationError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(self.in_thread, lambda author=author: activate(author)) for author in authors[28:]]
            self.assertEqual(sum(job.result(timeout=10) for job in jobs), 1)
        self.assertEqual(CopyBettingSubscription.objects.filter(user=self.reader, status__in=["active", "paused"]).count(), 30)

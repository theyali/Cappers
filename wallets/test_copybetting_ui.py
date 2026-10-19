from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError

from cabinet.models import AnalystFollow, AnalystPaidSubscription, User
from game.models import Match, Prediction, PredictionCoupon, Sport
from wallets.copybetting_ui import build_capper_search_context
from wallets.forms import CopyBettingForm
from wallets.models import CopiedBet, CopyBettingSubscription
from wallets.services import ensure_coin_wallet


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class CopybettingDiscoverySetupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reader = User.objects.create_user(username="ad-reader")
        cls.analysts = []
        for number in range(8):
            user = User.objects.create_user(username=f"ad-capper-{number}", role=User.Role.ANALYST,
                                            email=f"capper{number}@example.com")
            user.analyst_profile.display_name = f"Аналитик {number}"
            user.analyst_profile.trust_index = Decimal(number + 1)
            user.analyst_profile.is_verified = number % 2 == 0
            user.analyst_profile.save(update_fields=["display_name", "trust_index", "is_verified"])
            cls.analysts.append(user)
        cls.private = User.objects.create_user(username="ad-private", role=User.Role.ANALYST)
        cls.private.analyst_profile.is_public = False
        cls.private.analyst_profile.save(update_fields=["is_public"])
        cls.inactive = User.objects.create_user(username="ad-inactive", role=User.Role.ANALYST, is_active=False)
        cls.analyst = cls.analysts[0]
        cls.football = Sport.objects.create(code="football", name="Football", name_ru="Футбол")
        cls.basketball = Sport.objects.create(code="basketball", name="Basketball", name_ru="Баскетбол")
        for number, sport in enumerate([cls.football, cls.basketball, cls.football]):
            match = Match.objects.create(external_id=986010+number, sport=sport)
            coupon = PredictionCoupon.objects.create(author=cls.analyst, total_stake=100, possible_payout=195,
                                                     published_status="published", audience="paid" if number == 2 else "free",
                                                     headline="СЕКРЕТНЫЙ ЗАГОЛОВОК" if number == 2 else "Проверочный прогноз",
                                                     description="СЕКРЕТНОЕ ОПИСАНИЕ" if number == 2 else "")
            Prediction.objects.create(coupon=coupon, match=match, market="winner", selection="СЕКРЕТНЫЙ ИСХОД" if number == 2 else "П1",
                                      coefficient=Decimal("1.95"), stake=100)

    def setUp(self):
        self.client.force_login(self.reader)
        self.data = {"bank_amount": "10000", "stake_percent": "5", "max_single_stake": "0", "stop_loss_amount": "0",
                     "min_total_coefficient": "1.01", "coupon_types": "both", "allowed_sports": [self.football.pk]}

    def search(self, **params):
        return self.client.post(reverse("wallets:copybetting_search"), params)

    def preview(self, **changes):
        return self.client.post(reverse("wallets:copybetting_preview", args=[self.analyst.pk]), {**self.data, **changes})

    def test_search_is_private_read_only_and_excludes_unavailable_profiles(self):
        response = self.search(sort="trust")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        html = response.json()["html"]
        self.assertIn("ad-capper-7", html)
        self.assertNotIn("ad-private", html)
        self.assertNotIn("ad-inactive", html)
        self.assertNotIn("capper7@example.com", html)
        self.assertEqual(CopyBettingSubscription.objects.filter(user=self.reader).count(), 0)
        self.assertEqual(self.client.get(reverse("wallets:copybetting_search")).status_code, 405)
        self.client.logout()
        self.assertEqual(self.search().status_code, 302)
        self.client.force_login(self.analyst)
        self.assertEqual(self.search().status_code, 403)

    def test_search_by_name_username_and_exact_email(self):
        for query in ["@ad-capper-3", "Аналитик 3"]:
            html = self.search(q=query).json()["html"]
            self.assertIn("ad-capper-3", html)
            self.assertNotIn("ad-capper-4", html)
        html = self.search(q="CAPPER3@EXAMPLE.COM").json()["html"]
        self.assertIn("ad-capper-3", html)
        self.assertIn("c****3@example.com", html)
        self.assertNotIn("capper3@example.com", html)
        self.assertNotIn("ad-capper-3", self.search(q="capper3@").json()["html"])

    def test_search_paging_verified_filter_and_copying_badge(self):
        CopyBettingSubscription.objects.create(user=self.reader, analyst=self.analysts[7], bank_amount=1000, stake_percent=5)
        first = self.search(sort="trust").json()["html"]
        second = self.search(sort="trust", page=2).json()["html"]
        self.assertIn("Копирую", first)
        self.assertIn("data-copy-discovery-more", first)
        self.assertNotIn("data-copy-discovery-more", second)
        self.assertNotIn("ad-capper-7", second)
        verified = self.search(verified="1").json()["html"]
        self.assertIn("ad-capper-6", verified)
        self.assertNotIn("ad-capper-7", verified)

    def test_directory_counts_do_not_join_coupons_to_followers(self):
        AnalystFollow.objects.create(follower=self.reader, analyst=self.analyst)
        AnalystFollow.objects.create(follower=self.private, analyst=self.analyst)
        for sort in ("roi", "followers"):
            with CaptureQueriesContext(connection) as queries:
                context = build_capper_search_context(self.reader, {"q": "@ad-capper-0", "sort": sort})
            self.assertEqual(len(queries), 2)
            # Counting matching people must not aggregate their entire betting history.
            self.assertNotIn("game_predictioncoupon", queries[0]["sql"])
            self.assertNotIn("cabinet_analystfollow", queries[0]["sql"])
            self.assertNotIn('JOIN "game_predictioncoupon"', queries[1]["sql"])
            self.assertNotIn('JOIN "cabinet_analystfollow"', queries[1]["sql"])
            self.assertEqual(context["search_total"], 1)
            self.assertEqual(context["search_cappers"][0]["coupons"], 3)
            self.assertEqual(context["search_cappers"][0]["win_rate"], 0)

    def test_setup_page_renders_new_fields_and_no_inline_styles(self):
        response = self.client.get(reverse("wallets:copybetting_setup", args=[self.analyst.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-copy-setup-form")
        self.assertContains(response, 'name="coupon_types"')
        self.assertContains(response, "Как это сработало бы")
        self.assertNotContains(response, "<style>")
        self.assertNotContains(response, "5 000 C в день")
        self.assertNotContains(response, "СЕКРЕТНЫЙ")
        self.assertContains(response, '<section class="copybetting-setup-surface">', count=1)
        self.assertContains(response, 'class="copybetting-setup-profile-link"')

    def test_preview_uses_real_rules_without_creating_copies_or_charging(self):
        wallet = ensure_coin_wallet(self.reader)
        before = wallet.balance
        response = self.preview()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("500", payload["calculation"])
        self.assertIn("Вид спорта не выбран", payload["html"])
        self.assertNotIn("Содержимое скрыто", payload["html"])
        self.assertNotIn("СЕКРЕТНЫЙ", payload["html"])
        self.assertEqual(CopyBettingSubscription.objects.filter(user=self.reader).count(), 0)
        self.assertEqual(CopiedBet.objects.filter(user=self.reader).count(), 0)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, before)

    def test_preview_honors_cap_coefficient_and_types(self):
        payload = self.preview(bank_amount="10003", max_single_stake="400").json()
        self.assertIn("400", payload["calculation"])
        self.assertIn("ограничена максимумом", payload["calculation"])
        self.assertIn("Коэффициент ниже порога", self.preview(min_total_coefficient="2").json()["html"])
        self.assertIn("Тип прогноза не выбран", self.preview(coupon_types="tournament").json()["html"])
        self.assertIn("Укажите банк", self.preview(bank_amount="").json()["calculation"])
        ten_percent = self.preview(stake_percent="10").json()["calculation"]
        self.assertIn("10%", ten_percent)
        self.assertNotIn("1E+1", ten_percent)
        zero = self.preview(bank_amount="1", stake_percent="0.01").json()
        self.assertIn("Минимальная сумма копируемой ставки", zero["calculation"])
        self.assertIn("Минимум 100 C", zero["html"])

    def test_new_type_selector_saves_existing_model_flags_and_only_future_copying(self):
        url = reverse("wallets:copybetting_setup", args=[self.analyst.pk])
        response = self.client.post(url, {**self.data, "coupon_types": "regular"})
        self.assertEqual(response.status_code, 302)
        subscription = CopyBettingSubscription.objects.get(user=self.reader, analyst=self.analyst)
        self.assertTrue(subscription.copy_regular_coupons)
        self.assertFalse(subscription.copy_tournament_coupons)
        self.assertEqual(list(subscription.allowed_sports.all()), [self.football])
        self.assertEqual(CopiedBet.objects.filter(user=self.reader).count(), 0)
        form = CopyBettingForm({**self.data, "coupon_types": "both", "allowed_sports": []})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.cleaned_data["copy_tournament_coupons"])

    def test_invalid_settings_preserve_input_without_mutation_and_legacy_fields_work(self):
        response = self.client.post(reverse("wallets:copybetting_setup", args=[self.analyst.pk]), {**self.data, "stake_percent": "101"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="101"')
        self.assertContains(response, "Проверьте параметры")
        self.assertFalse(CopyBettingSubscription.objects.filter(user=self.reader).exists())
        data = {key: value for key, value in self.data.items() if key != "coupon_types"}
        data.update(copy_regular_coupons="on", copy_tournament_coupons="on")
        form = CopyBettingForm(data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_search_and_preview_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reader)
        self.assertEqual(client.post(reverse("wallets:copybetting_search"), {}).status_code, 403)
        self.assertEqual(client.post(reverse("wallets:copybetting_preview", args=[self.analyst.pk]), self.data).status_code, 403)

    def test_preview_filters_paid_before_taking_latest_three(self):
        free = PredictionCoupon.objects.filter(author=self.analyst, audience="free").first()
        free.pk = None
        free.headline = "Ещё бесплатный"
        free.save()
        payload = self.preview().json()
        self.assertEqual(payload["html"].count('<article class='), 3)
        self.assertNotIn("СЕКРЕТНЫЙ", payload["html"])
        self.assertNotIn("Содержимое скрыто", payload["html"])
        paid = AnalystPaidSubscription.objects.create(subscriber=self.reader, analyst=self.analyst, price=100, expires_at=timezone.now()+timedelta(days=1))
        self.assertIn("СЕКРЕТНЫЙ ИСХОД", self.preview().json()["html"])
        paid.expires_at = timezone.now()-timedelta(seconds=1)
        paid.save(update_fields=["expires_at"])
        self.assertNotIn("СЕКРЕТНЫЙ", self.preview().json()["html"])
        paid.expires_at = timezone.now()+timedelta(days=2)
        paid.starts_at = timezone.now()+timedelta(days=1)
        paid.save(update_fields=["expires_at", "starts_at"])
        self.assertNotIn("СЕКРЕТНЫЙ", self.preview().json()["html"])

    def test_minimum_stake_and_coefficient_validated_without_js(self):
        for changes in ({"bank_amount": "1000", "stake_percent": "1"}, {"max_single_stake": "99"}, {"min_total_coefficient": "0"}, {"min_total_coefficient": "1"}):
            payload = self.preview(**changes).json()
            self.assertFalse(payload["valid"])
            self.assertTrue(payload["errors"])
            response = self.client.post(reverse("wallets:copybetting_setup", args=[self.analyst.pk]), {**self.data, **changes})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(CopyBettingSubscription.objects.filter(user=self.reader).exists())
        self.assertTrue(self.preview(bank_amount="1000", stake_percent="10").json()["valid"])
        page = self.client.get(reverse("wallets:copybetting_setup", args=[self.analyst.pk]))
        self.assertContains(page, 'min="1.01"')
        self.assertContains(page, 'value="1.01"')

    def test_mobile_discovery_pages_four_cappers_without_skipping_results(self):
        first = self.search(sort="trust", page_size=4, page=1).json()["html"]
        second = self.search(sort="trust", page_size=4, page=2).json()["html"]
        self.assertEqual(first.count('class="copybetting-search-result"'), 4)
        self.assertEqual(second.count('class="copybetting-search-result"'), 4)
        self.assertIn("ad-capper-7", first)
        self.assertNotIn("ad-capper-7", second)
        self.assertIn("ad-capper-0", second)
        self.assertNotIn("ad-capper-0", first)
        # Other values do not allow unbounded requests.
        default = self.search(page_size=99999).json()["html"]
        self.assertEqual(default.count('class="copybetting-search-result"'), 6)

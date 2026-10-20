from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystFollow, AnalystPaidSubscription, AnalystProfile, User
from game.models import Match, Prediction, PredictionCoupon, Sport


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class PaidPredictionPaywallTests(TestCase):
    def setUp(self):
        cache.clear()
        self.author = User.objects.create_user(
            username="paid-author",
            password="secret",
            role=User.Role.ANALYST,
        )
        profile, _ = AnalystProfile.objects.get_or_create(user=self.author)
        profile.display_name = "Платный автор"
        profile.paid_predictions_enabled = True
        profile.paid_predictions_price = Decimal("299")
        profile.save()

        sport = Sport.objects.create(code="paywall-football", name="Football", name_ru="Футбол")
        match = Match.objects.create(
            external_id=998877,
            sport=sport,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={
                "league": {"name": {"ru": "Премьер-лига"}},
                "teams": {
                    "home": {"name": {"ru": "Команда А"}},
                    "away": {"name": {"ru": "Команда Б"}},
                },
            },
        )
        self.coupon = PredictionCoupon.objects.create(
            author=self.author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.PAID,
            prediction_format=PredictionCoupon.PredictionFormat.RICH,
            total_stake=Decimal("500"),
            possible_payout=Decimal("975"),
            description="Секретный разбор платного прогноза",
        )
        Prediction.objects.create(
            coupon=self.coupon,
            match=match,
            market="Победитель",
            selection="Секретный исход П1",
            coefficient=Decimal("1.95"),
            stake=Decimal("500"),
        )
        follower = User.objects.create_user(username="public-follower", password="secret")
        follower.avatar = "users/avatars/follower.webp"
        follower.save(update_fields=["avatar"])
        AnalystFollow.objects.create(follower=follower, analyst=self.author)

    def test_direct_link_shows_paywall_without_paid_content(self):
        response = self.client.get(
            reverse("front:prediction_detail", kwargs={"prediction_id": self.coupon.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "front/paid_prediction_paywall.html")
        self.assertContains(response, "Прогноз закрыт")
        self.assertContains(response, "Открыть за 299 ₽")
        self.assertContains(response, "Подписка — 299 ₽ / 30 дней")
        self.assertContains(response, "users/avatars/follower.webp")
        self.assertContains(response, "на автора подписаны <b>1 человек</b>", html=True)
        self.assertNotContains(response, "Секретный исход П1")
        self.assertNotContains(response, "Секретный разбор платного прогноза")
        self.assertNotContains(response, "Команда А")
        self.assertNotContains(response, "Команда Б")
        self.assertNotContains(response, "Премьер-лига")
        self.assertNotContains(response, "1.95")

    def test_active_subscriber_sees_regular_coupon_detail(self):
        subscriber = User.objects.create_user(username="paid-reader", password="secret")
        AnalystPaidSubscription.objects.create(
            subscriber=subscriber,
            analyst=self.author,
            price=Decimal("299"),
            duration_days=30,
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(subscriber)

        response = self.client.get(
            reverse("front:prediction_detail", kwargs={"prediction_id": self.coupon.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "front/prediction_detail.html")
        self.assertContains(response, "Секретный разбор платного прогноза")

    def test_author_sees_regular_coupon_detail(self):
        self.client.force_login(self.author)

        response = self.client.get(
            reverse("front:prediction_detail", kwargs={"prediction_id": self.coupon.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "front/prediction_detail.html")

    def test_paid_catalog_lists_locked_predictions_for_anonymous_visitors(self):
        response = self.client.get(
            f"{reverse('front:predictions')}?prediction_type=paid"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "feed-prediction-card is-paid-locked")
        self.assertContains(response, "Платный автор")
        self.assertContains(response, "Выбрать тариф")
        self.assertNotContains(response, 'aria-label="Статус прогнозов"')
        self.assertNotContains(response, "Секретный исход П1")
        self.assertNotContains(response, "Секретный разбор платного прогноза")
        self.assertContains(response, "Команда А")
        self.assertContains(response, "Команда Б")
        self.assertNotContains(response, "1.95")



        html = response.content.decode()
        content_start = html.index("predictions-content matches-list-panel is-paid-catalog")
        breadcrumbs_start = html.index("breadcrumbs-container predictions-content-breadcrumbs")
        self.assertGreater(breadcrumbs_start, content_start)
        self.assertEqual(html.count("breadcrumbs-container"), 1)

    def test_paid_catalog_removes_status_filter_from_url(self):
        response = self.client.get(
            f"{reverse('front:predictions')}?prediction_type=paid&status=win"
        )

        self.assertRedirects(
            response,
            f"{reverse('front:predictions')}?prediction_type=paid",
            fetch_redirect_response=False,
        )

    def test_completed_paid_coupon_has_no_purchase_action(self):
        self.coupon.state_status = PredictionCoupon.StateStatus.WIN
        self.coupon.save(update_fields=["state_status"])

        catalog_response = self.client.get(
            f"{reverse('front:predictions')}?prediction_type=paid"
        )
        detail_response = self.client.get(
            reverse("front:prediction_detail", kwargs={"prediction_id": self.coupon.pk})
        )

        self.assertContains(catalog_response, "Покупка закрыта")
        self.assertNotContains(catalog_response, "Выбрать подписку")
        self.assertContains(detail_response, "Покупка рассчитанного купона недоступна")
        self.assertNotContains(detail_response, "Открыть за 299 ₽")
        self.assertNotContains(detail_response, "Подписка — 299 ₽")

    def test_paid_catalog_unlocks_card_for_active_subscriber(self):
        subscriber = User.objects.create_user(username="paid-catalog-reader", password="secret")
        AnalystPaidSubscription.objects.create(
            subscriber=subscriber,
            analyst=self.author,
            price=Decimal("299"),
            duration_days=30,
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(subscriber)

        response = self.client.get(
            f"{reverse('front:predictions')}?prediction_type=paid"
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "is-paid-locked")
        self.assertNotContains(response, "Секретный разбор платного прогноза")
        self.assertContains(response, "Команда А")

    @override_settings(SINGLE_COUPON_SALES_ENABLED=True)
    def test_unified_card_shows_actual_purchase_price_without_pick_or_odds(self):
        profile = self.author.analyst_profile
        profile.single_coupon_sales_enabled = True
        profile.single_coupon_price = Decimal("129")
        profile.save(update_fields=["single_coupon_sales_enabled", "single_coupon_price"])
        self.coupon.single_purchase_enabled = True
        self.coupon.single_purchase_price = Decimal("129")
        self.coupon.save(update_fields=["single_purchase_enabled", "single_purchase_price"])
        response = self.client.get(reverse("front:predictions"), {"prediction_type": "paid"})
        self.assertContains(response, 'class="feed-prediction-bet is-locked"')
        self.assertContains(response, "Купить за 129 ₽")
        self.assertContains(response, reverse("cabinet:single_coupon_checkout", args=[self.coupon.pk]))
        self.assertContains(response, "feed-prediction-cover-format")
        self.assertContains(response, 'aria-label="Текстовый прогноз"')
        self.assertNotContains(response, "Секретный исход П1")
        self.assertNotContains(response, "Секретный разбор платного прогноза")
        self.assertNotContains(response, "1,95")
        self.assertNotContains(response, "1.95")

        match = self.coupon.predictions.first().match
        future_start = match.starts_at
        match.starts_at = timezone.now() - timedelta(minutes=1)
        match.save(update_fields=["starts_at"])
        response = self.client.get(reverse("front:predictions"), {"prediction_type": "paid"})
        self.assertContains(response, "Покупка недоступна")
        self.assertNotContains(response, "Купить за 129 ₽")
        match.starts_at = future_start
        match.save(update_fields=["starts_at"])

        reader = User.objects.create_user(username="unified-paid-reader")
        from cabinet.models import PaidPredictionPurchase
        PaidPredictionPurchase.objects.create(buyer=reader, analyst=self.author, coupon=self.coupon,
            status="paid", price=129, platform_fee_percent=0, platform_fee_amount=0,
            capper_income=129, paid_at=timezone.now())
        self.client.force_login(reader)
        response = self.client.get(reverse("front:predictions"), {"prediction_type": "paid"})
        self.assertNotContains(response, "Купить за 129 ₽")
        self.assertNotContains(response, 'class="feed-prediction-bet is-locked"')
        self.assertContains(response, "feed-prediction-cover-format")
        self.assertContains(response, "1,95")

    def test_free_text_prediction_uses_normal_feed_card_with_document_icon(self):
        self.coupon.audience = "free"
        self.coupon.save(update_fields=["audience"])
        response = self.client.get(reverse("front:predictions"), {"prediction_type": "rich"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "feed-prediction-card")
        self.assertContains(response, 'aria-label="Текстовый прогноз"')
        self.assertNotContains(response, "feed-prediction-purchase")
        self.assertNotContains(response, 'class="feed-prediction-bet is-locked"')

    def test_catalog_combines_all_formats_under_predictions_tab(self):
        match = self.coupon.predictions.first().match
        coupons = {}
        for audience, prediction_format in [("paid", "quick"), ("free", "rich"), ("free", "quick")]:
            coupon = PredictionCoupon.objects.create(author=self.author, published_status="published",
                audience=audience, prediction_format=prediction_format, total_stake=100, possible_payout=200)
            Prediction.objects.create(coupon=coupon, match=match, market="winner", selection="ТАЙНЫЙ ИСХОД" if audience == "paid" else "П1", coefficient=2, stake=100)
            coupons[audience, prediction_format] = coupon
        response = self.client.get(reverse("front:predictions_rich"))
        self.assertEqual(response.status_code, 200)
        cards = {card.id: card for card in response.context["page_obj"]}
        self.assertEqual(set(cards), {self.coupon.pk, *(coupon.pk for coupon in coupons.values())})
        self.assertEqual(response.context["filtered_predictions"], 4)
        self.assertTrue(cards[self.coupon.pk].is_paid_locked)
        self.assertTrue(cards[coupons["paid", "quick"].pk].is_paid_locked)
        tabs = response.context["prediction_head"]["prediction_types"]
        self.assertEqual([tab["key"] for tab in tabs], ["classic", "vip"])
        self.assertTrue(tabs[0]["active"])
        self.assertEqual(tabs[0]["href"], reverse("front:predictions"))
        self.assertNotContains(response, "ТАЙНЫЙ ИСХОД")
        self.assertNotContains(response, "Секретный разбор платного прогноза")
        default = self.client.get(reverse("front:predictions"))
        self.assertEqual([tab["key"] for tab in default.context["prediction_head"]["prediction_types"]], ["classic", "vip"])
        self.assertEqual({card.id for card in default.context["page_obj"]}, set(cards))
        for card in default.context["page_obj"]:
            if card.coupon.audience == "paid":
                self.assertTrue(card.is_paid_locked)

    def test_table_rows_support_all_formats_and_hide_locked_picks_on_all_devices(self):
        self.coupon.single_purchase_enabled = True
        self.coupon.single_purchase_price = Decimal("129")
        self.coupon.save(update_fields=["single_purchase_enabled", "single_purchase_price"])
        for audience, prediction_format in [("paid", "rich"), ("paid", "quick"), ("free", "rich"), ("free", "quick")]:
            with self.subTest(audience=audience, prediction_format=prediction_format):
                self.coupon.audience = audience
                self.coupon.prediction_format = prediction_format
                self.coupon.save(update_fields=["audience", "prediction_format"])
                response = self.client.get(reverse("front:predictions"), {"view_mode": "table"})
                self.assertEqual(response.status_code, 200)
                card = next(card for card in response.context["page_obj"] if card.id == self.coupon.pk)
                html = render_to_string("front/includes/_prediction_table_row.html", {"prediction": card}, request=response.wsgi_request)
                self.assertIn('class="content-table-row prediction-table-row', html)
                self.assertNotIn("feed-prediction-card", html)
                if audience == "paid":
                    self.assertIn("129 ₽", html)
                    self.assertIn("Исход скрыт", html)
                    self.assertNotIn("Секретный исход П1", html)
                    self.assertNotIn("Победитель", html)
                    self.assertNotIn("1,95", html)
                    self.assertNotIn("1.95", html)
                else:
                    self.assertIn("Секретный исход П1", html)
                    self.assertIn("1,95", html)

    def test_subscriber_sees_pick_and_odds_in_paid_table_row(self):
        subscriber = User.objects.create_user(username="paid-table-reader")
        AnalystPaidSubscription.objects.create(subscriber=subscriber, analyst=self.author,
            price=299, duration_days=30, expires_at=timezone.now() + timedelta(days=30))
        self.client.force_login(subscriber)
        response = self.client.get(reverse("front:predictions"), {"view_mode": "table"})
        card = next(card for card in response.context["page_obj"] if card.id == self.coupon.pk)
        html = render_to_string("front/includes/_prediction_table_row.html", {"prediction": card}, request=response.wsgi_request)
        self.assertIn("prediction-table-row", html)
        self.assertIn("Секретный исход П1", html)
        self.assertIn("1,95", html)
        self.assertNotIn("Исход скрыт", html)

    def test_catalog_vip_sidebar_keeps_top_toggle_in_toolbar_after_ajax(self):
        for top_only in (False, True):
            with self.subTest(top_only=top_only):
                response = self.client.get(reverse("front:predictions"),
                    {"top": "1"} if top_only else {},
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest" if top_only else "")
                self.assertEqual(response.status_code, 200)
                self.assertIn("vip_prediction_rail", response.context)
                html = response.content.decode()
                sidebar = html.split('data-prediction-filter-sidebar', 1)[1].split('</aside>', 1)[0]
                self.assertIn('class="vip-prediction-rail"', sidebar)
                self.assertNotIn('predictions-sidebar-top-toggle', sidebar)
                self.assertEqual(html.count('data-top-experts-tab'), 1)
                utility = html.split('class="matches-head-util is-predictions"', 1)[1].split('class="matches-head-actions"', 1)[0]
                self.assertIn('class="predictions-sidebar-top-toggle"', utility)
                self.assertIn('data-prediction-filter-url=', utility)
                self.assertEqual(response.context["top_experts_only"], top_only)
                self.assertEqual(' checked' in utility, top_only)

    def test_rich_article_has_cover_panel_and_independent_responsive_readers(self):
        self.coupon.headline = "Авторский заголовок текстового прогноза"
        self.coupon.description = ("Первый абзац подробного разбора. " * 25) + "\n\nВторой абзац <script>alert(1)</script>"
        self.coupon.single_purchase_price = Decimal("129")
        self.coupon.save(update_fields=["headline", "description", "single_purchase_price"])
        self.client.force_login(self.author)
        response = self.client.get(reverse("front:prediction_detail", args=[self.coupon.pk]))
        self.assertEqual(response.status_code, 200)
        article = response.context["prediction_article"]
        self.assertTrue(article["is_rich"])
        self.assertEqual(article["size"], "long")
        self.assertEqual(article["character_count"], len(self.coupon.description.strip()))
        self.assertGreaterEqual(article["reading_minutes"], 1)
        html = response.content.decode()
        self.assertEqual(html.count('data-prediction-article>'), 2)
        for variant in ("mobile", "desktop"):
            self.assertEqual(html.count(f'id="coupon-article-full-{self.coupon.pk}-{variant}"'), 1)
            self.assertIn(f'aria-controls="coupon-article-full-{self.coupon.pk}-{variant}"', html)
        self.assertIn("Платный · 129 ₽", html)
        self.assertIn('class="coupon-prediction-article-stats"', html)
        self.assertIn("Читать полностью", html)
        self.assertIn("Разбор от автора", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_short_rich_article_uses_custom_cover_and_real_metrics(self):
        self.coupon.audience = "free"
        self.coupon.description = "Короткий разбор автора."
        self.coupon.custom_cover_image = "coupon-covers/article-cover.jpg"
        self.coupon.save(update_fields=["audience", "description", "custom_cover_image"])
        response = self.client.get(reverse("front:prediction_detail", args=[self.coupon.pk]))
        self.assertEqual(response.context["prediction_article"]["size"], "short")
        self.assertContains(response, 'class="coupon-detail-page is-rich"')
        self.assertContains(response, "coupon-covers/article-cover.jpg")
        self.assertContains(response, "Бесплатный")
        self.assertContains(response, "1,95")
        self.assertContains(response, 'class="coupon-prediction-article-stat is-confidence"')

    def test_quick_coupon_description_keeps_existing_article_layout(self):
        self.coupon.prediction_format = "quick"
        self.coupon.audience = "free"
        self.coupon.save(update_fields=["prediction_format", "audience"])
        response = self.client.get(reverse("front:prediction_detail", args=[self.coupon.pk]))
        self.assertFalse(response.context["prediction_article"]["is_rich"])
        self.assertNotContains(response, 'class="coupon-detail-page is-rich"')
        self.assertContains(response, 'class="coupon-prediction-article"')
        self.assertContains(response, self.coupon.description)
        self.assertNotContains(response, "data-prediction-article")
        self.assertNotContains(response, "coupon-prediction-article-hero")

    def test_coupon_back_links_follow_local_source_with_safe_direct_entry_fallback(self):
        self.client.force_login(self.author)
        detail_url = reverse("front:prediction_detail", args=[self.coupon.pk])
        fallback = reverse("front:predictions")
        for referrer, expected_url, expected_label in [
            ("http://testserver/experts/paid-author/?tab=predictions&status=win", "http://testserver/experts/paid-author/?tab=predictions&status=win", "Назад"),
            ("http://testserver/feed/?view_mode=table", "http://testserver/feed/?view_mode=table", "Назад"),
            ("", fallback, "К прогнозам"),
            (f"http://testserver{detail_url}?copy=1", fallback, "К прогнозам"),
            ("https://outside.example/feed/", fallback, "К прогнозам"),
            ("javascript:alert(1)", fallback, "К прогнозам"),
            ("http://[", fallback, "К прогнозам"),
        ]:
            with self.subTest(referrer=referrer):
                response = self.client.get(detail_url, HTTP_REFERER=referrer)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["coupon_back_url"], expected_url)
                self.assertEqual(response.context["coupon_back_label"], expected_label)
                self.assertContains(response, 'data-coupon-back', count=2)
                self.assertNotContains(response, "Вернуться в ленту")

    def test_cookie_banner_is_rendered_only_for_guests(self):
        url = reverse("front:predictions")
        guest = self.client.get(url)
        self.assertContains(guest, 'data-cookie-banner')
        self.assertContains(guest, 'data-cookie-preferences')
        self.assertContains(guest, "Принять все")
        self.assertContains(guest, "Только обязательные")
        self.client.force_login(self.author)
        signed_in = self.client.get(url)
        self.assertNotContains(signed_in, 'data-cookie-banner')
        self.assertNotContains(signed_in, 'data-cookie-preferences')

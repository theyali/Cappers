from datetime import timedelta
from decimal import Decimal

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
        self.assertContains(response, 'class="prediction-card prediction-card-rich paid-prediction-locked-card"')
        self.assertContains(response, "front/img/real_coin.png")
        self.assertContains(response, "Платный автор")
        self.assertContains(response, "Выбрать подписку")
        self.assertNotContains(response, 'aria-label="Статус прогнозов"')
        self.assertNotContains(response, "Секретный исход П1")
        self.assertNotContains(response, "Секретный разбор платного прогноза")
        self.assertNotContains(response, "Команда А")
        self.assertNotContains(response, "Команда Б")
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
        self.assertNotContains(response, "paid-prediction-locked-card")
        self.assertContains(response, "Секретный разбор платного прогноза")

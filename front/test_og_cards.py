from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from cabinet.models import AnalystProfile, User
from front.og_cards.data import coupon_card_data, profile_card_data
from game.models import Match, Prediction, PredictionCoupon, Sport

TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES, SITE_BASE_URL="https://www.capper-hub.com")
class OgCardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.author = User.objects.create_user(username="og-author", password="secret", role=User.Role.ANALYST)
        self.profile, _ = AnalystProfile.objects.get_or_create(user=self.author)
        self.profile.display_name = "Вадим Крылов"
        self.profile.is_verified = True
        self.profile.trust_index = Decimal("8.2")
        self.profile.save()
        sport, _ = Sport.objects.get_or_create(code="football", defaults={"name": "Football", "name_ru": "Футбол"})
        self.match = Match.objects.create(
            external_id=771001,
            sport=sport,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={
                "league": {"name": {"ru": "Ла Лига"}},
                "teams": {"home": {"name": {"ru": "Барселона"}}, "away": {"name": {"ru": "Жирона"}}},
            },
        )

    def _coupon(self, *, audience=PredictionCoupon.Audience.FREE, state=PredictionCoupon.StateStatus.PENDING,
                published=True):
        coupon = PredictionCoupon.objects.create(
            author=self.author,
            published_status=(
                PredictionCoupon.PublishedStatus.PUBLISHED if published else PredictionCoupon.PublishedStatus.DRAFT
            ),
            state_status=state,
            audience=audience,
            total_stake=Decimal("500"),
            possible_payout=Decimal("975"),
            settled_at=None if state == PredictionCoupon.StateStatus.PENDING else timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon, match=self.match, market="winner", selection="Барселона", outcome_code="1",
            coefficient=Decimal("1.95"), stake=Decimal("500"),
        )
        return coupon

    def _card_data(self, coupon):
        coupon = PredictionCoupon.objects.select_related("author__analyst_profile").get(pk=coupon.pk)
        return coupon_card_data(coupon, list(coupon.predictions.select_related("match")))

    def assert_card_png(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(Image.open(BytesIO(response.content)).size, (1200, 630))

    def test_free_coupon_card_and_page_meta(self):
        coupon = self._coupon()

        data = self._card_data(coupon)
        self.assertEqual(data["events"][0]["title"], "Барселона — Жирона")
        self.assertEqual(data["events"][0]["pick"], "П1")
        self.assertEqual(data["coefficient"], "1.95")
        self.assertEqual(data["sport"], "f")
        self.assertEqual(data["host"], "capper-hub.com")
        self.assert_card_png(self.client.get(reverse("front:og_coupon", args=[coupon.pk])))

        page = self.client.get(reverse("front:prediction_detail", kwargs={"prediction_id": coupon.pk}))
        self.assertContains(page, f'<meta property="og:image" content="http://testserver/og/coupon/{coupon.pk}.png?v=')
        self.assertContains(page, '<meta property="og:image:width" content="1200">')
        self.assertContains(page, f'<meta name="twitter:image" content="http://testserver/og/coupon/{coupon.pk}.png?v=')

    def test_paid_coupon_card_hides_pick_odds_and_money(self):
        self.profile.paid_predictions_enabled = True
        self.profile.paid_predictions_price = Decimal("990")
        self.profile.save()
        coupon = self._coupon(audience=PredictionCoupon.Audience.PAID)

        data = self._card_data(coupon)
        self.assertTrue(data["locked"])
        # Teams are public in the feed; the pick and anything that gives the odds away are not.
        self.assertEqual(data["events"][0]["title"], "Барселона — Жирона")
        self.assertEqual((data["events"][0]["pick"], data["events"][0]["coefficient"]), ("", ""))
        self.assertEqual((data["coefficient"], data["stake"], data["result_amount"]), ("", "", ""))
        self.assertEqual(data["price"], "от 990 ₽/мес")
        self.assert_card_png(self.client.get(reverse("front:og_coupon", args=[coupon.pk])))
        page = self.client.get(reverse("front:prediction_detail", kwargs={"prediction_id": coupon.pk}))
        self.assertTemplateUsed(page, "front/paid_prediction_paywall.html")
        self.assertContains(page, f"/og/coupon/{coupon.pk}.png?v=")

        coupon.state_status = PredictionCoupon.StateStatus.WIN
        coupon.save()
        data = self._card_data(coupon)
        self.assertEqual((data["coefficient"], data["stake"], data["result_amount"]), ("", "", ""))
        self.assertEqual(data["events"][0]["pick"], "")
        self.assert_card_png(self.client.get(reverse("front:og_coupon", args=[coupon.pk])))

    def test_card_is_drawn_once_per_version(self):
        coupon = self._coupon()
        url = reverse("front:og_coupon", args=[coupon.pk])
        with patch("front.og_cards.views.coupon_card", return_value=b"png") as draw:
            self.client.get(url)
            self.client.get(f"{url}?v=other")
            self.assertEqual(draw.call_count, 1)
            coupon.state_status = PredictionCoupon.StateStatus.WIN
            coupon.save()
            self.client.get(url)
        self.assertEqual(draw.call_count, 2)
        self.assertEqual(draw.call_args.args[0]["state"], PredictionCoupon.StateStatus.WIN)

    def test_no_card_for_draft_coupon_or_private_capper(self):
        draft = self._coupon(published=False)
        self.assertEqual(self.client.get(reverse("front:og_coupon", args=[draft.pk])).status_code, 404)
        self.profile.is_public = False
        self.profile.save()
        self.assertEqual(self.client.get(reverse("front:og_capper", args=[self.author.username])).status_code, 404)

    def test_capper_card_is_newbie_until_ten_settled_coupons(self):
        for _ in range(3):
            self._coupon(state=PredictionCoupon.StateStatus.WIN)
        data = profile_card_data(self.profile)
        self.assertTrue(data["newbie"])
        self.assertEqual(data["predictions_label"], "3 прогноза")
        self.assertEqual(data["sport_names"], ["Футбол"])

        for state in [PredictionCoupon.StateStatus.WIN] * 5 + [PredictionCoupon.StateStatus.LOSE] * 2:
            self._coupon(state=state)
        data = profile_card_data(self.profile)
        self.assertNotIn("newbie", data)
        self.assertEqual(data["roi_label"], "ROI ЗА 3 МЕСЯЦА")
        self.assertEqual(data["hit_rate"], "80%")
        self.assertEqual(data["predictions"], "10")
        self.assertEqual(len(data["recent"]), 10)
        self.assertEqual(data["author"]["trust"], "8.2")
        self.assert_card_png(self.client.get(reverse("front:og_capper", args=[self.author.username])))

        page = self.client.get(reverse("front:expert_profile", kwargs={"username": self.author.username}))
        self.assertContains(page, f'<meta property="og:image" content="http://testserver/og/capper/{self.author.username}.png?v=')

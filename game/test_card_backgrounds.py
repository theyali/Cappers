from collections import Counter
from decimal import Decimal
from itertools import count
from urllib.parse import unquote

from django.test import TestCase, override_settings

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon, Sport
from front.home_views import _latest_home_predictions
from game.services.card_backgrounds import EXPRESS_DIR, assign_backgrounds, backgrounds

EXTERNAL_IDS = count(992001)


class CardBackgroundTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="background-capper", password="x", role=User.Role.ANALYST)

    def coupon(self, *sport_codes, background=""):
        coupon = PredictionCoupon.objects.create(
            author=self.author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100"),
            mobile_card_background=background,
        )
        for code in sport_codes:
            sport, _ = Sport.objects.get_or_create(code=code, defaults={"name": code})
            match = Match.objects.create(external_id=next(EXTERNAL_IDS), sport=sport, sync_scope=Match.SyncScope.PREMATCH)
            Prediction.objects.create(
                coupon=coupon, match=match, market="winner", selection="П1", coefficient=Decimal("2"), stake=Decimal("100")
            )
        return coupon, list(coupon.predictions.select_related("match__sport"))

    def test_singles_go_through_every_picture_of_their_sport(self):
        coupons = [self.coupon("tennis") for _ in range(8)]

        assign_backgrounds(coupons)

        used = Counter(PredictionCoupon.objects.values_list("mobile_card_background", flat=True))
        self.assertEqual(set(used), set(backgrounds()["tennis"]))
        self.assertEqual(set(used.values()), {2})

    def test_express_and_sports_without_pictures_get_the_mixed_ones(self):
        express = self.coupon("football", "tennis")
        darts = self.coupon("darts")

        assign_backgrounds([express, darts])

        for coupon, _ in (express, darts):
            coupon.refresh_from_db()
            self.assertTrue(coupon.mobile_card_background.startswith(EXPRESS_DIR))

    def test_a_kept_background_stays_and_a_missing_file_is_replaced(self):
        kept_path = backgrounds()["football"][2]
        kept = self.coupon("football", background=kept_path)
        stale = self.coupon("football", background="front/img/removed@2x.png")

        assign_backgrounds([kept, stale])

        kept[0].refresh_from_db()
        stale[0].refresh_from_db()
        self.assertEqual(kept[0].mobile_card_background, kept_path)
        self.assertIn(stale[0].mobile_card_background, backgrounds()["football"])

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_home_slider_cards_get_a_saved_background(self):
        coupon, _ = self.coupon("ice-hockey")
        PredictionCoupon.objects.filter(pk=coupon.pk).update(audience=PredictionCoupon.Audience.FREE)

        card = _latest_home_predictions()[0]

        coupon.refresh_from_db()
        self.assertIn(coupon.mobile_card_background, backgrounds()["hockey"])
        self.assertTrue(unquote(card["mobile_background"]["url"]).endswith(coupon.mobile_card_background))
        self.assertIn("png@3x", unquote(card["mobile_background"]["url_3x"]))

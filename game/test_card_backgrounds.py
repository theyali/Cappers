from collections import Counter
from decimal import Decimal
from itertools import count
from urllib.parse import unquote

from django.test import TestCase, override_settings
from django.urls import reverse

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon, Sport
from front.home_views import _latest_home_predictions
from game.services.bet_options import pick_label, picked_side
from game.services.card_backgrounds import EXPRESS_DIR, assign_backgrounds, assign_coupon_backgrounds, backgrounds

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

    def test_published_coupon_gives_each_event_a_picture_of_its_sport(self):
        coupon, _ = self.coupon("football", "tennis", "darts")

        assign_coupon_backgrounds(coupon)

        coupon.refresh_from_db()
        self.assertTrue(coupon.mobile_card_background.startswith(EXPRESS_DIR))
        events = {
            event.match.sport.code: event.mobile_card_background
            for event in coupon.predictions.select_related("match__sport")
        }
        self.assertIn(events["football"], backgrounds()["football"])
        self.assertIn(events["tennis"], backgrounds()["tennis"])
        self.assertTrue(events["darts"].startswith(EXPRESS_DIR))


    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_coupon_page_shows_old_events_with_their_pictures(self):
        coupon, events = self.coupon("tennis")
        PredictionCoupon.objects.filter(pk=coupon.pk).update(audience=PredictionCoupon.Audience.FREE)

        response = self.client.get(reverse("front:prediction_detail", args=[coupon.pk]))

        events[0].refresh_from_db()
        self.assertIn(events[0].mobile_card_background, backgrounds()["tennis"])
        self.assertContains(response, "coupon-mobile-event")
        self.assertContains(response, "Победитель: П1")
        self.assertContains(response, "coupon-detail-body")


class PickLabelTests(TestCase):
    def event(self, market, selection, outcome_code=""):
        match = Match(external_id=1, raw_data={"teams": {"home": {"name": {"ru": "Хансен"}}, "away": {"name": {"ru": "Поповик"}}}})
        return Prediction(match=match, market=market, selection=selection, outcome_code=outcome_code)

    def test_winner_shows_the_side_and_highlights_the_team(self):
        by_code = self.event("winner", "Поповик", "2")
        legacy = self.event("winner", "Хансен")

        self.assertEqual(pick_label(by_code), "Победитель: П2")
        self.assertEqual(picked_side(by_code), "away")
        self.assertEqual(pick_label(legacy), "Победитель: П1")
        self.assertEqual(picked_side(legacy), "home")

    def test_other_markets_keep_their_text(self):
        self.assertEqual(pick_label(self.event("total", "ТБ 2.5", "over 2.5")), "Тотал: ТБ 2.5")
        self.assertEqual(picked_side(self.event("total", "ТБ 2.5", "over 2.5")), "")
        self.assertEqual(pick_label(self.event("both_score", "Обе забьют: да", "yes")), "Обе забьют: да")
        self.assertEqual(picked_side(self.event("handicap", "Ф2 (+1.5)", "away +1.5")), "away")

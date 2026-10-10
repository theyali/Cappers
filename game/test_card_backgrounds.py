from decimal import Decimal
from itertools import count

from django.test import TestCase, override_settings
from django.urls import reverse

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon, PredictionCoverImage, Sport
from game.services.bet_options import pick_label, picked_side

EXTERNAL_IDS = count(992001)


class MobileEventCoverTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="cover-capper", password="x", role=User.Role.ANALYST)

    def coupon(self, *sport_codes):
        coupon = PredictionCoupon.objects.create(
            author=self.author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100"),
            possible_payout=Decimal("200"),
            audience=PredictionCoupon.Audience.FREE,
        )
        for code in sport_codes:
            sport, _ = Sport.objects.get_or_create(code=code, defaults={"name": code})
            PredictionCoverImage.objects.get_or_create(
                cover_type=PredictionCoverImage.CoverType.SPORT,
                placement=PredictionCoverImage.Placement.GRID,
                sport=sport,
                defaults={"image": f"prediction_covers/{code}.webp"},
            )
            match = Match.objects.create(external_id=next(EXTERNAL_IDS), sport=sport, sync_scope=Match.SyncScope.PREMATCH)
            Prediction.objects.create(
                coupon=coupon, match=match, market="winner", selection="П1", coefficient=Decimal("2"), stake=Decimal("100")
            )
        return coupon, list(coupon.predictions.select_related("match__sport"))

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_coupon_page_shows_event_covers_from_prediction_cover_images(self):
        coupon, _ = self.coupon("tennis")

        response = self.client.get(reverse("front:prediction_detail", args=[coupon.pk]))

        self.assertContains(response, "coupon-mobile-event")
        self.assertContains(response, "prediction_covers/tennis.webp")
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

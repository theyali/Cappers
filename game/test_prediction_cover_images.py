from decimal import Decimal

from django.test import TestCase

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon, PredictionCoverImage, Sport


class PredictionCoverImageAssignmentTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="analyst",
            password="pass",
            role=User.Role.ANALYST,
        )
        self.football = Sport.objects.create(code="football", name="Football", name_ru="Футбол")
        self.tennis = Sport.objects.create(code="tennis", name="Tennis", name_ru="Теннис")
        self.football_match = Match.objects.create(
            sport=self.football,
            external_id=101,
            sync_scope=Match.SyncScope.PREMATCH,
        )
        self.tennis_match = Match.objects.create(
            sport=self.tennis,
            external_id=102,
            sync_scope=Match.SyncScope.PREMATCH,
        )

    def _coupon(self, *, coupon_type=PredictionCoupon.CouponType.SINGLE, cover_image=None):
        return PredictionCoupon.objects.create(
            author=self.author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            coupon_type=coupon_type,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=60,
            cover_image=cover_image,
        )

    def test_single_coupon_uses_sport_cover(self):
        football_cover = PredictionCoverImage.objects.create(
            cover_type=PredictionCoverImage.CoverType.SPORT,
            sport=self.football,
            image="prediction_covers/football.webp",
        )
        PredictionCoverImage.objects.create(
            cover_type=PredictionCoverImage.CoverType.SPORT,
            sport=self.tennis,
            image="prediction_covers/tennis.webp",
        )
        coupon = self._coupon()
        Prediction.objects.create(
            coupon=coupon,
            match=self.football_match,
            market="П1",
            selection="П1",
            coefficient=Decimal("2.00"),
            stake=Decimal("100.00"),
        )

        coupon.refresh_from_db()
        self.assertEqual(coupon.cover_image, football_cover)

    def test_express_coupon_uses_express_cover(self):
        express_cover = PredictionCoverImage.objects.create(
            cover_type=PredictionCoverImage.CoverType.EXPRESS,
            image="prediction_covers/express.webp",
        )
        PredictionCoverImage.objects.create(
            cover_type=PredictionCoverImage.CoverType.SPORT,
            sport=self.football,
            image="prediction_covers/football.webp",
        )
        coupon = self._coupon(coupon_type=PredictionCoupon.CouponType.EXPRESS)
        Prediction.objects.create(
            coupon=coupon,
            match=self.football_match,
            market="П1",
            selection="П1",
            coefficient=Decimal("2.00"),
            stake=Decimal("100.00"),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self.tennis_match,
            market="П2",
            selection="П2",
            coefficient=Decimal("1.80"),
            stake=Decimal("100.00"),
        )

        coupon.refresh_from_db()
        self.assertEqual(coupon.cover_image, express_cover)

    def test_existing_cover_is_not_overwritten(self):
        manual_cover = PredictionCoverImage.objects.create(
            cover_type=PredictionCoverImage.CoverType.SPORT,
            sport=self.football,
            image="prediction_covers/manual.webp",
        )
        PredictionCoverImage.objects.create(
            cover_type=PredictionCoverImage.CoverType.SPORT,
            sport=self.football,
            image="prediction_covers/auto.webp",
        )
        coupon = self._coupon(cover_image=manual_cover)
        Prediction.objects.create(
            coupon=coupon,
            match=self.football_match,
            market="П1",
            selection="П1",
            coefficient=Decimal("2.00"),
            stake=Decimal("100.00"),
        )

        coupon.refresh_from_db()
        self.assertEqual(coupon.cover_image, manual_cover)

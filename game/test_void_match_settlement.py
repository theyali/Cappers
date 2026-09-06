from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon
from game.services.settlement import settle_finished_matches


class VoidMatchSettlementTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="void-settlement-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )

    def test_postponed_match_refunds_position_and_removes_odd_from_coupon_payout(self):
        won_match = Match.objects.create(
            external_id=810001,
            sync_scope=Match.SyncScope.FINISHED,
            score="2:0",
        )
        postponed_match = Match.objects.create(
            external_id=810002,
            sync_scope=Match.SyncScope.POSTPONED,
            time_status="4",
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("570.00"),
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=won_match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("1.90"),
            stake=Decimal("100.00"),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=postponed_match,
            market="winner",
            selection="Гости",
            coefficient=Decimal("3.00"),
            stake=Decimal("100.00"),
        )

        result = settle_finished_matches()

        coupon.refresh_from_db()
        states = list(coupon.predictions.order_by("id").values_list("state_status", flat=True))
        self.assertEqual(result["void_matches"], 1)
        self.assertEqual(states, [Prediction.StateStatus.WIN, Prediction.StateStatus.REFUND])
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.WIN)
        self.assertEqual(coupon.possible_payout, Decimal("190.00"))

    def test_fully_void_coupon_becomes_refund(self):
        canceled_match = Match.objects.create(
            external_id=810003,
            sync_scope=Match.SyncScope.CANCELED,
            time_status="5",
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("220.00"),
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=canceled_match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.20"),
            stake=Decimal("100.00"),
        )

        settle_finished_matches()

        coupon.refresh_from_db()
        self.assertEqual(coupon.predictions.get().state_status, Prediction.StateStatus.REFUND)
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.REFUND)
        self.assertEqual(coupon.possible_payout, Decimal("100.00"))

    def test_losing_coupon_keeps_possible_payout_after_recalculation(self):
        lost_match = Match.objects.create(
            external_id=810004,
            sync_scope=Match.SyncScope.FINISHED,
            score="0:2",
        )
        won_match = Match.objects.create(
            external_id=810005,
            sync_scope=Match.SyncScope.FINISHED,
            score="1:0",
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("200.00"),
            possible_payout=Decimal("648.00"),
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=lost_match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("1.80"),
            stake=Decimal("200.00"),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=won_match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("1.80"),
            stake=Decimal("200.00"),
        )

        settle_finished_matches()

        coupon.refresh_from_db()
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.LOSE)
        self.assertEqual(coupon.possible_payout, Decimal("648.00"))

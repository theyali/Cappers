from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from cabinet.models import User
from game.models import Match, MatchManualReview, Prediction, PredictionCoupon
from game.services.settlement import settle_finished_matches


class ManualMatchReviewSettlementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="settlement-review-analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )

    def create_prediction(
        self,
        *,
        external_id: int,
        score: str,
        market: str = "winner",
        selection: str = "Хозяева",
    ):
        match = Match.objects.create(
            external_id=external_id,
            sync_scope=Match.SyncScope.FINISHED,
            starts_at=timezone.now(),
            score=score,
        )
        coupon = PredictionCoupon.objects.create(
            author=self.user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake="100.00",
            possible_payout="200.00",
        )
        prediction = Prediction.objects.create(
            coupon=coupon,
            match=match,
            market=market,
            selection=selection,
            coefficient="2.00",
            stake="100.00",
        )
        return match, coupon, prediction

    def settle(self):
        with (
            patch(
                "game.services.settlement.settle_orphaned_copied_bets",
                return_value=0,
            ),
            patch("game.services.settlement.settle_prediction_coupon"),
        ):
            return settle_finished_matches()

    def test_finished_match_without_predictions_still_opens_score_review(self):
        match = Match.objects.create(
            external_id=990000,
            sync_scope=Match.SyncScope.FINISHED,
            starts_at=timezone.now(),
            score="",
        )

        self.settle()

        self.assertTrue(
            MatchManualReview.objects.filter(
                match=match,
                reason=MatchManualReview.Reason.MISSING_SCORE,
                status=MatchManualReview.Status.OPEN,
            ).exists()
        )

    def test_finished_match_without_score_stays_pending_and_opens_review(self):
        match, coupon, prediction = self.create_prediction(
            external_id=990001,
            score="",
        )

        self.settle()

        prediction.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(prediction.state_status, "")
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.PENDING)
        self.assertTrue(
            MatchManualReview.objects.filter(
                match=match,
                reason=MatchManualReview.Reason.MISSING_SCORE,
                status=MatchManualReview.Status.OPEN,
            ).exists()
        )

    def test_repeated_missing_score_settlement_keeps_single_open_review(self):
        match, _, _ = self.create_prediction(
            external_id=990007,
            score="",
        )

        self.settle()
        self.settle()

        self.assertEqual(
            MatchManualReview.objects.filter(
                match=match,
                reason=MatchManualReview.Reason.MISSING_SCORE,
                status=MatchManualReview.Status.OPEN,
            ).count(),
            1,
        )

    def test_finished_match_with_invalid_score_stays_pending_and_opens_review(self):
        match, coupon, prediction = self.create_prediction(
            external_id=990002,
            score="finished",
        )

        self.settle()

        prediction.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(prediction.state_status, "")
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.PENDING)
        self.assertTrue(
            MatchManualReview.objects.filter(
                match=match,
                reason=MatchManualReview.Reason.INVALID_SCORE,
                status=MatchManualReview.Status.OPEN,
            ).exists()
        )

    def test_unknown_market_stays_pending_instead_of_becoming_loss(self):
        match, coupon, prediction = self.create_prediction(
            external_id=990003,
            score="2-1",
            market="unsupported_market",
            selection="Unsupported selection",
        )

        self.settle()

        prediction.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(prediction.state_status, "")
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.PENDING)
        review = MatchManualReview.objects.get(
            match=match,
            reason=MatchManualReview.Reason.UNKNOWN_MARKET,
            status=MatchManualReview.Status.OPEN,
        )
        self.assertEqual(review.details["prediction_id"], prediction.id)

    def test_unrecognized_selection_in_supported_market_stays_pending(self):
        match, coupon, prediction = self.create_prediction(
            external_id=990005,
            score="2-1",
            market="winner",
            selection="Unsupported selection",
        )

        self.settle()

        prediction.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(prediction.state_status, "")
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.PENDING)
        self.assertTrue(
            MatchManualReview.objects.filter(
                match=match,
                reason=MatchManualReview.Reason.UNKNOWN_MARKET,
                status=MatchManualReview.Status.OPEN,
            ).exists()
        )

    def test_score_review_is_resolved_after_score_becomes_valid(self):
        match, coupon, prediction = self.create_prediction(
            external_id=990006,
            score="",
        )
        self.settle()
        match.score = "2-1"
        match.save(update_fields=["score", "updated_at"])

        self.settle()

        prediction.refresh_from_db()
        coupon.refresh_from_db()
        review = MatchManualReview.objects.get(
            match=match,
            reason=MatchManualReview.Reason.MISSING_SCORE,
        )
        self.assertEqual(prediction.state_status, Prediction.StateStatus.WIN)
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.WIN)
        self.assertEqual(review.status, MatchManualReview.Status.RESOLVED)
        self.assertIsNotNone(review.resolved_at)

    def test_supported_losing_market_is_still_settled_as_loss(self):
        _, coupon, prediction = self.create_prediction(
            external_id=990008,
            score="0-1",
        )

        self.settle()

        prediction.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(prediction.state_status, Prediction.StateStatus.LOSE)
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.LOSE)

    def test_supported_market_is_still_settled_normally(self):
        match, coupon, prediction = self.create_prediction(
            external_id=990004,
            score="2-1",
        )

        self.settle()

        prediction.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(prediction.state_status, Prediction.StateStatus.WIN)
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.WIN)
        self.assertFalse(
            MatchManualReview.objects.filter(
                match=match,
                status=MatchManualReview.Status.OPEN,
            ).exists()
        )

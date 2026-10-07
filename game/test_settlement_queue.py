from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from cabinet.models import User
from game.models import Match, MatchManualReview, Prediction, PredictionCoupon
from game.services.settlement import settle_finished_matches


class SettlementQueueTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="queue-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.next_external_id = 779000

    def _match(self, hours_ago, *, score="2-1", sync_scope=Match.SyncScope.FINISHED):
        self.next_external_id += 1
        return Match.objects.create(
            external_id=self.next_external_id,
            sync_scope=sync_scope,
            starts_at=timezone.now() - timedelta(hours=hours_ago),
            score=score,
        )

    def _prediction(self, match):
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100"),
            possible_payout=Decimal("200"),
            confidence=70,
            published_at=match.starts_at - timedelta(hours=1),
        )
        return Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="Хозяева",
            outcome_code="1",
            coefficient=Decimal("2.00"),
            stake=Decimal("100"),
        )

    def _state(self, prediction):
        prediction.refresh_from_db()
        return prediction.state_status

    def test_old_unsettled_match_is_not_pushed_out_by_newer_matches(self):
        old_prediction = self._prediction(self._match(hours_ago=48))
        for hours_ago in (1, 2, 3):
            self._match(hours_ago=hours_ago)

        settle_finished_matches(limit=2)

        self.assertEqual(self._state(old_prediction), Prediction.StateStatus.WIN)

    def test_matches_on_manual_review_do_not_block_fresh_ones(self):
        stuck = self._match(hours_ago=48, score="")
        stuck_prediction = self._prediction(stuck)
        MatchManualReview.objects.create(match=stuck, reason=MatchManualReview.Reason.MISSING_SCORE)
        fresh_prediction = self._prediction(self._match(hours_ago=3))

        settle_finished_matches(limit=1)

        self.assertEqual(self._state(fresh_prediction), Prediction.StateStatus.WIN)
        self.assertEqual(self._state(stuck_prediction), "")

    def test_old_void_match_is_refunded(self):
        void_prediction = self._prediction(self._match(hours_ago=72, score="", sync_scope=Match.SyncScope.CANCELED))
        for hours_ago in (1, 2):
            self._match(hours_ago=hours_ago, score="", sync_scope=Match.SyncScope.CANCELED)

        settle_finished_matches(limit=1)

        self.assertEqual(self._state(void_prediction), Prediction.StateStatus.REFUND)

    def test_score_review_of_match_without_predictions_is_resolved_when_score_arrives(self):
        match = self._match(hours_ago=5, score="")
        settle_finished_matches()
        review = MatchManualReview.objects.get(match=match, reason=MatchManualReview.Reason.MISSING_SCORE)

        Match.objects.filter(pk=match.pk).update(score="1-0")
        settle_finished_matches()

        review.refresh_from_db()
        self.assertEqual(review.status, MatchManualReview.Status.RESOLVED)

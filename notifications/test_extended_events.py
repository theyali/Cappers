from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from cabinet.models import (
    AnalystFollow,
    AnalystPaidSubscription,
    MatchPredictionRequest,
    User,
)
from front.models import PredictionFavorite, PredictionLike
from game.models import Match, Prediction, PredictionCoupon
from tournaments.models import Tournament, TournamentParticipant
from wallets.models import CopyBettingSubscription

from .extra_tasks import dispatch_extended_notification_events
from .models import MatchWatch, Notification
from .services import get_preferences


class NotificationPreferenceDefaultsTests(TestCase):
    def test_only_primary_notification_types_are_enabled_by_default(self):
        user = User.objects.create_user(username="notification-defaults")
        preferences = get_preferences(user)

        enabled = (
            "prediction_like",
            "prediction_favorite",
            "copybetting",
            "new_follower",
            "paid_subscription",
            "new_prediction",
            "requested_match_prediction",
            "match_prediction",
            "tournament_started",
            "tournament_finished",
            "own_coupon_settled",
        )
        disabled = ("favorite_settled", "match_reminder", "achievement")

        for field in enabled:
            self.assertTrue(getattr(preferences, field), field)
        for field in disabled:
            self.assertFalse(getattr(preferences, field), field)


class NotificationSignalTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="signal-analyst",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(username="signal-reader")
        self.coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            published_at=timezone.now(),
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("180.00"),
        )

    def test_like_favorite_follow_paid_subscription_and_copybetting_create_notifications(self):
        PredictionLike.objects.create(prediction=self.coupon, user=self.reader)
        PredictionFavorite.objects.create(prediction=self.coupon, user=self.reader)
        AnalystFollow.objects.create(follower=self.reader, analyst=self.analyst)
        AnalystPaidSubscription.objects.create(
            subscriber=self.reader,
            analyst=self.analyst,
            price=Decimal("150.00"),
            duration_days=30,
            expires_at=timezone.now() + timedelta(days=30),
        )
        CopyBettingSubscription.objects.create(
            user=self.reader,
            analyst=self.analyst,
            bank_amount=Decimal("10000.00"),
            stake_percent=Decimal("2.00"),
        )

        kinds = set(
            Notification.objects.filter(recipient=self.analyst).values_list("kind", flat=True)
        )
        self.assertTrue(
            {
                Notification.Kind.PREDICTION_LIKE,
                Notification.Kind.PREDICTION_FAVORITE,
                Notification.Kind.NEW_FOLLOWER,
                Notification.Kind.PAID_SUBSCRIPTION,
                Notification.Kind.COPYBETTING,
            }.issubset(kinds)
        )


class ExtendedNotificationTaskTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="task-analyst",
            role=User.Role.ANALYST,
        )
        self.requester = User.objects.create_user(username="task-requester")
        self.watcher = User.objects.create_user(username="task-watcher")
        self.match = Match.objects.create(
            external_id=880001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=3),
        )
        self.coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            published_at=timezone.now(),
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("190.00"),
        )
        Prediction.objects.create(
            coupon=self.coupon,
            match=self.match,
            market="winner",
            selection="home",
            coefficient=Decimal("1.90"),
            stake=Decimal("100.00"),
        )
        MatchPredictionRequest.objects.create(user=self.requester, match=self.match)
        MatchWatch.objects.create(user=self.watcher, match=self.match)

    def test_requested_and_watched_match_predictions_are_dispatched(self):
        dispatch_extended_notification_events.run()

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.requester,
                kind=Notification.Kind.REQUESTED_MATCH_PREDICTION,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.watcher,
                kind=Notification.Kind.MATCH_PREDICTION,
            ).exists()
        )

    def test_own_coupon_settlement_is_dispatched(self):
        self.coupon.state_status = PredictionCoupon.StateStatus.WIN
        self.coupon.settled_at = timezone.now()
        self.coupon.save(update_fields=["state_status", "settled_at", "updated_at"])

        dispatch_extended_notification_events.run()

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.analyst,
                kind=Notification.Kind.OWN_COUPON_SETTLED,
            ).exists()
        )

    def test_tournament_start_and_finish_are_dispatched(self):
        now = timezone.now()
        live = Tournament.objects.create(
            title="Live tournament",
            status=Tournament.Status.PUBLISHED,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=1),
        )
        finished = Tournament.objects.create(
            title="Finished tournament",
            status=Tournament.Status.PUBLISHED,
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(minutes=5),
        )
        TournamentParticipant.objects.create(tournament=live, user=self.analyst)
        TournamentParticipant.objects.create(tournament=finished, user=self.analyst)

        dispatch_extended_notification_events.run()

        kinds = set(
            Notification.objects.filter(recipient=self.analyst).values_list("kind", flat=True)
        )
        self.assertIn(Notification.Kind.TOURNAMENT_STARTED, kinds)
        self.assertIn(Notification.Kind.TOURNAMENT_FINISHED, kinds)

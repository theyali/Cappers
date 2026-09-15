from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from cabinet.comments.models import Comment
from front.metric_models import MatchMetrics, PredictionMetrics
from front.metrics import (
    decrement_prediction_comments,
    get_match_metrics,
    get_prediction_metrics,
    increment_match_views,
    increment_prediction_comments,
    increment_prediction_shares,
    increment_prediction_views,
    refresh_match_metrics,
    refresh_prediction_metrics,
    toggle_prediction_favorite_metric,
    toggle_prediction_like_metric,
)
from front.models import PredictionFavorite, PredictionLike
from game.models import Match, Prediction, PredictionCoupon
from notifications.models import MatchWatch


class PersistedMetricsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.analyst = user_model.objects.create_user(
            username="metrics-analyst",
            password="test-password",
            role=user_model.Role.ANALYST,
        )
        self.reader = user_model.objects.create_user(
            username="metrics-reader",
            password="test-password",
        )
        self.match = Match.objects.create(
            external_id=990001,
            sync_scope=Match.SyncScope.PREMATCH,
        )
        self.coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.FREE,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("180.00"),
            confidence=70,
        )
        self.position = Prediction.objects.create(
            coupon=self.coupon,
            match=self.match,
            market="winner",
            selection="home",
            coefficient=Decimal("1.80"),
            stake=Decimal("100.00"),
        )

    def test_metric_rows_exist_for_new_coupon_and_match(self):
        self.assertTrue(PredictionMetrics.objects.filter(coupon=self.coupon).exists())
        self.assertTrue(MatchMetrics.objects.filter(match=self.match).exists())

    def test_refresh_prediction_metrics_rebuilds_reactions_and_comments(self):
        PredictionLike.objects.create(prediction=self.coupon, user=self.reader)
        PredictionFavorite.objects.create(prediction=self.coupon, user=self.reader)
        content_type = ContentType.objects.get_for_model(
            PredictionCoupon,
            for_concrete_model=False,
        )
        Comment.objects.create(
            user=self.reader,
            content_type=content_type,
            object_id=self.coupon.pk,
            text="Полезный прогноз",
            status=Comment.Status.PUBLISHED,
        )
        increment_prediction_views(self.coupon.pk)
        increment_prediction_shares(self.coupon.pk)

        metrics = refresh_prediction_metrics(self.coupon.pk)

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.likes_count, 1)
        self.assertEqual(metrics.favorites_count, 1)
        self.assertEqual(metrics.comments_count, 1)
        self.assertEqual(metrics.views_count, 1)
        self.assertEqual(metrics.shares_count, 1)

    def test_direct_comment_changes_keep_prediction_metrics_synced(self):
        content_type = ContentType.objects.get_for_model(
            PredictionCoupon,
            for_concrete_model=False,
        )
        comment = Comment.objects.create(
            user=self.reader,
            content_type=content_type,
            object_id=self.coupon.pk,
            text="Слежу за прогнозом",
            status=Comment.Status.PUBLISHED,
        )
        self.assertEqual(get_prediction_metrics(self.coupon.pk).comments_count, 1)

        comment.status = Comment.Status.DELETED
        comment.save(update_fields=("status", "updated_at"))
        self.assertEqual(get_prediction_metrics(self.coupon.pk).comments_count, 0)

    def test_prediction_comment_increment_and_decrement_never_go_negative(self):
        metrics = increment_prediction_comments(self.coupon.pk)
        self.assertEqual(metrics.comments_count, 1)

        metrics = decrement_prediction_comments(self.coupon.pk)
        self.assertEqual(metrics.comments_count, 0)

        metrics = decrement_prediction_comments(self.coupon.pk)
        self.assertEqual(metrics.comments_count, 0)

    def test_prediction_reaction_toggles_update_stored_metrics(self):
        active, metrics = toggle_prediction_like_metric(self.coupon, self.reader)
        self.assertTrue(active)
        self.assertEqual(metrics.likes_count, 1)

        active, metrics = toggle_prediction_like_metric(self.coupon, self.reader)
        self.assertFalse(active)
        self.assertEqual(metrics.likes_count, 0)

        active, metrics = toggle_prediction_favorite_metric(self.coupon, self.reader)
        self.assertTrue(active)
        self.assertEqual(metrics.favorites_count, 1)

        active, metrics = toggle_prediction_favorite_metric(self.coupon, self.reader)
        self.assertFalse(active)
        self.assertEqual(metrics.favorites_count, 0)

    def test_refresh_match_metrics_counts_distinct_public_coupons_and_activity(self):
        second_coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.FREE,
            total_stake=Decimal("80.00"),
            possible_payout=Decimal("120.00"),
            confidence=65,
        )
        Prediction.objects.create(
            coupon=second_coupon,
            match=self.match,
            market="winner",
            selection="away",
            coefficient=Decimal("1.50"),
            stake=Decimal("80.00"),
        )
        MatchWatch.objects.create(user=self.reader, match=self.match)
        match_content_type = ContentType.objects.get_for_model(
            Match,
            for_concrete_model=False,
        )
        Comment.objects.create(
            user=self.reader,
            content_type=match_content_type,
            object_id=self.match.pk,
            text="Жду матч",
            status=Comment.Status.PUBLISHED,
        )

        metrics = refresh_match_metrics(self.match.pk)

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.predictions_count, 2)
        self.assertEqual(metrics.favorites_count, 1)
        self.assertEqual(metrics.comments_count, 1)
        self.assertEqual(metrics.activity_count, 4)

    def test_match_watch_signals_keep_favorite_and_activity_counts_synced(self):
        watch = MatchWatch.objects.create(user=self.reader, match=self.match)
        metrics = get_match_metrics(self.match.pk)
        self.assertEqual(metrics.favorites_count, 1)
        self.assertEqual(metrics.activity_count, metrics.predictions_count + 1)

        watch.delete()
        metrics = get_match_metrics(self.match.pk)
        self.assertEqual(metrics.favorites_count, 0)
        self.assertEqual(metrics.activity_count, metrics.predictions_count)

    def test_match_and_prediction_views_are_persisted(self):
        prediction_metrics = increment_prediction_views(self.coupon.pk)
        match_metrics = increment_match_views(self.match.pk)

        self.assertEqual(prediction_metrics.views_count, 1)
        self.assertEqual(match_metrics.views_count, 1)
        self.assertEqual(get_prediction_metrics(self.coupon.pk).views_count, 1)
        self.assertEqual(get_match_metrics(self.match.pk).views_count, 1)

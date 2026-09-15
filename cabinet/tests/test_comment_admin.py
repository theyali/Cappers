from decimal import Decimal

from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.utils import timezone

from cabinet.comments.admin import CommentAdmin, _set_comment_status
from cabinet.comments.data import ForbiddenLexicon, clear_profanity_cache, matches_profanity
from cabinet.comments.models import Comment
from cabinet.models import User
from front.metrics import get_prediction_metrics
from game.models import PredictionCoupon


class TestForbiddenSource:
    def load(self) -> ForbiddenLexicon:
        return ForbiddenLexicon(
            words=("тестзапрет",),
            patterns=(r"\bкодовоеслово\b",),
        )


class CommentAdminTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="admin-comment-author",
            password="password",
            role=User.Role.ANALYST,
        )
        self.user = User.objects.create_user(
            username="admin-comment-user",
            password="password",
        )
        self.prediction = PredictionCoupon.objects.create(
            author=self.author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.FREE,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=60,
            published_at=timezone.now(),
        )
        content_type = ContentType.objects.get_for_model(
            PredictionCoupon,
            for_concrete_model=False,
        )
        self.comment = Comment.objects.create(
            user=self.user,
            content_type=content_type,
            object_id=self.prediction.pk,
            text="Нормальный комментарий",
            status=Comment.Status.PUBLISHED,
        )

    def test_comment_admin_is_registered_with_moderation_tools(self):
        model_admin = admin.site._registry.get(Comment)

        self.assertIsInstance(model_admin, CommentAdmin)
        self.assertIn("status", model_admin.list_filter)
        self.assertIn("text", model_admin.search_fields)
        self.assertIn("user__username", model_admin.search_fields)
        self.assertIn("publish_comments", model_admin.actions)
        self.assertIn("reject_comments", model_admin.actions)
        self.assertIn("delete_comments", model_admin.actions)
        for field_name in (
            "user",
            "content_type",
            "object_id",
            "target_object_link",
            "parent",
            "created_at",
            "updated_at",
        ):
            self.assertIn(field_name, model_admin.readonly_fields)

    def test_admin_soft_delete_keeps_prediction_metrics_in_sync(self):
        metrics = get_prediction_metrics(self.prediction.pk)
        self.assertEqual(metrics.comments_count, 1)

        changed = _set_comment_status(
            Comment.objects.filter(pk=self.comment.pk),
            status=Comment.Status.DELETED,
            reason="deleted_by_moderator",
        )

        self.assertEqual(changed, 1)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.status, Comment.Status.DELETED)
        self.assertEqual(self.comment.moderation_reason, "deleted_by_moderator")

        metrics.refresh_from_db()
        self.assertEqual(metrics.comments_count, 0)

    def test_target_object_column_contains_target_reference(self):
        model_admin = admin.site._registry[Comment]

        rendered = str(model_admin.target_object_link(self.comment))

        self.assertIn("game.predictioncoupon", rendered)
        self.assertIn(str(self.prediction.pk), rendered)


class ForbiddenLexiconSourceTests(TestCase):
    @override_settings(
        COMMENT_FORBIDDEN_LEXICON_SOURCE=(
            "cabinet.tests.test_comment_admin.TestForbiddenSource"
        )
    )
    def test_moderation_source_can_be_replaced_without_changing_service(self):
        clear_profanity_cache()
        self.addCleanup(clear_profanity_cache)

        self.assertTrue(matches_profanity("Это тестзапрет"))
        self.assertTrue(matches_profanity("кодовоеслово"))
        self.assertFalse(matches_profanity("Обычный текст"))

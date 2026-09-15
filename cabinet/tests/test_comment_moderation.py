from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from cabinet.comments.models import Comment
from cabinet.comments.services import (
    COMMENT_MAX_LENGTH,
    ModerationCode,
    contains_forbidden_link,
    contains_profanity,
    normalize_comment_text,
    validate_comment_text,
)


class CommentModerationServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="moderation-user",
            password="test-password",
        )
        self.content_type = ContentType.objects.get_for_model(self.user)

    def test_normalize_comment_text_collapses_whitespace(self):
        self.assertEqual(
            normalize_comment_text("  Хороший \n\t прогноз   на матч  "),
            "Хороший прогноз на матч",
        )

    def test_empty_comment_is_rejected(self):
        result = validate_comment_text(" \n\t ")

        self.assertFalse(result.is_allowed)
        self.assertEqual(result.code, ModerationCode.EMPTY)

    def test_comment_length_is_limited_after_normalization(self):
        result = validate_comment_text("а" * (COMMENT_MAX_LENGTH + 1))

        self.assertFalse(result.is_allowed)
        self.assertEqual(result.code, ModerationCode.TOO_LONG)

    def test_html_is_rejected(self):
        result = validate_comment_text("<b>Текст</b>")

        self.assertFalse(result.is_allowed)
        self.assertEqual(result.code, ModerationCode.HTML)

    def test_forbidden_link_variants_are_detected(self):
        samples = (
            "http://example.com",
            "https://example.com/path",
            "www.example.com",
            "example.ru",
            "t.me/channel",
            "@channel_name",
            "mail@example.com",
            "почта@пример.рф",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(contains_forbidden_link(sample))
                result = validate_comment_text(f"Смотрите {sample}")
                self.assertFalse(result.is_allowed)
                self.assertEqual(result.code, ModerationCode.FORBIDDEN_LINK)

    def test_plain_text_with_dot_is_not_treated_as_link(self):
        self.assertFalse(contains_forbidden_link("Матч закончился 2.0, всё отлично."))

    def test_profanity_is_rejected(self):
        self.assertTrue(contains_profanity("Это полный пиздец"))

        result = validate_comment_text("Это полный пиздец")
        self.assertFalse(result.is_allowed)
        self.assertEqual(result.code, ModerationCode.PROFANITY)

    def test_clean_comment_is_allowed_and_returns_normalized_text(self):
        result = validate_comment_text("  Нравится   этот прогноз  ", user=self.user)

        self.assertTrue(result.is_allowed)
        self.assertEqual(result.normalized_text, "Нравится этот прогноз")
        self.assertEqual(result.code, "")
        self.assertEqual(result.reason, "")

    def test_fourth_identical_comment_in_24_hours_is_rejected(self):
        text = "Одинаковый комментарий"
        for _ in range(3):
            Comment.objects.create(
                user=self.user,
                content_type=self.content_type,
                object_id=self.user.pk,
                text=text,
                status=Comment.Status.PUBLISHED,
            )

        result = validate_comment_text(f"  {text}  ", user=self.user)

        self.assertFalse(result.is_allowed)
        self.assertEqual(result.code, ModerationCode.REPEATED)

    def test_old_identical_comments_do_not_trigger_repeat_limit(self):
        text = "Старый комментарий"
        comments = [
            Comment.objects.create(
                user=self.user,
                content_type=self.content_type,
                object_id=self.user.pk,
                text=text,
            )
            for _ in range(3)
        ]
        Comment.objects.filter(pk__in=[comment.pk for comment in comments]).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        result = validate_comment_text(text, user=self.user)

        self.assertTrue(result.is_allowed)

    def test_deleted_and_rejected_comments_do_not_count_as_repeat_spam(self):
        text = "Повтор после удаления"
        comments = []
        for status in (
            Comment.Status.DELETED,
            Comment.Status.REJECTED,
            Comment.Status.DELETED,
        ):
            comments.append(
                Comment.objects.create(
                    user=self.user,
                    content_type=self.content_type,
                    object_id=self.user.pk,
                    text=text,
                    status=status,
                )
            )
        Comment.objects.filter(pk__in=[comment.pk for comment in comments]).update(
            created_at=timezone.now() - timedelta(minutes=2)
        )

        result = validate_comment_text(text, user=self.user)

        self.assertTrue(result.is_allowed)

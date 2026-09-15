from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from cabinet.comments.models import Comment
from cabinet.comments.services import (
    COMMENTS_PER_HOUR,
    COMMENTS_PER_MINUTE,
    MASS_TARGET_LIMIT,
    NEW_USER_COMMENTS_PER_MINUTE,
    NEW_USER_MASS_TARGET_LIMIT,
    AntiSpamCode,
    ModerationCode,
    check_comment_spam,
    validate_comment_text,
)


class CommentAntiSpamServiceTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.user = get_user_model().objects.create_user(
            username="anti-spam-user",
            password="test-password",
        )
        self.content_type = ContentType.objects.get_for_model(self.user)

    def _make_regular_user(self):
        self.user.date_joined = self.now - timedelta(days=30)
        self.user.save(update_fields=["date_joined"])

    def _create_comment(
        self,
        text,
        *,
        object_id=None,
        created_at=None,
        status=Comment.Status.PUBLISHED,
    ):
        comment = Comment.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=object_id or self.user.pk,
            text=text,
            status=status,
        )
        if created_at is not None:
            Comment.objects.filter(pk=comment.pk).update(created_at=created_at)
        return comment

    def test_regular_user_minute_limit(self):
        self._make_regular_user()
        for index in range(COMMENTS_PER_MINUTE):
            self._create_comment(f"Комментарий номер {index} достаточно длинный")

        result = check_comment_spam(
            "Следующий уникальный комментарий",
            self.user,
            now=self.now,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, AntiSpamCode.RATE_LIMIT_MINUTE)
        self.assertEqual(
            result.public_message,
            "Слишком много комментариев. Попробуйте позже.",
        )

    def test_new_user_has_stricter_minute_limit(self):
        for index in range(NEW_USER_COMMENTS_PER_MINUTE):
            self._create_comment(f"Новый пользователь пишет сообщение {index}")

        result = check_comment_spam(
            "Еще один комментарий нового пользователя",
            self.user,
            now=self.now,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, AntiSpamCode.RATE_LIMIT_MINUTE)

    def test_hour_limit(self):
        self._make_regular_user()
        for index in range(COMMENTS_PER_HOUR):
            self._create_comment(
                f"Часовой лимит комментарий номер {index}",
                created_at=self.now - timedelta(minutes=10),
            )

        result = check_comment_spam(
            "Новый текст после большого числа комментариев",
            self.user,
            now=self.now,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, AntiSpamCode.RATE_LIMIT_HOUR)

    def test_identical_text_cannot_be_sent_consecutively(self):
        self._make_regular_user()
        self._create_comment("Очень хороший прогноз")

        result = check_comment_spam(
            "  очень   хороший прогноз  ",
            self.user,
            now=self.now,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, AntiSpamCode.DUPLICATE)
        self.assertEqual(result.public_message, "Вы уже отправили такой комментарий.")

    def test_short_repeated_messages_are_blocked_even_when_interleaved(self):
        self._make_regular_user()
        self._create_comment("Ок!")
        self._create_comment("Совсем другой длинный комментарий")
        self._create_comment("ок...")

        result = check_comment_spam("ОК", self.user, now=self.now)

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, AntiSpamCode.SHORT_REPEAT)

    def test_mass_comments_to_different_targets_are_blocked(self):
        self._make_regular_user()
        for index in range(MASS_TARGET_LIMIT):
            self._create_comment(
                f"Разный комментарий для объекта {index}",
                object_id=1000 + index,
                created_at=self.now - timedelta(seconds=90),
            )

        result = check_comment_spam(
            "Комментарий к еще одному прогнозу",
            self.user,
            content_type=self.content_type,
            object_id=9999,
            now=self.now,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, AntiSpamCode.MASS_TARGETS)
        self.assertEqual(
            result.public_message,
            "Слишком много комментариев. Попробуйте позже.",
        )

    def test_new_user_has_stricter_mass_target_limit(self):
        for index in range(NEW_USER_MASS_TARGET_LIMIT):
            self._create_comment(
                f"Новый пользователь объект {index}",
                object_id=2000 + index,
                created_at=self.now - timedelta(seconds=90),
            )

        result = check_comment_spam(
            "Еще один объект",
            self.user,
            content_type=self.content_type,
            object_id=9999,
            now=self.now,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, AntiSpamCode.MASS_TARGETS)

    def test_same_target_does_not_trigger_mass_target_rule(self):
        self._make_regular_user()
        for index in range(MASS_TARGET_LIMIT):
            self._create_comment(
                f"Разные сообщения к одному объекту {index}",
                object_id=777,
                created_at=self.now - timedelta(seconds=90),
            )

        result = check_comment_spam(
            "Еще один комментарий к тому же объекту",
            self.user,
            content_type=self.content_type,
            object_id=777,
            now=self.now,
        )

        self.assertTrue(result.allowed)

    def test_validate_comment_text_uses_shared_anti_spam_service(self):
        for index in range(NEW_USER_COMMENTS_PER_MINUTE):
            self._create_comment(f"Интеграционный комментарий {index}")

        result = validate_comment_text(
            "Новый чистый комментарий",
            user=self.user,
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.code, ModerationCode.RATE_LIMIT_MINUTE)
        self.assertEqual(
            result.public_message,
            "Слишком много комментариев. Попробуйте позже.",
        )

    def test_rejected_and_deleted_text_do_not_trigger_duplicate_rule(self):
        self._make_regular_user()
        self._create_comment(
            "Можно написать снова",
            status=Comment.Status.REJECTED,
        )
        self._create_comment(
            "Можно написать снова",
            status=Comment.Status.DELETED,
        )

        result = check_comment_spam(
            "Можно написать снова",
            self.user,
            now=self.now,
        )

        self.assertTrue(result.allowed)

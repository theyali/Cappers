from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from cabinet.comments.models import Comment


class CommentModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="commenter",
            password="test-password",
        )
        self.content_type = ContentType.objects.get_for_model(self.user)

    def test_comment_can_target_any_content_type_object(self):
        comment = Comment.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.user.pk,
            text="Тестовый комментарий",
        )

        self.assertEqual(comment.target, self.user)
        self.assertEqual(comment.status, Comment.Status.PUBLISHED)
        self.assertEqual(comment.moderation_reason, "")

    def test_parent_is_available_for_future_replies(self):
        parent = Comment.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.user.pk,
            text="Родительский комментарий",
        )
        reply = Comment.objects.create(
            user=self.user,
            content_type=self.content_type,
            object_id=self.user.pk,
            text="Ответ",
            parent=parent,
        )

        self.assertEqual(reply.parent, parent)
        self.assertEqual(list(parent.replies.all()), [reply])

    def test_supported_statuses_and_text_limit_are_fixed(self):
        self.assertEqual(
            {value for value, _label in Comment.Status.choices},
            {"published", "pending", "rejected", "deleted"},
        )
        self.assertEqual(Comment._meta.get_field("text").max_length, 1000)

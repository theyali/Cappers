import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.comments.models import Comment, CommentMetrics, CommentReaction
from game.models import PredictionCoupon


class PredictionCommentApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.author = user_model.objects.create_user(
            username="comment-author",
            password="password",
            role=user_model.Role.ANALYST,
        )
        self.user = user_model.objects.create_user(
            username="comment-reader",
            password="password",
        )
        self.other_user = user_model.objects.create_user(
            username="comment-other",
            password="password",
        )
        self.staff = user_model.objects.create_user(
            username="comment-staff",
            password="password",
            is_staff=True,
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
        self.content_type = ContentType.objects.get_for_model(
            PredictionCoupon,
            for_concrete_model=False,
        )

    def comments_url(self, prediction=None):
        prediction = prediction or self.prediction
        return reverse(
            "front:prediction_comments",
            kwargs={"prediction_id": prediction.pk},
        )

    def delete_url(self, comment):
        return reverse(
            "front:comment_delete",
            kwargs={"comment_id": comment.pk},
        )

    def reaction_url(self, comment):
        return reverse(
            "front:comment_reaction",
            kwargs={"comment_id": comment.pk},
        )

    def make_comment(self, *, user=None, text="Хороший прогноз", status=Comment.Status.PUBLISHED):
        return Comment.objects.create(
            user=user or self.user,
            content_type=self.content_type,
            object_id=self.prediction.pk,
            text=text,
            status=status,
        )

    def post_comment(self, text, *, client=None):
        client = client or self.client
        return client.post(
            self.comments_url(),
            data=json.dumps({"text": text}),
            content_type="application/json",
        )

    def test_get_returns_only_published_prediction_comments(self):
        published = self.make_comment(text="Первый")
        self.make_comment(text="Удаленный", status=Comment.Status.DELETED)

        response = self.client.get(self.comments_url())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["comments_count"], 1)
        self.assertEqual([item["id"] for item in payload["comments"]], [published.pk])

    def test_guest_cannot_create_comment(self):
        response = self.post_comment("Новый комментарий")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(Comment.objects.count(), 0)

    def test_authenticated_user_can_create_normalized_comment(self):
        self.client.force_login(self.user)

        response = self.post_comment("  Нравится   этот прогноз  ")

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["comments_count"], 1)
        comment = Comment.objects.get()
        self.assertEqual(comment.text, "Нравится этот прогноз")
        self.assertEqual(comment.status, Comment.Status.PUBLISHED)
        self.assertEqual(comment.content_type_id, self.content_type.pk)
        self.assertEqual(comment.object_id, self.prediction.pk)
        self.assertEqual(payload["comment"]["id"], comment.pk)
        self.assertTrue(payload["comment"]["can_delete"])
        self.assertTrue(CommentMetrics.objects.filter(comment=comment).exists())

    def test_comment_rejected_by_moderation_service(self):
        self.client.force_login(self.user)

        response = self.post_comment("Смотрите https://example.com")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "forbidden_link")
        self.assertEqual(Comment.objects.count(), 0)

    def test_duplicate_comment_is_rejected_by_anti_spam(self):
        self.client.force_login(self.user)
        first = self.post_comment("Очень полезный прогноз")
        second = self.post_comment("Очень полезный прогноз")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["code"], "duplicate")
        self.assertEqual(Comment.objects.count(), 1)

    def test_new_user_minute_rate_limit_is_applied(self):
        self.client.force_login(self.user)
        for text in ("Первый ответ", "Второй ответ", "Третий ответ"):
            response = self.post_comment(text)
            self.assertEqual(response.status_code, 201)

        response = self.post_comment("Четвертый ответ")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], "rate_limit_minute")

    def test_draft_prediction_is_not_available_for_comments(self):
        draft = PredictionCoupon.objects.create(
            author=self.author,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            audience=PredictionCoupon.Audience.FREE,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=60,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "front:prediction_comments",
                kwargs={"prediction_id": draft.pk},
            ),
            {"text": "Комментарий"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Comment.objects.count(), 0)

    def test_paid_prediction_is_hidden_without_subscription(self):
        paid = PredictionCoupon.objects.create(
            author=self.author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.PAID,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=60,
            published_at=timezone.now(),
        )

        response = self.client.get(
            reverse(
                "front:prediction_comments",
                kwargs={"prediction_id": paid.pk},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_soft_deletes_comment_and_count_decreases(self):
        comment = self.make_comment()
        self.client.force_login(self.user)

        response = self.client.post(self.delete_url(comment))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], Comment.Status.DELETED)
        self.assertEqual(payload["comments_count"], 0)
        comment.refresh_from_db()
        self.assertEqual(comment.status, Comment.Status.DELETED)
        self.assertEqual(comment.moderation_reason, "deleted_by_user")
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_other_user_cannot_delete_comment(self):
        comment = self.make_comment()
        self.client.force_login(self.other_user)

        response = self.client.post(self.delete_url(comment))

        self.assertEqual(response.status_code, 403)
        comment.refresh_from_db()
        self.assertEqual(comment.status, Comment.Status.PUBLISHED)

    def test_staff_can_soft_delete_any_comment(self):
        comment = self.make_comment()
        self.client.force_login(self.staff)

        response = self.client.post(self.delete_url(comment))

        self.assertEqual(response.status_code, 200)
        comment.refresh_from_db()
        self.assertEqual(comment.status, Comment.Status.DELETED)
        self.assertEqual(comment.moderation_reason, "deleted_by_moderator")

    def test_delete_requires_authentication(self):
        comment = self.make_comment()

        response = self.client.post(self.delete_url(comment))

        self.assertEqual(response.status_code, 401)
        comment.refresh_from_db()
        self.assertEqual(comment.status, Comment.Status.PUBLISHED)

    def test_reaction_toggle_updates_comment_metrics(self):
        comment = self.make_comment()
        self.client.force_login(self.user)

        like_response = self.client.post(
            self.reaction_url(comment),
            data=json.dumps({"kind": CommentReaction.Kind.LIKE}),
            content_type="application/json",
        )
        self.assertEqual(like_response.status_code, 200)
        metrics = CommentMetrics.objects.get(comment=comment)
        self.assertEqual(metrics.likes_count, 1)
        self.assertEqual(metrics.dislikes_count, 0)

        dislike_response = self.client.post(
            self.reaction_url(comment),
            data=json.dumps({"kind": CommentReaction.Kind.DISLIKE}),
            content_type="application/json",
        )
        self.assertEqual(dislike_response.status_code, 200)
        metrics.refresh_from_db()
        self.assertEqual(metrics.likes_count, 0)
        self.assertEqual(metrics.dislikes_count, 1)

        remove_response = self.client.post(
            self.reaction_url(comment),
            data=json.dumps({"kind": CommentReaction.Kind.DISLIKE}),
            content_type="application/json",
        )
        self.assertEqual(remove_response.status_code, 200)
        metrics.refresh_from_db()
        self.assertEqual(metrics.likes_count, 0)
        self.assertEqual(metrics.dislikes_count, 0)
        self.assertEqual(remove_response.json()["comment"]["viewer_reaction"], "")

    def test_reply_create_and_delete_updates_parent_metrics(self):
        parent = self.make_comment(text="Основной комментарий")
        self.client.force_login(self.user)

        create_response = self.client.post(
            self.comments_url(),
            data=json.dumps(
                {
                    "text": "Ответ на основной комментарий",
                    "parent_id": parent.pk,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 201)
        parent_metrics = CommentMetrics.objects.get(comment=parent)
        self.assertEqual(parent_metrics.replies_count, 1)

        reply = Comment.objects.get(pk=create_response.json()["comment"]["id"])
        delete_response = self.client.post(self.delete_url(reply))
        self.assertEqual(delete_response.status_code, 200)
        parent_metrics.refresh_from_db()
        self.assertEqual(parent_metrics.replies_count, 0)

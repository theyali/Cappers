from decimal import Decimal

from django.test import TestCase

from cabinet.comments.services import create_prediction_comment
from cabinet.models import User
from game.models import PredictionCoupon
from notifications.models import Notification


class PredictionCommentNotificationTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="comment-notify-author",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.commenter = User.objects.create_user(
            username="comment-notify-reader",
            first_name="Иван",
            password="test-password",
        )
        self.replier = User.objects.create_user(
            username="comment-notify-replier",
            first_name="Пётр",
            password="test-password",
        )
        self.prediction = PredictionCoupon.objects.create(
            author=self.author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.FREE,
            headline="Прогноз на матч",
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("180.00"),
            confidence=70,
        )

    def test_prediction_author_gets_notification_for_new_comment(self):
        with self.captureOnCommitCallbacks(execute=True):
            comment = create_prediction_comment(
                prediction=self.prediction,
                user=self.commenter,
                text="Отличный прогноз, спасибо за разбор",
            )

        notification = Notification.objects.get(
            recipient=self.author,
            kind=Notification.Kind.PREDICTION_COMMENT,
        )
        self.assertEqual(notification.actor, self.commenter)
        self.assertEqual(
            notification.event_key,
            f"prediction-comment:{comment.pk}:{self.author.pk}",
        )
        self.assertIn(f"#comment-{comment.pk}", notification.url)
        self.assertEqual(notification.meta["prediction_id"], self.prediction.pk)
        self.assertEqual(notification.meta["comment_id"], comment.pk)

    def test_reply_notifies_parent_author_and_prediction_author(self):
        parent = create_prediction_comment(
            prediction=self.prediction,
            user=self.commenter,
            text="Первый комментарий с вопросом",
        )
        Notification.objects.all().delete()

        with self.captureOnCommitCallbacks(execute=True):
            reply = create_prediction_comment(
                prediction=self.prediction,
                user=self.replier,
                text="Ответ на вопрос по прогнозу",
                parent_id=parent.pk,
            )

        reply_notification = Notification.objects.get(
            recipient=self.commenter,
            kind=Notification.Kind.COMMENT_REPLY,
        )
        author_notification = Notification.objects.get(
            recipient=self.author,
            kind=Notification.Kind.PREDICTION_COMMENT,
        )
        self.assertEqual(reply_notification.actor, self.replier)
        self.assertEqual(author_notification.actor, self.replier)
        self.assertIn(f"#comment-{reply.pk}", reply_notification.url)
        self.assertIn(f"#comment-{reply.pk}", author_notification.url)
        self.assertEqual(reply_notification.meta["parent_id"], parent.pk)

    def test_user_does_not_get_notification_for_own_comment(self):
        with self.captureOnCommitCallbacks(execute=True):
            create_prediction_comment(
                prediction=self.prediction,
                user=self.author,
                text="Автор добавил уточнение по прогнозу",
            )

        self.assertFalse(Notification.objects.exists())

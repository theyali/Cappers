from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404

from cabinet.comments.models import Comment
from cabinet.comments.services.anti_spam import check_comment_spam
from cabinet.comments.services.moderation import validate_comment_text
from cabinet.paid_predictions import user_can_view_paid_predictions
from front.metrics import get_prediction_metrics
from game.models import PredictionCoupon


@dataclass(frozen=True)
class CommentServiceError(Exception):
    code: str
    public_message: str
    http_status: int

    def __str__(self) -> str:
        return self.public_message


def get_accessible_prediction(user: Any, prediction_id: int) -> PredictionCoupon:
    prediction = get_object_or_404(
        PredictionCoupon.objects.select_related("author"),
        pk=prediction_id,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    if (
        prediction.audience == PredictionCoupon.Audience.PAID
        and not user_can_view_paid_predictions(user, prediction.author)
    ):
        raise Http404("Прогноз не найден.")
    return prediction


def prediction_comments_queryset(prediction: PredictionCoupon):
    content_type = _prediction_content_type()
    return (
        Comment.objects.filter(
            content_type=content_type,
            object_id=prediction.pk,
            status=Comment.Status.PUBLISHED,
            parent__isnull=True,
        )
        .select_related("user")
        .order_by("created_at", "id")
    )


def prediction_comments_count(prediction: PredictionCoupon) -> int:
    return get_prediction_metrics(prediction.pk).comments_count


def create_prediction_comment(
    *,
    prediction: PredictionCoupon,
    user: Any,
    text: str,
) -> Comment:
    moderation = validate_comment_text(text)
    if not moderation.allowed:
        raise CommentServiceError(
            code=moderation.code,
            public_message=moderation.public_message,
            http_status=422,
        )

    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        anti_spam = check_comment_spam(
            moderation.normalized_text,
            locked_user,
            target=prediction,
        )
        if not anti_spam.allowed:
            raise CommentServiceError(
                code=anti_spam.code,
                public_message=anti_spam.public_message,
                http_status=429,
            )

        return Comment.objects.create(
            user=locked_user,
            content_type=_prediction_content_type(),
            object_id=prediction.pk,
            text=moderation.normalized_text,
            status=Comment.Status.PUBLISHED,
        )


def soft_delete_comment(*, comment_id: int, actor: Any) -> tuple[Comment, int | None]:
    with transaction.atomic():
        comment = get_object_or_404(
            Comment.objects.select_for_update().select_related("content_type", "user"),
            pk=comment_id,
        )
        if not can_delete_comment(comment, actor):
            raise CommentServiceError(
                code="forbidden",
                public_message="Недостаточно прав для удаления комментария.",
                http_status=403,
            )

        if comment.status != Comment.Status.DELETED:
            reason = (
                "deleted_by_user"
                if comment.user_id == getattr(actor, "pk", None)
                else "deleted_by_moderator"
            )
            comment.status = Comment.Status.DELETED
            comment.moderation_reason = reason
            comment.save(update_fields=("status", "moderation_reason", "updated_at"))

        return comment, _comments_count_for_comment_target(comment)


def can_delete_comment(comment: Comment, user: Any) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(
        comment.user_id == getattr(user, "pk", None)
        or getattr(user, "is_staff", False)
        or getattr(user, "is_superuser", False)
    )


def serialize_comment(comment: Comment, *, viewer: Any = None) -> dict:
    user = comment.user
    display_name = (user.get_full_name() or "").strip() or user.username
    avatar_url = ""
    if getattr(user, "avatar", None):
        try:
            avatar_url = user.avatar.url
        except ValueError:
            avatar_url = ""

    return {
        "id": comment.pk,
        "text": comment.text,
        "status": comment.status,
        "created_at": comment.created_at.isoformat(),
        "updated_at": comment.updated_at.isoformat(),
        "user": {
            "id": user.pk,
            "username": user.username,
            "display_name": display_name,
            "avatar_url": avatar_url,
        },
        "can_delete": can_delete_comment(comment, viewer),
    }


def _prediction_content_type() -> ContentType:
    return ContentType.objects.get_for_model(
        PredictionCoupon,
        for_concrete_model=False,
    )


def _comments_count_for_comment_target(comment: Comment) -> int | None:
    prediction_content_type = _prediction_content_type()
    if comment.content_type_id != prediction_content_type.pk:
        return None
    return get_prediction_metrics(comment.object_id).comments_count


__all__ = [
    "CommentServiceError",
    "can_delete_comment",
    "create_prediction_comment",
    "get_accessible_prediction",
    "prediction_comments_count",
    "prediction_comments_queryset",
    "serialize_comment",
    "soft_delete_comment",
]

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F, IntegerField, Q, Value
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse

from cabinet.comments.models import Comment, CommentMetrics, CommentReaction
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
        _comment_queryset_base().filter(
            content_type=content_type,
            object_id=prediction.pk,
            status=Comment.Status.PUBLISHED,
            parent__isnull=True,
        )
        .order_by("created_at", "id")
    )


def prediction_comments_count(prediction: PredictionCoupon) -> int:
    return get_prediction_metrics(prediction.pk).comments_count


def prediction_comments_total_count(prediction: PredictionCoupon) -> int:
    return Comment.objects.filter(
        content_type=_prediction_content_type(),
        object_id=prediction.pk,
        status=Comment.Status.PUBLISHED,
    ).filter(
        Q(parent__isnull=True) | Q(parent__status=Comment.Status.PUBLISHED)
    ).count()


def prediction_comment_target_counts(comment: Comment) -> dict[str, int | None]:
    prediction_content_type = _prediction_content_type()
    if comment.content_type_id != prediction_content_type.pk:
        return {"comments_count": None, "root_comments_count": None}
    total_count = Comment.objects.filter(
        content_type=prediction_content_type,
        object_id=comment.object_id,
        status=Comment.Status.PUBLISHED,
    ).filter(
        Q(parent__isnull=True) | Q(parent__status=Comment.Status.PUBLISHED)
    ).count()
    return {
        "comments_count": total_count,
        "root_comments_count": get_prediction_metrics(comment.object_id).comments_count,
    }


def comment_replies_queryset(parent: Comment):
    return (
        _comment_queryset_base().filter(
            content_type_id=parent.content_type_id,
            object_id=parent.object_id,
            status=Comment.Status.PUBLISHED,
            parent=parent,
        )
        .order_by("created_at", "id")
    )


def comment_replies_count(parent: Comment) -> int:
    annotated = getattr(parent, "replies_count", None)
    if annotated is not None:
        return int(annotated or 0)
    return int(_get_comment_metrics(parent.pk).replies_count or 0)


def attach_comment_replies(
    comments,
    *,
    limit: int,
) -> None:
    for comment in comments:
        replies_count = comment_replies_count(comment)
        replies = list(comment_replies_queryset(comment)[:limit]) if limit else []
        comment.published_replies = replies
        comment.replies_total_count = replies_count
        comment.replies_count = replies_count
        if replies_count <= len(replies):
            comment.replies_next_page = None
        else:
            comment.replies_next_page = 2 if limit else 1


def attach_viewer_reactions(comments, viewer: Any) -> None:
    visible_comments = []
    for comment in comments:
        visible_comments.append(comment)
        visible_comments.extend(getattr(comment, "published_replies", []) or [])

    if not visible_comments:
        return
    if not getattr(viewer, "is_authenticated", False):
        for comment in visible_comments:
            comment.viewer_reaction = ""
        return

    reaction_map = dict(
        CommentReaction.objects.filter(
            user=viewer,
            comment_id__in=[comment.pk for comment in visible_comments],
        ).values_list("comment_id", "kind")
    )
    for comment in visible_comments:
        comment.viewer_reaction = reaction_map.get(comment.pk, "")


def get_accessible_comment_parent(user: Any, comment_id: int) -> Comment:
    comment = get_object_or_404(
        Comment.objects.select_related("content_type", "user", "metrics"),
        pk=comment_id,
        status=Comment.Status.PUBLISHED,
        parent__isnull=True,
    )
    _ensure_comment_target_access(comment, user)
    return comment


def create_prediction_comment(
    *,
    prediction: PredictionCoupon,
    user: Any,
    text: str,
    parent_id: int | None = None,
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
        parent = _resolve_reply_parent(prediction=prediction, parent_id=parent_id)
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

        comment = Comment.objects.create(
            user=locked_user,
            content_type=_prediction_content_type(),
            object_id=prediction.pk,
            text=moderation.normalized_text,
            status=Comment.Status.PUBLISHED,
            parent=parent,
        )
        comment.likes_count = 0
        comment.dislikes_count = 0
        comment.replies_count = 0
        comment.replies_total_count = 0
        comment.replies_next_page = None
        comment.published_replies = []
        comment.viewer_reaction = ""
        return comment


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


def set_comment_reaction(*, comment_id: int, user: Any, kind: str) -> Comment:
    if not getattr(user, "is_authenticated", False):
        raise CommentServiceError(
            code="authentication_required",
            public_message="Для реакции на комментарий нужно войти в аккаунт.",
            http_status=401,
        )

    comment = get_object_or_404(
        Comment.objects.select_related("content_type", "user"),
        pk=comment_id,
        status=Comment.Status.PUBLISHED,
    )
    _ensure_comment_target_access(comment, user)
    normalized_kind = (kind or "").strip().lower()
    if normalized_kind not in {"", CommentReaction.Kind.LIKE, CommentReaction.Kind.DISLIKE}:
        raise CommentServiceError(
            code="invalid_reaction",
            public_message="Некорректная реакция на комментарий.",
            http_status=400,
        )

    active_kind = ""
    with transaction.atomic():
        existing = CommentReaction.objects.select_for_update().filter(
            comment=comment,
            user=user,
        ).first()
        if not normalized_kind or (existing and existing.kind == normalized_kind):
            if existing:
                existing.delete()
        elif existing:
            existing.kind = normalized_kind
            existing.save(update_fields=("kind",))
            active_kind = normalized_kind
        else:
            CommentReaction.objects.create(
                comment=comment,
                user=user,
                kind=normalized_kind,
            )
            active_kind = normalized_kind

        metrics = CommentMetrics.objects.select_for_update().get(comment_id=comment.pk)

    comment.likes_count = int(metrics.likes_count or 0)
    comment.dislikes_count = int(metrics.dislikes_count or 0)
    comment.replies_count = int(metrics.replies_count or 0)
    comment.viewer_reaction = active_kind
    return comment


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
        "parent_id": comment.parent_id,
        "user": {
            "id": user.pk,
            "username": user.username,
            "display_name": display_name,
            "avatar_url": avatar_url,
            "profile_url": reverse("front:expert_profile", kwargs={"username": user.username}),
        },
        "can_delete": can_delete_comment(comment, viewer),
        "likes_count": _reaction_count(comment, CommentReaction.Kind.LIKE),
        "dislikes_count": _reaction_count(comment, CommentReaction.Kind.DISLIKE),
        "viewer_reaction": _viewer_reaction(comment, viewer),
        "replies_count": _replies_metric_count(comment),
        "replies_next_page": getattr(comment, "replies_next_page", None),
        "replies_has_next": bool(getattr(comment, "replies_next_page", None)),
        "replies": [
            serialize_comment(reply, viewer=viewer)
            for reply in getattr(comment, "published_replies", []) or []
        ],
    }


def _prediction_content_type() -> ContentType:
    return ContentType.objects.get_for_model(
        PredictionCoupon,
        for_concrete_model=False,
    )


def _comment_queryset_base():
    return (
        Comment.objects.select_related("user", "metrics")
        .annotate(
            likes_count=Coalesce(
                F("metrics__likes_count"),
                Value(0),
                output_field=IntegerField(),
            ),
            dislikes_count=Coalesce(
                F("metrics__dislikes_count"),
                Value(0),
                output_field=IntegerField(),
            ),
            replies_count=Coalesce(
                F("metrics__replies_count"),
                Value(0),
                output_field=IntegerField(),
            ),
        )
    )


def _resolve_reply_parent(
    *,
    prediction: PredictionCoupon,
    parent_id: int | None,
) -> Comment | None:
    if not parent_id:
        return None
    parent = get_object_or_404(
        Comment.objects.select_for_update(),
        pk=parent_id,
        content_type=_prediction_content_type(),
        object_id=prediction.pk,
        status=Comment.Status.PUBLISHED,
    )
    if parent.parent_id:
        raise CommentServiceError(
            code="nested_reply_not_allowed",
            public_message="Можно отвечать только на основной комментарий.",
            http_status=422,
        )
    return parent


def _comments_count_for_comment_target(comment: Comment) -> int | None:
    prediction_content_type = _prediction_content_type()
    if comment.content_type_id != prediction_content_type.pk:
        return None
    return get_prediction_metrics(comment.object_id).comments_count


def _ensure_comment_target_access(comment: Comment, user: Any) -> None:
    prediction_content_type = _prediction_content_type()
    if comment.content_type_id != prediction_content_type.pk:
        return
    prediction = get_object_or_404(
        PredictionCoupon.objects.select_related("author"),
        pk=comment.object_id,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    if (
        prediction.audience == PredictionCoupon.Audience.PAID
        and not user_can_view_paid_predictions(user, prediction.author)
    ):
        raise Http404("Комментарий не найден.")


def _get_comment_metrics(comment_id: int) -> CommentMetrics:
    metrics, _ = CommentMetrics.objects.get_or_create(comment_id=comment_id)
    return metrics


def _reaction_count(comment: Comment, kind: str) -> int:
    annotated_name = "likes_count" if kind == CommentReaction.Kind.LIKE else "dislikes_count"
    annotated = getattr(comment, annotated_name, None)
    if annotated is not None:
        return int(annotated or 0)
    metrics = _get_comment_metrics(comment.pk)
    return int(getattr(metrics, annotated_name) or 0)


def _replies_metric_count(comment: Comment) -> int:
    total = getattr(comment, "replies_total_count", None)
    if total is not None:
        return int(total or 0)
    annotated = getattr(comment, "replies_count", None)
    if annotated is not None:
        return int(annotated or 0)
    return int(_get_comment_metrics(comment.pk).replies_count or 0)


def _viewer_reaction(comment: Comment, viewer: Any) -> str:
    if not getattr(viewer, "is_authenticated", False):
        return ""
    annotated = getattr(comment, "viewer_reaction", None)
    if annotated is not None:
        return annotated
    return (
        CommentReaction.objects.filter(comment=comment, user=viewer)
        .values_list("kind", flat=True)
        .first()
        or ""
    )


__all__ = [
    "CommentServiceError",
    "attach_comment_replies",
    "attach_viewer_reactions",
    "can_delete_comment",
    "comment_replies_count",
    "comment_replies_queryset",
    "create_prediction_comment",
    "get_accessible_comment_parent",
    "get_accessible_prediction",
    "prediction_comments_count",
    "prediction_comment_target_counts",
    "prediction_comments_total_count",
    "prediction_comments_queryset",
    "serialize_comment",
    "set_comment_reaction",
    "soft_delete_comment",
]

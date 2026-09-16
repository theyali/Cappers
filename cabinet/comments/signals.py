from django.db.models import Case, F, PositiveIntegerField, Value, When
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Comment, CommentMetrics, CommentReaction


def _counter_expression(field_name: str, delta: int):
    if delta >= 0:
        return F(field_name) + Value(delta)
    return Case(
        When(**{f"{field_name}__gt": 0}, then=F(field_name) - Value(abs(delta))),
        default=Value(0),
        output_field=PositiveIntegerField(),
    )


def _ensure_metrics(comment_id: int) -> CommentMetrics:
    metrics, _ = CommentMetrics.objects.get_or_create(comment_id=comment_id)
    return metrics


def _change_metric(comment_id: int, field_name: str, delta: int) -> None:
    _ensure_metrics(comment_id)
    CommentMetrics.objects.filter(comment_id=comment_id).update(
        **{
            field_name: _counter_expression(field_name, delta),
            "updated_at": timezone.now(),
        }
    )


@receiver(pre_save, sender=Comment)
def remember_previous_comment_visibility(sender, instance: Comment, **kwargs) -> None:
    if not instance.pk:
        instance._metrics_previous_reply_state = None
        return
    instance._metrics_previous_reply_state = sender.objects.filter(pk=instance.pk).values_list(
        "status", "parent_id"
    ).first()


@receiver(post_save, sender=Comment)
def sync_comment_metrics(sender, instance: Comment, created: bool, **kwargs) -> None:
    _ensure_metrics(instance.pk)
    previous = getattr(instance, "_metrics_previous_reply_state", None)
    old_status, old_parent_id = previous if previous else (None, None)
    old_visible = bool(old_parent_id and old_status == Comment.Status.PUBLISHED)
    new_visible = bool(instance.parent_id and instance.status == Comment.Status.PUBLISHED)

    if old_visible and (not new_visible or old_parent_id != instance.parent_id):
        _change_metric(old_parent_id, "replies_count", -1)
    if new_visible and (not old_visible or old_parent_id != instance.parent_id):
        _change_metric(instance.parent_id, "replies_count", 1)


@receiver(post_delete, sender=Comment)
def sync_deleted_comment_metrics(sender, instance: Comment, **kwargs) -> None:
    if instance.parent_id and instance.status == Comment.Status.PUBLISHED:
        CommentMetrics.objects.filter(comment_id=instance.parent_id).update(
            replies_count=_counter_expression("replies_count", -1),
            updated_at=timezone.now(),
        )


@receiver(pre_save, sender=CommentReaction)
def remember_previous_reaction_kind(sender, instance: CommentReaction, **kwargs) -> None:
    if not instance.pk:
        instance._metrics_previous_kind = None
        return
    instance._metrics_previous_kind = sender.objects.filter(pk=instance.pk).values_list(
        "kind", flat=True
    ).first()


@receiver(post_save, sender=CommentReaction)
def sync_comment_reaction_metrics(sender, instance: CommentReaction, created: bool, **kwargs) -> None:
    previous_kind = getattr(instance, "_metrics_previous_kind", None)
    if previous_kind == instance.kind:
        return
    if previous_kind == CommentReaction.Kind.LIKE:
        _change_metric(instance.comment_id, "likes_count", -1)
    elif previous_kind == CommentReaction.Kind.DISLIKE:
        _change_metric(instance.comment_id, "dislikes_count", -1)

    if instance.kind == CommentReaction.Kind.LIKE:
        _change_metric(instance.comment_id, "likes_count", 1)
    elif instance.kind == CommentReaction.Kind.DISLIKE:
        _change_metric(instance.comment_id, "dislikes_count", 1)


@receiver(post_delete, sender=CommentReaction)
def sync_deleted_comment_reaction_metrics(sender, instance: CommentReaction, **kwargs) -> None:
    field_name = (
        "likes_count"
        if instance.kind == CommentReaction.Kind.LIKE
        else "dislikes_count"
    )
    CommentMetrics.objects.filter(comment_id=instance.comment_id).update(
        **{
            field_name: _counter_expression(field_name, -1),
            "updated_at": timezone.now(),
        }
    )

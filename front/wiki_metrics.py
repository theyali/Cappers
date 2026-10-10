from __future__ import annotations

from django.db import transaction
from django.db.models import Case, F, PositiveIntegerField, Value, When
from django.utils import timezone

from .models import WikiVideo, WikiVideoProgress, WikiVideoReaction


VIDEO_COMPLETION_RATIO = 0.9


def increment_wiki_video_views(video: WikiVideo) -> WikiVideo:
    with transaction.atomic():
        locked_video = WikiVideo.objects.select_for_update().get(pk=video.pk)
        WikiVideo.objects.filter(pk=locked_video.pk).update(
            views_count=F("views_count") + Value(1),
            updated_at=timezone.now(),
        )
        locked_video.refresh_from_db(fields=("views_count", "updated_at"))
    return locked_video


def set_wiki_video_reaction(
    video: WikiVideo,
    user,
    kind: str,
) -> tuple[str | None, WikiVideo]:
    if kind not in {WikiVideoReaction.KIND_LIKE, WikiVideoReaction.KIND_DISLIKE}:
        raise ValueError("Unknown reaction kind.")

    with transaction.atomic():
        locked_video = WikiVideo.objects.select_for_update().get(pk=video.pk)
        reaction = WikiVideoReaction.objects.select_for_update().filter(
            video=locked_video,
            user=user,
        ).first()

        if reaction is None:
            WikiVideoReaction.objects.create(video=locked_video, user=user, kind=kind)
            _change_reaction_counter(locked_video.pk, kind, 1)
            active_kind = kind
        elif reaction.kind == kind:
            reaction.delete()
            _change_reaction_counter(locked_video.pk, kind, -1)
            active_kind = None
        else:
            previous_kind = reaction.kind
            reaction.kind = kind
            reaction.save(update_fields=("kind", "updated_at"))
            _change_reaction_counter(locked_video.pk, previous_kind, -1)
            _change_reaction_counter(locked_video.pk, kind, 1)
            active_kind = kind

        locked_video.refresh_from_db(
            fields=("likes_count", "dislikes_count", "updated_at")
        )

    return active_kind, locked_video


def save_wiki_video_progress(
    video: WikiVideo,
    user,
    *,
    position_seconds: int,
    duration_seconds: int = 0,
) -> WikiVideoProgress:
    position = max(0, int(position_seconds or 0))
    duration = max(0, int(duration_seconds or 0))
    if duration:
        position = min(position, duration)
    completed = bool(duration and position / duration >= VIDEO_COMPLETION_RATIO)

    with transaction.atomic():
        progress, created = WikiVideoProgress.objects.select_for_update().get_or_create(
            video=video,
            user=user,
            defaults={
                "position_seconds": position,
                "duration_seconds": duration,
                "completed": completed,
                "completed_at": timezone.now() if completed else None,
            },
        )
        if not created:
            completed_at = progress.completed_at
            if completed and completed_at is None:
                completed_at = timezone.now()
            if not completed:
                completed_at = None
            progress.position_seconds = position
            progress.duration_seconds = duration
            progress.completed = completed
            progress.completed_at = completed_at
            progress.save(
                update_fields=(
                    "position_seconds",
                    "duration_seconds",
                    "completed",
                    "completed_at",
                    "last_watched_at",
                )
            )
    return progress


def _change_reaction_counter(video_id: int, kind: str, delta: int) -> None:
    field_name = "likes_count" if kind == WikiVideoReaction.KIND_LIKE else "dislikes_count"
    WikiVideo.objects.filter(pk=video_id).update(
        **{
            field_name: _counter_expression(field_name, delta),
            "updated_at": timezone.now(),
        }
    )


def _counter_expression(field_name: str, delta: int):
    if delta >= 0:
        return F(field_name) + Value(delta)
    return Case(
        When(**{f"{field_name}__gt": 0}, then=F(field_name) - Value(abs(delta))),
        default=Value(0),
        output_field=PositiveIntegerField(),
    )

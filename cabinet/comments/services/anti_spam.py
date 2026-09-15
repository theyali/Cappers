from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from cabinet.comments.models import Comment
from cabinet.comments.services.moderation import normalize_comment_text


COMMENTS_PER_MINUTE = 6
COMMENTS_PER_HOUR = 40

NEW_USER_AGE = timedelta(days=7)
NEW_USER_COMMENTS_PER_MINUTE = 3
NEW_USER_COMMENTS_PER_HOUR = 15

CONSECUTIVE_REPEAT_WINDOW = timedelta(minutes=10)
SHORT_REPEAT_WINDOW = timedelta(minutes=10)
SHORT_REPEAT_MAX_LENGTH = 12
SHORT_REPEAT_LIMIT = 2

MASS_TARGET_WINDOW = timedelta(minutes=2)
MASS_TARGET_LIMIT = 6
NEW_USER_MASS_TARGET_LIMIT = 4

_TOO_MANY_MESSAGE = "Слишком много комментариев. Попробуйте позже."
_ACTIVE_TEXT_STATUSES = (Comment.Status.PUBLISHED, Comment.Status.PENDING)


class AntiSpamCode:
    RATE_LIMIT_MINUTE = "rate_limit_minute"
    RATE_LIMIT_HOUR = "rate_limit_hour"
    DUPLICATE = "duplicate"
    SHORT_REPEAT = "short_repeat"
    MASS_TARGETS = "mass_targets"


@dataclass(frozen=True)
class AntiSpamResult:
    allowed: bool
    code: str = ""
    public_message: str = ""
    retry_after_seconds: int | None = None

    @property
    def is_allowed(self) -> bool:
        return self.allowed

    @property
    def ok(self) -> bool:
        return self.allowed

    @property
    def reason(self) -> str:
        return self.code


def check_comment_spam(
    text: str,
    user: Any,
    *,
    target: Any = None,
    content_type: Any = None,
    object_id: Any = None,
    now=None,
) -> AntiSpamResult:
    """Apply reusable comment rate limits and behavioural anti-spam rules."""
    user_id = getattr(user, "pk", None)
    if not user_id:
        return AntiSpamResult(allowed=True)

    now = now or timezone.now()
    normalized = normalize_comment_text(text)
    canonical = _canonical_text(normalized)

    if canonical and _is_consecutive_duplicate(user_id, canonical, now):
        return _blocked(
            AntiSpamCode.DUPLICATE,
            "Вы уже отправили такой комментарий.",
        )

    minute_limit, hour_limit, mass_target_limit = _limits_for_user(user, now)

    minute_count = Comment.objects.filter(
        user_id=user_id,
        created_at__gte=now - timedelta(minutes=1),
    ).count()
    if minute_count >= minute_limit:
        return _blocked(AntiSpamCode.RATE_LIMIT_MINUTE, _TOO_MANY_MESSAGE)

    hour_count = Comment.objects.filter(
        user_id=user_id,
        created_at__gte=now - timedelta(hours=1),
    ).count()
    if hour_count >= hour_limit:
        return _blocked(AntiSpamCode.RATE_LIMIT_HOUR, _TOO_MANY_MESSAGE)

    short_key = _short_text_key(normalized)
    if short_key and len(short_key) <= SHORT_REPEAT_MAX_LENGTH:
        if _short_repeat_count(user_id, short_key, now) >= SHORT_REPEAT_LIMIT:
            return _blocked(
                AntiSpamCode.SHORT_REPEAT,
                "Не отправляйте однотипные короткие комментарии.",
            )

    target_key = _resolve_target_key(target, content_type, object_id)
    if target_key and _is_mass_target_posting(
        user_id,
        target_key,
        mass_target_limit,
        now,
    ):
        return _blocked(AntiSpamCode.MASS_TARGETS, _TOO_MANY_MESSAGE)

    return AntiSpamResult(allowed=True)


def _limits_for_user(user: Any, now) -> tuple[int, int, int]:
    joined_at = getattr(user, "date_joined", None)
    is_new_user = bool(joined_at and joined_at >= now - NEW_USER_AGE)

    if is_new_user:
        return (
            NEW_USER_COMMENTS_PER_MINUTE,
            NEW_USER_COMMENTS_PER_HOUR,
            NEW_USER_MASS_TARGET_LIMIT,
        )

    return COMMENTS_PER_MINUTE, COMMENTS_PER_HOUR, MASS_TARGET_LIMIT


def _is_consecutive_duplicate(user_id: int, canonical: str, now) -> bool:
    last_text = (
        Comment.objects.filter(
            user_id=user_id,
            status__in=_ACTIVE_TEXT_STATUSES,
            created_at__gte=now - CONSECUTIVE_REPEAT_WINDOW,
        )
        .order_by("-created_at", "-id")
        .values_list("text", flat=True)
        .first()
    )
    return bool(last_text and _canonical_text(last_text) == canonical)


def _short_repeat_count(user_id: int, short_key: str, now) -> int:
    recent_texts = (
        Comment.objects.filter(
            user_id=user_id,
            status__in=_ACTIVE_TEXT_STATUSES,
            created_at__gte=now - SHORT_REPEAT_WINDOW,
        )
        .order_by("-created_at", "-id")
        .values_list("text", flat=True)[:COMMENTS_PER_HOUR]
    )
    return sum(_short_text_key(text) == short_key for text in recent_texts)


def _resolve_target_key(
    target: Any,
    content_type: Any,
    object_id: Any,
) -> tuple[int, int] | None:
    if target is not None:
        target_id = getattr(target, "pk", None)
        if not target_id:
            return None
        target_content_type = ContentType.objects.get_for_model(
            target,
            for_concrete_model=False,
        )
        return target_content_type.pk, int(target_id)

    content_type_id = getattr(content_type, "pk", content_type)
    if not content_type_id or not object_id:
        return None

    try:
        return int(content_type_id), int(object_id)
    except (TypeError, ValueError):
        return None


def _is_mass_target_posting(
    user_id: int,
    target_key: tuple[int, int],
    target_limit: int,
    now,
) -> bool:
    recent_targets = set(
        Comment.objects.filter(
            user_id=user_id,
            created_at__gte=now - MASS_TARGET_WINDOW,
        )
        .order_by()
        .values_list("content_type_id", "object_id")
        .distinct()[:target_limit]
    )
    return target_key not in recent_targets and len(recent_targets) >= target_limit


def _canonical_text(text: str) -> str:
    return normalize_comment_text(text).casefold()


def _short_text_key(text: str) -> str:
    return "".join(character for character in _canonical_text(text) if character.isalnum())


def _blocked(code: str, public_message: str) -> AntiSpamResult:
    return AntiSpamResult(
        allowed=False,
        code=code,
        public_message=public_message,
    )


__all__ = [
    "COMMENTS_PER_HOUR",
    "COMMENTS_PER_MINUTE",
    "CONSECUTIVE_REPEAT_WINDOW",
    "MASS_TARGET_LIMIT",
    "MASS_TARGET_WINDOW",
    "NEW_USER_AGE",
    "NEW_USER_COMMENTS_PER_HOUR",
    "NEW_USER_COMMENTS_PER_MINUTE",
    "NEW_USER_MASS_TARGET_LIMIT",
    "SHORT_REPEAT_LIMIT",
    "SHORT_REPEAT_MAX_LENGTH",
    "SHORT_REPEAT_WINDOW",
    "AntiSpamCode",
    "AntiSpamResult",
    "check_comment_spam",
]

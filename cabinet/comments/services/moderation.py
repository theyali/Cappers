import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.utils import timezone


COMMENT_MAX_LENGTH = 1000
REPEAT_WINDOW = timedelta(hours=24)
REPEAT_LIMIT = 3

_WHITESPACE_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<!--.*?-->|</?[a-z][^>]*>", re.IGNORECASE | re.DOTALL)
_HTTP_RE = re.compile(r"\bhttps?://", re.IGNORECASE)
_WWW_RE = re.compile(r"\bwww\.", re.IGNORECASE)
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[\w.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[a-zа-яё0-9](?:[a-zа-яё0-9-]{0,61}[a-zа-яё0-9])?\.)+"
    r"(?:[a-zа-яё]{2,24}|xn--[a-z0-9-]{2,59})\b",
    re.IGNORECASE,
)
_TELEGRAM_RE = re.compile(r"(?<![\w.])(?:t\.me|telegram\.me)/[a-z0-9_+/-]+", re.IGNORECASE)
_MENTION_RE = re.compile(r"(?<![\w@])@[a-z0-9_]{3,32}\b", re.IGNORECASE)
_DOMAIN_RE = re.compile(
    r"(?<![@\w-])"
    r"(?:[a-zа-яё0-9](?:[a-zа-яё0-9-]{0,61}[a-zа-яё0-9])?\.)+"
    r"(?:[a-zа-яё]{2,24}|xn--[a-z0-9-]{2,59})"
    r"(?::\d{2,5})?(?:[/?:#][^\s]*)?",
    re.IGNORECASE,
)
_PROFANITY_RE = re.compile(
    r"(?<![a-zа-яё0-9])(?:"
    r"бля(?:дь|ть)|"
    r"сука|"
    r"хуй|хуя|хуе(?:в|т|м|й)?|хуё(?:в|т|м|й)?|"
    r"пизд[a-zа-яё]*|"
    r"[её]б(?:ать|ал|ала|али|ан|ану|ёт|ет|ут|уч|учий|ись|иська|нут|нулся|аный|анный)|"
    r"fuck[a-z]*|shit[a-z]*|bitch(?:es)?"
    r")(?![a-zа-яё0-9])",
    re.IGNORECASE,
)


class ModerationCode:
    EMPTY = "empty"
    TOO_LONG = "too_long"
    HTML = "html"
    FORBIDDEN_LINK = "forbidden_link"
    PROFANITY = "profanity"
    REPEATED = "repeated"


@dataclass(frozen=True)
class ModerationResult:
    is_allowed: bool
    normalized_text: str
    code: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.is_allowed


def normalize_comment_text(text: str) -> str:
    """Return canonical user text used both for storage and moderation."""
    if text is None:
        return ""

    normalized = unicodedata.normalize("NFKC", str(text))
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def contains_forbidden_link(text: str) -> bool:
    """Detect links, domains, Telegram handles and e-mail addresses."""
    normalized = normalize_comment_text(text)
    if not normalized:
        return False

    return any(
        pattern.search(normalized)
        for pattern in (
            _HTTP_RE,
            _WWW_RE,
            _EMAIL_RE,
            _TELEGRAM_RE,
            _MENTION_RE,
            _DOMAIN_RE,
        )
    )


def contains_profanity(text: str) -> bool:
    normalized = normalize_comment_text(text)
    return bool(normalized and _PROFANITY_RE.search(normalized))


def validate_comment_text(text: str, user: Any = None) -> ModerationResult:
    normalized = normalize_comment_text(text)

    if not normalized:
        return _rejected(normalized, ModerationCode.EMPTY, "Комментарий не может быть пустым.")

    if len(normalized) > COMMENT_MAX_LENGTH:
        return _rejected(
            normalized,
            ModerationCode.TOO_LONG,
            f"Комментарий не может быть длиннее {COMMENT_MAX_LENGTH} символов.",
        )

    if _HTML_TAG_RE.search(normalized):
        return _rejected(normalized, ModerationCode.HTML, "HTML в комментариях запрещён.")

    if contains_forbidden_link(normalized):
        return _rejected(
            normalized,
            ModerationCode.FORBIDDEN_LINK,
            "Ссылки, e-mail и упоминания каналов в комментариях запрещены.",
        )

    if contains_profanity(normalized):
        return _rejected(
            normalized,
            ModerationCode.PROFANITY,
            "Комментарий содержит запрещённую лексику.",
        )

    if _is_repeated_comment(normalized, user):
        return _rejected(
            normalized,
            ModerationCode.REPEATED,
            "Одинаковый комментарий нельзя отправлять много раз.",
        )

    return ModerationResult(is_allowed=True, normalized_text=normalized)


def _is_repeated_comment(text: str, user: Any) -> bool:
    user_id = getattr(user, "pk", None)
    if not user_id:
        return False

    from cabinet.comments.models import Comment

    since = timezone.now() - REPEAT_WINDOW
    repeated_count = (
        Comment.objects.filter(
            user_id=user_id,
            text__iexact=text,
            status__in=(Comment.Status.PUBLISHED, Comment.Status.PENDING),
            created_at__gte=since,
        )
        .order_by()
        .count()
    )
    return repeated_count >= REPEAT_LIMIT


def _rejected(text: str, code: str, reason: str) -> ModerationResult:
    return ModerationResult(
        is_allowed=False,
        normalized_text=text,
        code=code,
        reason=reason,
    )

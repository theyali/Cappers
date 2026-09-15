import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from cabinet.comments.data.profanity_patterns import matches_profanity, normalize_obfuscated_text


COMMENT_MAX_LENGTH = 1000

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


class ModerationCode:
    EMPTY = "empty"
    TOO_LONG = "too_long"
    HTML = "html"
    FORBIDDEN_LINK = "forbidden_link"
    PROFANITY = "profanity"
    RATE_LIMIT_MINUTE = "rate_limit_minute"
    RATE_LIMIT_HOUR = "rate_limit_hour"
    DUPLICATE = "duplicate"
    REPEATED = DUPLICATE
    SHORT_REPEAT = "short_repeat"
    MASS_TARGETS = "mass_targets"


@dataclass(frozen=True)
class ModerationResult:
    is_allowed: bool
    normalized_text: str
    code: str = ""
    reason: str = ""
    status: str = "published"
    public_message: str = ""

    @property
    def allowed(self) -> bool:
        return self.is_allowed

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
    return matches_profanity(normalize_comment_text(text))


def validate_comment_text(
    text: str,
    user: Any = None,
    *,
    target: Any = None,
    content_type: Any = None,
    object_id: Any = None,
) -> ModerationResult:
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
            "Комментарий содержит запрещенные слова.",
        )

    if user is not None:
        from cabinet.comments.services.anti_spam import check_comment_spam

        anti_spam_result = check_comment_spam(
            normalized,
            user,
            target=target,
            content_type=content_type,
            object_id=object_id,
        )
        if not anti_spam_result.allowed:
            return _rejected(
                normalized,
                anti_spam_result.code,
                anti_spam_result.public_message,
            )

    return ModerationResult(
        is_allowed=True,
        normalized_text=normalized,
        status="published",
    )


def _rejected(text: str, code: str, public_message: str) -> ModerationResult:
    return ModerationResult(
        is_allowed=False,
        normalized_text=text,
        code=code,
        reason=code,
        status="rejected",
        public_message=public_message,
    )


__all__ = [
    "COMMENT_MAX_LENGTH",
    "ModerationCode",
    "ModerationResult",
    "contains_forbidden_link",
    "contains_profanity",
    "normalize_comment_text",
    "normalize_obfuscated_text",
    "validate_comment_text",
]

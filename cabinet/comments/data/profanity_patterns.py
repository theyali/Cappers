import re
import unicodedata
from functools import lru_cache

from .forbidden_source import (
    load_forbidden_lexicon,
    reset_forbidden_lexicon_source_cache,
)


# Устойчивые транслит-варианты заменяем целиком после удаления маскирующих разделителей.
_TRANSLIT_ALIASES = {
    "blyad": "бляд",
    "blyat": "бляд",
    "suka": "сука",
    "huy": "хуй",
    "hui": "хуй",
    "huinya": "хуйня",
    "pizda": "пизда",
    "pizdec": "пиздец",
    "pizdets": "пиздец",
    "ebat": "ебать",
    "yebat": "ебать",
    "dolboeb": "долбоеб",
    "mudak": "мудак",
    "fuck": "ебать",
    "shit": "сука",
    "bitch": "сука",
}

_CHAR_TRANSLATION = str.maketrans(
    {
        "a": "а",
        "b": "б",
        "c": "с",
        "d": "д",
        "e": "е",
        "h": "х",
        "i": "и",
        "k": "к",
        "m": "м",
        "o": "о",
        "p": "п",
        "t": "т",
        "u": "у",
        "x": "х",
        "y": "у",
        "z": "з",
        "0": "о",
        "1": "и",
        "3": "з",
        "4": "а",
        "6": "б",
    }
)

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_MASK_BETWEEN_CHARS_RE = re.compile(
    r"(?<=[a-zа-яё0-9])[*._~`'\-]+(?=[a-zа-яё0-9])",
    re.IGNORECASE,
)
_SINGLE_LETTER_CHAIN_RE = re.compile(
    r"(?<![a-zа-яё0-9])(?:[a-zа-яё0-9](?:[\s._*~`'\-]+)){2,}[a-zа-яё0-9](?![a-zа-яё0-9])",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)

# Корневые шаблоны нужны для склонений и частичных маскировок, когда одна буква пропущена.
# Они остаются встроенным safety baseline. Дополнительные regex можно будет хранить
# в ForbiddenPattern через сменный ForbiddenLexiconSource.
_ROOT_PATTERNS = (
    re.compile(r"(?<![а-я0-9])бл(?:я)?д[а-я]*(?![а-я0-9])", re.IGNORECASE),
    re.compile(r"(?<![а-я0-9])сук(?:а|и|у|ой|е)(?![а-я0-9])", re.IGNORECASE),
    re.compile(r"(?<![а-я0-9])(?:ху[йеяи]|хй)[а-я]*(?![а-я0-9])", re.IGNORECASE),
    re.compile(r"(?<![а-я0-9])п(?:и)?зд[а-я]*(?![а-я0-9])", re.IGNORECASE),
    re.compile(r"(?<![а-я0-9])еб(?:а|у|л|н|уч)[а-я]*(?![а-я0-9])", re.IGNORECASE),
    re.compile(r"(?<![а-я0-9])долбо(?:е)?б[а-я]*(?![а-я0-9])", re.IGNORECASE),
    re.compile(r"(?<![а-я0-9])мудак[а-я]*(?![а-я0-9])", re.IGNORECASE),
    re.compile(r"(?<![а-я0-9])мраз[а-я]*(?![а-я0-9])", re.IGNORECASE),
)

_ENGLISH_PATTERNS = (
    re.compile(r"(?<![a-z0-9])fuck[a-z]*(?![a-z0-9])", re.IGNORECASE),
    re.compile(r"(?<![a-z0-9])shit[a-z]*(?![a-z0-9])", re.IGNORECASE),
    re.compile(r"(?<![a-z0-9])bitch(?:es)?(?![a-z0-9])", re.IGNORECASE),
)


def _compact_single_letter_chain(match: re.Match) -> str:
    return re.sub(r"[^a-zа-яё0-9]", "", match.group(0), flags=re.IGNORECASE)


def normalize_obfuscated_text(text: str) -> str:
    """Нормализует текст только для поиска обходов фильтра, не для хранения."""
    if text is None:
        return ""

    normalized = unicodedata.normalize("NFKC", str(text)).casefold().replace("ё", "е")
    normalized = _ZERO_WIDTH_RE.sub("", normalized)
    normalized = _SINGLE_LETTER_CHAIN_RE.sub(_compact_single_letter_chain, normalized)
    normalized = _MASK_BETWEEN_CHARS_RE.sub("", normalized)

    for alias, replacement in _TRANSLIT_ALIASES.items():
        normalized = re.sub(
            rf"(?<![a-z]){re.escape(alias)}(?![a-z])",
            replacement,
            normalized,
        )

    normalized = normalized.translate(_CHAR_TRANSLATION)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


@lru_cache(maxsize=1)
def _active_lexicon():
    return load_forbidden_lexicon()


@lru_cache(maxsize=1)
def load_profanity_terms() -> frozenset[str]:
    terms = {
        normalize_obfuscated_text(term)
        for term in _active_lexicon().words
        if str(term).strip()
    }
    return frozenset(term for term in terms if term)


@lru_cache(maxsize=1)
def load_forbidden_patterns() -> tuple[re.Pattern, ...]:
    patterns = []
    for expression in _active_lexicon().patterns:
        expression = str(expression).strip()
        if expression:
            patterns.append(re.compile(expression, re.IGNORECASE))
    return tuple(patterns)


def clear_profanity_cache() -> None:
    """
    Invalidate source and normalized caches.

    A future ForbiddenWord/ForbiddenPattern admin can call this after save/delete
    so moderation starts using changed database rules without process restart.
    """
    reset_forbidden_lexicon_source_cache()
    _active_lexicon.cache_clear()
    load_profanity_terms.cache_clear()
    load_forbidden_patterns.cache_clear()


def matches_profanity(text: str) -> bool:
    original = unicodedata.normalize("NFKC", str(text or "")).casefold()
    if any(pattern.search(original) for pattern in _ENGLISH_PATTERNS):
        return True

    normalized = normalize_obfuscated_text(text)
    if not normalized:
        return False

    if any(pattern.search(normalized) for pattern in load_forbidden_patterns()):
        return True

    words = set(_WORD_RE.findall(normalized))
    if words.intersection(load_profanity_terms()):
        return True

    return any(pattern.search(normalized) for pattern in _ROOT_PATTERNS)


__all__ = [
    "clear_profanity_cache",
    "load_forbidden_patterns",
    "load_profanity_terms",
    "matches_profanity",
    "normalize_obfuscated_text",
]

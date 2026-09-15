import re
import unicodedata
from functools import lru_cache
from pathlib import Path


_DATA_FILE = Path(__file__).with_name("profanity_ru.txt")

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
_MASK_BETWEEN_CHARS_RE = re.compile(r"(?<=[a-zа-яё0-9])[*._~`'\-]+(?=[a-zа-яё0-9])", re.IGNORECASE)
_SINGLE_LETTER_CHAIN_RE = re.compile(
    r"(?<![a-zа-яё0-9])(?:[a-zа-яё0-9](?:[\s._*~`'\-]+)){2,}[a-zа-яё0-9](?![a-zа-яё0-9])",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)

# Корневые шаблоны нужны для склонений и частичных маскировок, когда одна буква пропущена.
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
        normalized = re.sub(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", replacement, normalized)

    normalized = normalized.translate(_CHAR_TRANSLATION)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


@lru_cache(maxsize=1)
def load_profanity_terms() -> frozenset[str]:
    terms = set()
    with _DATA_FILE.open("r", encoding="utf-8") as source:
        for raw_line in source:
            line = raw_line.strip().casefold()
            if not line or line.startswith("#"):
                continue
            terms.add(normalize_obfuscated_text(line))
    return frozenset(terms)


def matches_profanity(text: str) -> bool:
    original = unicodedata.normalize("NFKC", str(text or "")).casefold()
    if any(pattern.search(original) for pattern in _ENGLISH_PATTERNS):
        return True

    normalized = normalize_obfuscated_text(text)
    if not normalized:
        return False

    words = set(_WORD_RE.findall(normalized))
    if words.intersection(load_profanity_terms()):
        return True

    return any(pattern.search(normalized) for pattern in _ROOT_PATTERNS)

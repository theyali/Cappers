from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from django.conf import settings
from django.utils.module_loading import import_string


DEFAULT_FORBIDDEN_LEXICON_SOURCE = (
    "cabinet.comments.data.forbidden_source.FileForbiddenLexiconSource"
)
DEFAULT_WORDS_FILE = Path(__file__).with_name("profanity_ru.txt")


@dataclass(frozen=True)
class ForbiddenLexicon:
    """
    Source-neutral moderation dictionary.

    `words` are normalized by the profanity service before matching.
    `patterns` are optional regular expressions applied to normalized text.
    A future ORM source can populate these from ForbiddenWord/ForbiddenPattern.
    """

    words: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()


class ForbiddenLexiconSource(Protocol):
    def load(self) -> ForbiddenLexicon:
        ...


class FileForbiddenLexiconSource:
    """Current source: the repository profanity dictionary file."""

    def __init__(self, words_file: Path | str = DEFAULT_WORDS_FILE):
        self.words_file = Path(words_file)

    def load(self) -> ForbiddenLexicon:
        words = []
        with self.words_file.open("r", encoding="utf-8") as source:
            for raw_line in source:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                words.append(line)
        return ForbiddenLexicon(words=tuple(words))


@lru_cache(maxsize=1)
def get_forbidden_lexicon_source() -> ForbiddenLexiconSource:
    """
    Resolve the active source once per process.

    Later the project can add an ORM-backed implementation using
    ForbiddenWord/ForbiddenPattern and switch it through
    COMMENT_FORBIDDEN_LEXICON_SOURCE without changing moderation.py.
    """
    source_path = getattr(
        settings,
        "COMMENT_FORBIDDEN_LEXICON_SOURCE",
        DEFAULT_FORBIDDEN_LEXICON_SOURCE,
    )
    source_class = import_string(source_path)
    return source_class()


def load_forbidden_lexicon() -> ForbiddenLexicon:
    return get_forbidden_lexicon_source().load()


def reset_forbidden_lexicon_source_cache() -> None:
    get_forbidden_lexicon_source.cache_clear()


__all__ = [
    "DEFAULT_FORBIDDEN_LEXICON_SOURCE",
    "DEFAULT_WORDS_FILE",
    "FileForbiddenLexiconSource",
    "ForbiddenLexicon",
    "ForbiddenLexiconSource",
    "get_forbidden_lexicon_source",
    "load_forbidden_lexicon",
    "reset_forbidden_lexicon_source_cache",
]

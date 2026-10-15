from dataclasses import dataclass
from enum import Enum, auto


class LinkKind(Enum):
    NOVEL = auto()
    CHAPTER = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class NovelSummary:
    title: str
    url: str


@dataclass(frozen=True)
class ChapterLink:
    title: str
    url: str


@dataclass(frozen=True)
class NovelDetails:
    title: str
    url: str
    status: str
    description: str
    chapters: list[ChapterLink]
    """Readable chapters, oldest first."""
    locked_chapter_count: int
    """Chapters the site lists but only shows to paying supporters."""


@dataclass(frozen=True)
class Chapter:
    title: str
    url: str
    novel_url: str | None
    paragraphs: list[str]
    previous_url: str | None
    next_url: str | None

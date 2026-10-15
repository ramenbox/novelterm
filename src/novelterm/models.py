from dataclasses import dataclass
from enum import Enum, auto


class LinkKind(Enum):
    NOVEL = auto()
    CHAPTER = auto()
    UNKNOWN = auto()


class Listing(Enum):
    """A list of novels on a site."""

    NOVEL_LIST = auto()
    SEARCH = auto()


@dataclass(frozen=True)
class NovelSummary:
    title: str
    url: str


@dataclass(frozen=True)
class NovelListPage:
    """One page of a novel list or of search results."""

    url: str
    novels: list[NovelSummary]
    next_page_url: str | None
    """The next page of the same list. None on the last page."""


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
    image_count: int = 0
    """Images in the chapter body. novelterm shows text only, so it only reports them."""

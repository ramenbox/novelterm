"""Read and check source files (.toml) that describe how to read one site."""

import re
import tomllib
from dataclasses import dataclass
from enum import Enum
from typing import Any

from novelterm.css_selectors import Selector, SelectorError, parse_selector

SUPPORTED_FORMAT_VERSION = 1
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
VERSION_PATTERN = re.compile(r"^\d+(\.\d+)*$")
SEARCH_QUERY_PLACEHOLDER = "{query}"


class SourceFileError(ValueError):
    pass


class ChapterOrder(Enum):
    OLDEST_FIRST = "oldest_first"
    NEWEST_FIRST = "newest_first"


class DescriptionText(Enum):
    ALL = "all"
    """All text inside the element."""
    OWN = "own"
    """Only text placed directly in the element, without child elements."""


@dataclass(frozen=True)
class UrlRules:
    novel_pattern: re.Pattern[str]
    chapter_pattern: re.Pattern[str]


@dataclass(frozen=True)
class NovelListRules:
    page: str
    links: Selector


@dataclass(frozen=True)
class NovelRules:
    title: Selector
    status: Selector | None
    description: Selector | None
    description_text: DescriptionText
    chapters: Selector
    locked_chapters: Selector | None
    chapter_order: ChapterOrder


@dataclass(frozen=True)
class ChapterRules:
    title: Selector
    content: Selector
    novel_link: Selector | None
    previous: Selector | None
    next: Selector | None


@dataclass(frozen=True)
class SearchRules:
    url_template: str
    """Search page URL with the placeholder {query}. novelterm puts in the URL-encoded search text."""
    results: Selector
    """Links to novel pages on the search page."""


@dataclass(frozen=True)
class SourceDefinition:
    identifier: str
    name: str
    version: str
    description: str
    home_url: str
    hosts: tuple[str, ...]
    urls: UrlRules
    novel_list: NovelListRules
    novel: NovelRules
    chapter: ChapterRules
    search: SearchRules | None


class TableReader:
    """Reads typed values from one TOML table and names the full key in errors."""

    def __init__(self, table: dict[str, Any], prefix: str) -> None:
        self.table = table
        self.prefix = prefix

    def key_name(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def required_text(self, key: str) -> str:
        value = self.table.get(key)
        match value:
            case str() if value.strip():
                return value.strip()
            case None:
                raise SourceFileError(f"'{self.key_name(key)}' is missing")
            case _:
                raise SourceFileError(f"'{self.key_name(key)}' must be a non-empty text")

    def optional_text(self, key: str) -> str | None:
        match self.table.get(key):
            case None:
                return None
            case _:
                return self.required_text(key)

    def required_selector(self, key: str) -> Selector:
        return self.as_selector(key, self.required_text(key))

    def optional_selector(self, key: str) -> Selector | None:
        text = self.optional_text(key)
        return self.as_selector(key, text) if text is not None else None

    def as_selector(self, key: str, text: str) -> Selector:
        try:
            return parse_selector(text)
        except SelectorError as error:
            raise SourceFileError(f"'{self.key_name(key)}': {error}") from error

    def pattern(self, key: str) -> re.Pattern[str]:
        text = self.required_text(key)
        try:
            return re.compile(text)
        except re.error as error:
            raise SourceFileError(f"'{self.key_name(key)}' is not a valid regular expression: {error}") from error

    def choice[ChoiceType: Enum](self, key: str, choices: type[ChoiceType], default: ChoiceType) -> ChoiceType:
        text = self.optional_text(key)
        if text is None:
            return default
        try:
            return choices(text)
        except ValueError as error:
            allowed = ", ".join(f"'{choice.value}'" for choice in choices)
            raise SourceFileError(f"'{self.key_name(key)}' must be one of {allowed}") from error

    def text_list(self, key: str) -> tuple[str, ...]:
        value = self.table.get(key)
        match value:
            case [*items] if items and all(isinstance(item, str) and item for item in items):
                return tuple(items)
            case None:
                raise SourceFileError(f"'{self.key_name(key)}' is missing")
            case _:
                raise SourceFileError(f"'{self.key_name(key)}' must be a list of texts")

    def subtable(self, key: str) -> "TableReader":
        match self.optional_subtable(key):
            case TableReader() as reader:
                return reader
            case None:
                raise SourceFileError(f"table [{self.key_name(key)}] is missing")

    def optional_subtable(self, key: str) -> "TableReader | None":
        value = self.table.get(key)
        match value:
            case dict():
                return TableReader(value, f"{self.prefix}{key}.")
            case None:
                return None
            case _:
                raise SourceFileError(f"'{self.key_name(key)}' must be a table")


def parse_source_definition(content: str) -> SourceDefinition:
    try:
        document = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise SourceFileError(f"not valid TOML: {error}") from error

    root = TableReader(document, "")
    format_version = document.get("format_version")
    if format_version != SUPPORTED_FORMAT_VERSION:
        raise SourceFileError(
            f"'format_version' is {format_version!r}; this novelterm reads format_version = {SUPPORTED_FORMAT_VERSION}"
        )
    identifier = root.required_text("identifier")
    if not IDENTIFIER_PATTERN.match(identifier):
        raise SourceFileError("'identifier' may only use a-z, 0-9, '-' and '_'")
    version = root.required_text("version")
    if not VERSION_PATTERN.match(version):
        raise SourceFileError("'version' must look like 1.0.0")

    urls = root.subtable("urls")
    novel_list = root.subtable("novel_list")
    novel = root.subtable("novel")
    chapter = root.subtable("chapter")
    return SourceDefinition(
        identifier=identifier,
        name=root.required_text("name"),
        version=version,
        description=root.optional_text("description") or "",
        home_url=root.required_text("home_url"),
        hosts=root.text_list("hosts"),
        urls=UrlRules(
            novel_pattern=urls.pattern("novel_pattern"),
            chapter_pattern=urls.pattern("chapter_pattern"),
        ),
        novel_list=NovelListRules(
            page=novel_list.required_text("page"),
            links=novel_list.required_selector("links"),
        ),
        novel=NovelRules(
            title=novel.required_selector("title"),
            status=novel.optional_selector("status"),
            description=novel.optional_selector("description"),
            description_text=novel.choice("description_text", DescriptionText, DescriptionText.ALL),
            chapters=novel.required_selector("chapters"),
            locked_chapters=novel.optional_selector("locked_chapters"),
            chapter_order=novel.choice("chapter_order", ChapterOrder, ChapterOrder.OLDEST_FIRST),
        ),
        chapter=ChapterRules(
            title=chapter.required_selector("title"),
            content=chapter.required_selector("content"),
            novel_link=chapter.optional_selector("novel_link"),
            previous=chapter.optional_selector("previous"),
            next=chapter.optional_selector("next"),
        ),
        search=search_rules(root.optional_subtable("search")),
    )


def search_rules(search: TableReader | None) -> SearchRules | None:
    if search is None:
        return None
    url_template = search.required_text("url")
    if url_template.count(SEARCH_QUERY_PLACEHOLDER) != 1:
        raise SourceFileError(f"'{search.key_name('url')}' must contain {SEARCH_QUERY_PLACEHOLDER} exactly once")
    return SearchRules(url_template=url_template, results=search.required_selector("results"))


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))

"""Read and check source files (.toml) that describe how to read one site."""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from novelterm.css_selectors import Selector, SelectorError, parse_selector
from novelterm.network import RequestMethod

SUPPORTED_FORMAT_VERSIONS = (1, 2)
TEMPLATE_FORMAT_VERSION = 2
"""Source files that use a template, and template files, need this format_version."""
TEMPLATE_KIND = "template"
TEMPLATE_TABLES = ("urls", "novel_list", "novel", "chapter", "search")
"""The tables that a template can set."""
TEMPLATE_HEADER_KEYS = frozenset({"format_version", "kind", "identifier", "name", "version", "description"})
HOME_URL_PLACEHOLDER = "{home_url}"
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
VERSION_PATTERN = re.compile(r"^\d+(\.\d+)*$")
SEARCH_QUERY_PLACEHOLDER = "{query}"
NOVEL_URL_PLACEHOLDER = "{novel_url}"


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
    next_page: Selector | None
    """Link to the next page of the list. novelterm loads it only when the reader asks for more."""


@dataclass(frozen=True)
class LabeledField:
    """A value found by its label, for pages that show rows such as "Status: Ongoing".

    novelterm checks each element that matches item. The first item whose label
    text equals label_text gives the value. The comparison ignores case, extra
    spaces and a trailing ":".
    """

    item: Selector
    label: Selector
    label_text: str
    value: Selector


@dataclass(frozen=True)
class ChapterListRequest:
    """A second request that returns the chapter list, for sites that do not put it on the novel page."""

    url_template: str
    """URL with the placeholder {novel_url}. novelterm puts in the novel page URL as it was opened."""
    method: RequestMethod


type FieldRule = Selector | LabeledField
"""A selector for the element, or a value found by its label."""


@dataclass(frozen=True)
class NovelRules:
    title: Selector
    status: FieldRule | None
    description: Selector | None
    description_text: DescriptionText
    chapters: Selector
    locked_chapters: Selector | None
    chapter_order: ChapterOrder
    chapter_list: ChapterListRequest | None
    """When set, chapters and locked_chapters read the response of this request instead of the novel page."""


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
    next_page: Selector | None
    """Link to the next page of results."""


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
    template: str | None
    """The identifier of the template the source file uses."""


@dataclass(frozen=True)
class SourceTemplate:
    """Shared rules for sites that use the same site software. A source file names it with template = "..."."""

    identifier: str
    name: str
    version: str
    description: str
    tables: dict[str, dict[str, Any]]
    """The template's tables, by name. Only names from TEMPLATE_TABLES."""


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

    def optional_field(self, key: str) -> FieldRule | None:
        """A field given as a selector text, or as a table with item, label, label_text and value."""
        match self.table.get(key):
            case None:
                return None
            case str():
                return self.required_selector(key)
            case dict():
                table = self.subtable(key)
                return LabeledField(
                    item=table.required_selector("item"),
                    label=table.required_selector("label"),
                    label_text=table.required_text("label_text"),
                    value=table.required_selector("value"),
                )
            case _:
                raise SourceFileError(f"'{self.key_name(key)}' must be a selector text or a table")

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


def load_toml(content: str) -> dict[str, Any]:
    try:
        return tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise SourceFileError(f"not valid TOML: {error}") from error


def check_header(root: TableReader, allowed_versions: tuple[int, ...]) -> tuple[int, str, str]:
    """Check format_version, identifier and version. Returns them."""
    format_version = root.table.get("format_version")
    match format_version:
        case int() if format_version in allowed_versions:
            pass
        case _:
            allowed = " or ".join(str(version) for version in allowed_versions)
            raise SourceFileError(f"'format_version' is {format_version!r}; this novelterm reads format_version = {allowed}")
    identifier = root.required_text("identifier")
    if not IDENTIFIER_PATTERN.match(identifier):
        raise SourceFileError("'identifier' may only use a-z, 0-9, '-' and '_'")
    version = root.required_text("version")
    if not VERSION_PATTERN.match(version):
        raise SourceFileError("'version' must look like 1.0.0")
    return format_version, identifier, version


def template_name(content: str) -> str | None:
    """The template a source file names, without checking the rest of the file."""
    match load_toml(content).get("template"):
        case str(name):
            return name
        case _:
            return None


def parse_template(content: str) -> SourceTemplate:
    document = load_toml(content)
    root = TableReader(document, "")
    _, identifier, version = check_header(root, (TEMPLATE_FORMAT_VERSION,))
    if document.get("kind") != TEMPLATE_KIND:
        raise SourceFileError(f"'kind' must be \"{TEMPLATE_KIND}\" in a template file")
    unknown_keys = sorted(set(document) - TEMPLATE_HEADER_KEYS - set(TEMPLATE_TABLES))
    if unknown_keys:
        raise SourceFileError(
            f"a template can only set the tables {', '.join(TEMPLATE_TABLES)}; remove {', '.join(unknown_keys)}"
        )
    tables: dict[str, dict[str, Any]] = {}
    for table_name in TEMPLATE_TABLES:
        match document.get(table_name):
            case None:
                pass
            case dict() as table:
                tables[table_name] = table
            case _:
                raise SourceFileError(f"'{table_name}' must be a table")
    return SourceTemplate(
        identifier=identifier,
        name=root.required_text("name"),
        version=version,
        description=root.optional_text("description") or "",
        tables=tables,
    )


def apply_template(document: dict[str, Any], template: SourceTemplate) -> dict[str, Any]:
    """The source file document with the template's tables filled in.

    A key in the source file wins over the same key in the template. {home_url} in
    the template's texts becomes the source's home_url without a trailing /.
    """
    home_url = TableReader(document, "").required_text("home_url").rstrip("/")
    merged = dict(document)
    for table_name, template_table in template.tables.items():
        filled = with_home_url(template_table, home_url)
        match document.get(table_name):
            case None:
                merged[table_name] = filled
            case dict() as source_table:
                merged[table_name] = {**filled, **source_table}
            case _:
                raise SourceFileError(f"'{table_name}' must be a table")
    return merged


def with_home_url(value: Any, home_url: str) -> Any:
    match value:
        case str():
            return value.replace(HOME_URL_PLACEHOLDER, home_url)
        case dict():
            return {key: with_home_url(item, home_url) for key, item in value.items()}
        case list():
            return [with_home_url(item, home_url) for item in value]
        case _:
            return value


def parse_source_definition(content: str, templates: Mapping[str, SourceTemplate] | None = None) -> SourceDefinition:
    """Read a source file. templates are the available templates by identifier."""
    document = load_toml(content)
    format_version, identifier, version = check_header(TableReader(document, ""), SUPPORTED_FORMAT_VERSIONS)
    match (document.get("template"), format_version):
        case (None, _):
            template = None
        case (str(), 1):
            raise SourceFileError(f"'template' needs format_version = {TEMPLATE_FORMAT_VERSION}")
        case (str(name), _):
            match (templates or {}).get(name):
                case None:
                    raise SourceFileError(f"the template '{name}' is not installed")
                case SourceTemplate() as found:
                    template = found
                    document = apply_template(document, found)
        case _:
            raise SourceFileError("'template' must be a text")

    root = TableReader(document, "")

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
            next_page=novel_list.optional_selector("next_page"),
        ),
        novel=NovelRules(
            title=novel.required_selector("title"),
            status=novel.optional_field("status"),
            description=novel.optional_selector("description"),
            description_text=novel.choice("description_text", DescriptionText, DescriptionText.ALL),
            chapters=novel.required_selector("chapters"),
            locked_chapters=novel.optional_selector("locked_chapters"),
            chapter_order=novel.choice("chapter_order", ChapterOrder, ChapterOrder.OLDEST_FIRST),
            chapter_list=chapter_list_request(novel.optional_subtable("chapter_list")),
        ),
        chapter=ChapterRules(
            title=chapter.required_selector("title"),
            content=chapter.required_selector("content"),
            novel_link=chapter.optional_selector("novel_link"),
            previous=chapter.optional_selector("previous"),
            next=chapter.optional_selector("next"),
        ),
        search=search_rules(root.optional_subtable("search")),
        template=template.identifier if template else None,
    )


def chapter_list_request(table: TableReader | None) -> ChapterListRequest | None:
    if table is None:
        return None
    url_template = table.required_text("url")
    if url_template.count(NOVEL_URL_PLACEHOLDER) != 1:
        raise SourceFileError(f"'{table.key_name('url')}' must contain {NOVEL_URL_PLACEHOLDER} exactly once")
    return ChapterListRequest(url_template=url_template, method=table.choice("method", RequestMethod, RequestMethod.GET))


def search_rules(search: TableReader | None) -> SearchRules | None:
    if search is None:
        return None
    url_template = search.required_text("url")
    if url_template.count(SEARCH_QUERY_PLACEHOLDER) != 1:
        raise SourceFileError(f"'{search.key_name('url')}' must contain {SEARCH_QUERY_PLACEHOLDER} exactly once")
    return SearchRules(
        url_template=url_template,
        results=search.required_selector("results"),
        next_page=search.optional_selector("next_page"),
    )


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))

"""The check-source command: run a source file against one page and print what it finds.

The output shows counts, titles and URLs only. It never prints chapter text.
"""

import argparse
import sys
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from novelterm.css_selectors import Selector
from novelterm.html_tree import Element, fetch_document, parse_html
from novelterm.models import LinkKind, Listing
from novelterm.network import FetchError, RequestMethod
from novelterm.sources.definition import FieldRule, LabeledField, SourceFileError
from novelterm.sources.registry import load_source_file
from novelterm.sources.toml_source import ChapterListPage, TomlSource, label_key

TITLE_SAMPLE_SIZE = 3


class PageKind(Enum):
    NOVEL_LIST = auto()
    SEARCH = auto()
    NOVEL = auto()
    CHAPTER = auto()


@dataclass(frozen=True)
class SelectorRule:
    key: str
    selector: FieldRule | None
    required: bool
    reads_chapter_list: bool = False
    """The selector reads the chapter list response instead of the page."""


@dataclass
class Report:
    lines: list[str]
    problems: list[str]

    def add(self, label: str, value: object) -> None:
        self.lines.append(f"  {label:<22} {value}")


def page_kind(source: TomlSource, url: str, search_query: str | None, is_novel_list: bool) -> PageKind | None:
    match (search_query, source.link_kind(url)):
        case (str(), _):
            return PageKind.SEARCH
        case (None, _) if is_novel_list or url == source.definition.novel_list.page:
            return PageKind.NOVEL_LIST
        case (None, LinkKind.NOVEL):
            return PageKind.NOVEL
        case (None, LinkKind.CHAPTER):
            return PageKind.CHAPTER
        case (None, LinkKind.UNKNOWN):
            return None


def selector_rules(source: TomlSource, kind: PageKind) -> list[SelectorRule]:
    definition = source.definition
    match kind:
        case PageKind.NOVEL_LIST:
            return [
                SelectorRule("novel_list.links", definition.novel_list.links, True),
                SelectorRule("novel_list.next_page", definition.novel_list.next_page, False),
            ]
        case PageKind.SEARCH:
            search = definition.search
            return [
                SelectorRule("search.results", search.results if search else None, True),
                SelectorRule("search.next_page", search.next_page if search else None, False),
            ]
        case PageKind.NOVEL:
            rules = definition.novel
            return [
                SelectorRule("novel.title", rules.title, True),
                SelectorRule("novel.status", rules.status, False),
                SelectorRule("novel.description", rules.description, False),
                SelectorRule("novel.chapters", rules.chapters, True, reads_chapter_list=True),
                SelectorRule("novel.locked_chapters", rules.locked_chapters, False, reads_chapter_list=True),
            ]
        case PageKind.CHAPTER:
            rules = definition.chapter
            return [
                SelectorRule("chapter.title", rules.title, True),
                SelectorRule("chapter.content", rules.content, True),
                SelectorRule("chapter.novel_link", rules.novel_link, False),
                SelectorRule("chapter.previous", rules.previous, False),
                SelectorRule("chapter.next", rules.next, False),
            ]


def check_selectors(rules: list[SelectorRule], document: Element, chapter_list: ChapterListPage, report: Report) -> None:
    report.lines.append("Selectors:")
    for rule in rules:
        checked_document = chapter_list.document if rule.reads_chapter_list else document
        match rule.selector:
            case None:
                report.add(rule.key, "not set")
            case Selector() as selector:
                count = len(selector.select(checked_document))
                report.add(rule.key, f'"{selector.text}" -> {match_label(count)}')
                if count == 0 and rule.required:
                    report.problems.append(f"{rule.key}: no element matches \"{selector.text}\"")
            case LabeledField() as field:
                items = field.item.select(checked_document)
                labels = [label for item in items if (label := field.label.select_first(item)) is not None]
                found = any(label_key(label.text()) == label_key(field.label_text) for label in labels)
                report.add(
                    rule.key,
                    f'item "{field.item.text}" -> {match_label(len(items))}, '
                    f'label "{field.label_text}" {"found" if found else "not found"}',
                )
                if not found and rule.required:
                    report.problems.append(f'{rule.key}: no item has the label "{field.label_text}"')


def match_label(count: int) -> str:
    return f"{count} {'match' if count == 1 else 'matches'}"


def sample_titles(titles: list[str]) -> str:
    sample = titles[:TITLE_SAMPLE_SIZE]
    more = f", ... ({len(titles) - len(sample)} more)" if len(titles) > len(sample) else ""
    return ", ".join(f'"{title}"' for title in sample) + more


def check_novel_list_page(source: TomlSource, listing: Listing, url: str, document: Element, report: Report) -> None:
    page = source.parse_novel_list_page(listing, url, document)
    report.add("novels", len(page.novels))
    report.add("titles", sample_titles([novel.title for novel in page.novels]) or "-")
    report.add("next page", page.next_page_url or "-")
    if not page.novels:
        report.problems.append("no links that match urls.novel_pattern")


def check_results(
    source: TomlSource, kind: PageKind, url: str, document: Element, chapter_list: ChapterListPage, report: Report
) -> None:
    report.lines.append("Result:")
    match (kind, source.definition.search):
        case (PageKind.NOVEL_LIST, _):
            check_novel_list_page(source, Listing.NOVEL_LIST, url, document, report)
        case (PageKind.SEARCH, None):
            report.problems.append("the source file has no [search] table")
        case (PageKind.SEARCH, _):
            check_novel_list_page(source, Listing.SEARCH, url, document, report)
        case (PageKind.NOVEL, _):
            novel = source.parse_novel(url, document, chapter_list)
            report.add("title", novel.title)
            report.add("status", novel.status or "-")
            report.add("description", f"{len(novel.description)} characters")
            report.add("chapters", len(novel.chapters))
            report.add("first chapter", novel.chapters[0].title if novel.chapters else "-")
            report.add("last chapter", novel.chapters[-1].title if novel.chapters else "-")
            report.add("locked chapters", novel.locked_chapter_count)
            if not novel.chapters:
                report.problems.append("no chapter links that match urls.chapter_pattern")
        case (PageKind.CHAPTER, _):
            chapter = source.parse_chapter(url, document)
            word_count = sum(len(paragraph.split()) for paragraph in chapter.paragraphs)
            report.add("title", chapter.title)
            report.add("paragraphs", len(chapter.paragraphs))
            report.add("words", word_count)
            report.add("novel link", chapter.novel_url or "-")
            report.add("previous chapter", chapter.previous_url or "-")
            report.add("next chapter", chapter.next_url or "-")
            if not chapter.paragraphs:
                report.problems.append("the chapter has no text")


def page_url(source: TomlSource, search_query: str | None, given_url: str | None) -> str:
    match (search_query, given_url):
        case (str(), _) if source.definition.search is None:
            sys.exit("error: the source file has no [search] table")
        case (str(query), _):
            return source.search_url(query)
        case (None, str(url)):
            return url
        case (None, None):
            return source.definition.novel_list.page


def load_page(url: str, html_file: Path | None, method: RequestMethod = RequestMethod.GET) -> Element:
    match html_file:
        case Path():
            return parse_html(html_file.read_text(encoding="utf-8", errors="replace"))
        case None:
            try:
                return fetch_document(url, method)
            except FetchError as error:
                sys.exit(f"error: {error.explanation()}")


def chapter_list_page(
    source: TomlSource, kind: PageKind, url: str, document: Element, chapter_list_html: Path | None
) -> ChapterListPage:
    """The page that the chapter selectors read: the chapter list response, or else the page itself."""
    match (kind, source.definition.novel.chapter_list):
        case (PageKind.NOVEL, None) | (PageKind.NOVEL_LIST | PageKind.SEARCH | PageKind.CHAPTER, _):
            return ChapterListPage(url, document)
        case (PageKind.NOVEL, request):
            chapter_list_url = source.chapter_list_url(url)
            print(f"Chapter list: {request.method.value.upper()} {chapter_list_url}")
            return ChapterListPage(chapter_list_url, load_page(chapter_list_url, chapter_list_html, request.method))


def check_source_command(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="novelterm check-source",
        description=(
            "Check a source file against one page. Without URL, the novel list page is checked. "
            "Prints counts, titles and URLs, never chapter text."
        ),
    )
    parser.add_argument("file", type=Path, help="the .toml source file")
    parser.add_argument("url", nargs="?", help="a novel page or chapter page URL")
    parser.add_argument("--search", metavar="TEXT", help="check the [search] table with this search text")
    parser.add_argument("--novel-list", action="store_true", help="URL is a later page of the novel list")
    parser.add_argument("--html", type=Path, metavar="FILE", help="read the page from a saved HTML file instead of the site")
    parser.add_argument(
        "--chapter-list-html",
        type=Path,
        metavar="FILE",
        help="read the [novel.chapter_list] response from a saved file instead of the site",
    )
    options = parser.parse_args(arguments)

    try:
        source = load_source_file(options.file)
    except SourceFileError as error:
        sys.exit(f"error: {options.file}: {error}")
    print(f"Source file OK: {source.identifier} {source.definition.version} ({source.name})")

    search_query: str | None = options.search
    given_url: str | None = options.url
    html_file: Path | None = options.html
    url = page_url(source, search_query, given_url)
    kind = page_kind(source, url, search_query, options.novel_list)
    if kind is None:
        sys.exit(
            f"error: {url} matches neither urls.novel_pattern nor urls.chapter_pattern, and it is not the novel list page. "
            "Add --novel-list for a later page of the novel list."
        )
    print(f"Page: {url} ({kind.name.lower().replace('_', ' ')})")
    document = load_page(url, html_file)
    chapter_list = chapter_list_page(source, kind, url, document, options.chapter_list_html)

    report = Report(lines=[], problems=[])
    check_selectors(selector_rules(source, kind), document, chapter_list, report)
    check_results(source, kind, url, document, chapter_list, report)
    print("\n".join(report.lines))
    match report.problems:
        case []:
            print("No problems found.")
        case problems:
            print("Problems:")
            print("\n".join(f"  {problem}" for problem in problems))
            sys.exit(1)

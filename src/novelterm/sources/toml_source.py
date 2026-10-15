"""A Source that reads a site with the rules from a source file."""

from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

from novelterm.css_selectors import Selector
from novelterm.html_tree import Element, clean_text, fetch_document
from novelterm.models import Chapter, ChapterLink, LinkKind, Listing, NovelDetails, NovelListPage, NovelSummary
from novelterm.sources.definition import SEARCH_QUERY_PLACEHOLDER, ChapterOrder, DescriptionText, SourceDefinition

CONTENT_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li"})
STATUS_LABEL_PREFIX = "status:"


class TomlSource:
    def __init__(self, definition: SourceDefinition, file_path: Path) -> None:
        self.definition = definition
        self.file_path = file_path
        self.identifier = definition.identifier
        self.name = definition.name
        self.home_url = definition.home_url
        self.description = definition.description

    def handles(self, url: str) -> bool:
        return urlparse(url).hostname in self.definition.hosts

    def link_kind(self, url: str) -> LinkKind:
        path = urlparse(url).path
        match path:
            case _ if not self.handles(url):
                return LinkKind.UNKNOWN
            case _ if self.definition.urls.chapter_pattern.search(path):
                return LinkKind.CHAPTER
            case _ if self.definition.urls.novel_pattern.search(path):
                return LinkKind.NOVEL
            case _:
                return LinkKind.UNKNOWN

    @property
    def supports_search(self) -> bool:
        return self.definition.search is not None

    def list_novels(self) -> NovelListPage:
        return self.next_novel_page(Listing.NOVEL_LIST, self.definition.novel_list.page)

    def search(self, query: str) -> NovelListPage:
        return self.next_novel_page(Listing.SEARCH, self.search_url(query))

    def next_novel_page(self, listing: Listing, page_url: str) -> NovelListPage:
        return self.parse_novel_list_page(listing, page_url, fetch_document(page_url))

    def search_url(self, query: str) -> str:
        match self.definition.search:
            case None:
                raise ValueError(f"source '{self.identifier}' has no [search] table")
            case search_rules:
                return search_rules.url_template.replace(SEARCH_QUERY_PLACEHOLDER, quote_plus(query))

    def get_novel(self, url: str) -> NovelDetails:
        return self.parse_novel(url, fetch_document(url))

    def get_chapter(self, url: str) -> Chapter:
        return self.parse_chapter(url, fetch_document(url))

    def listing_selectors(self, listing: Listing) -> tuple[Selector, Selector | None]:
        """The selectors for (novel links, next page link) of a listing."""
        match (listing, self.definition.search):
            case (Listing.NOVEL_LIST, _):
                return self.definition.novel_list.links, self.definition.novel_list.next_page
            case (Listing.SEARCH, None):
                raise ValueError(f"source '{self.identifier}' has no [search] table")
            case (Listing.SEARCH, search_rules):
                return search_rules.results, search_rules.next_page

    def parse_novel_list_page(self, listing: Listing, page_url: str, document: Element) -> NovelListPage:
        links, next_page = self.listing_selectors(listing)
        return NovelListPage(
            url=page_url,
            novels=self.novel_links(page_url, links.select(document)),
            next_page_url=self.next_page_url(page_url, first(next_page, document)),
        )

    def next_page_url(self, page_url: str, link: Element | None) -> str | None:
        """The URL of a next page link. None when it leads to another site or to the same page."""
        url = absolute_link(page_url, link) if link else None
        return url if url and url != page_url and self.handles(url) else None

    def novel_links(self, page_url: str, links: list[Element]) -> list[NovelSummary]:
        novels: dict[str, NovelSummary] = {}
        for link in links:
            url = absolute_link(page_url, link)
            title = clean_text(link.text())
            if url and title and url not in novels and self.link_kind(url) == LinkKind.NOVEL:
                novels[url] = NovelSummary(title=title, url=url)
        return list(novels.values())

    def parse_novel(self, url: str, document: Element) -> NovelDetails:
        rules = self.definition.novel
        status = text_of(first(rules.status, document))
        if status.lower().startswith(STATUS_LABEL_PREFIX):
            status = status[len(STATUS_LABEL_PREFIX) :].strip()
        description_element = first(rules.description, document)
        match (description_element, rules.description_text):
            case (None, _):
                description = ""
            case (Element(), DescriptionText.OWN):
                description = clean_text(description_element.direct_text())
            case (Element(), DescriptionText.ALL):
                description = clean_text(description_element.text())

        chapters = self.chapter_links(url, rules.chapters.select(document))
        match rules.chapter_order:
            case ChapterOrder.NEWEST_FIRST:
                chapters.reverse()
            case ChapterOrder.OLDEST_FIRST:
                pass
        locked_links = rules.locked_chapters.select(document) if rules.locked_chapters else []

        return NovelDetails(
            title=text_of(rules.title.select_first(document)) or url,
            url=url,
            status=status,
            description=description,
            chapters=chapters,
            locked_chapter_count=len(self.chapter_links(url, locked_links)),
        )

    def parse_chapter(self, url: str, document: Element) -> Chapter:
        rules = self.definition.chapter
        novel_link = first(rules.novel_link, document)
        return Chapter(
            title=text_of(rules.title.select_first(document)) or url,
            url=url,
            novel_url=absolute_link(url, novel_link) if novel_link else None,
            paragraphs=paragraphs_of(rules.content.select_first(document)),
            previous_url=self.chapter_link_url(url, first(rules.previous, document)),
            next_url=self.chapter_link_url(url, first(rules.next, document)),
        )

    def chapter_links(self, page_url: str, links: list[Element]) -> list[ChapterLink]:
        chapters: dict[str, ChapterLink] = {}
        for link in links:
            url = absolute_link(page_url, link)
            if url and url not in chapters and self.link_kind(url) == LinkKind.CHAPTER:
                chapters[url] = ChapterLink(title=clean_text(link.text()) or url, url=url)
        return list(chapters.values())

    def chapter_link_url(self, page_url: str, link: Element | None) -> str | None:
        url = absolute_link(page_url, link) if link else None
        return url if url and self.link_kind(url) == LinkKind.CHAPTER else None


def first(selector: Selector | None, document: Element) -> Element | None:
    return selector.select_first(document) if selector else None


def text_of(element: Element | None) -> str:
    return clean_text(element.text()) if element else ""


def absolute_link(page_url: str, link: Element) -> str | None:
    href = link.get("href")
    return urljoin(page_url, href) if href else None


def paragraphs_of(content: Element | None) -> list[str]:
    """Paragraph texts of the chapter body.

    Uses the block children (p, h2, ...) when the body has them. Otherwise uses
    the lines of the body text, for sites that separate paragraphs with <br>.
    """
    if content is None:
        return []
    blocks = [
        clean_text(child.text())
        for child in content.children
        if isinstance(child, Element) and child.tag in CONTENT_TAGS
    ]
    match [block for block in blocks if block]:
        case []:
            return [line for line in clean_text(content.text()).split("\n") if line]
        case paragraphs:
            return paragraphs

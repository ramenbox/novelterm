"""A small HTML element tree on top of html.parser, for site scrapers."""

import re
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) novelterm/0.1"
REQUEST_TIMEOUT_SECONDS = 30
VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)
SKIPPED_TEXT_TAGS = frozenset({"script", "style", "noscript"})
TAGS_THAT_CLOSE_PARAGRAPH = frozenset({"p", "div", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table"})


@dataclass(eq=False)
class Element:
    tag: str
    attributes: dict[str, str] = field(default_factory=dict)
    children: list["Element | str"] = field(default_factory=list)

    def classes(self) -> list[str]:
        return self.attributes.get("class", "").split()

    def get(self, attribute: str) -> str | None:
        return self.attributes.get(attribute)

    def descendants(self) -> Iterator["Element"]:
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.descendants()

    def find_all(self, tag: str | None = None, class_name: str | None = None) -> list["Element"]:
        return [
            element
            for element in self.descendants()
            if (tag is None or element.tag == tag)
            and (class_name is None or class_name in element.classes())
        ]

    def find(self, tag: str | None = None, class_name: str | None = None) -> "Element | None":
        return next(iter(self.find_all(tag, class_name)), None)

    def text(self) -> str:
        """Visible text. A <br> becomes a line break."""
        parts: list[str] = []
        for child in self.children:
            match child:
                case str():
                    parts.append(child)
                case Element(tag="br"):
                    parts.append("\n")
                case Element(tag=tag) if tag in SKIPPED_TEXT_TAGS:
                    pass
                case Element():
                    parts.append(child.text())
        return "".join(parts)

    def direct_text(self) -> str:
        """Text of this element only, without the text of child elements."""
        return "".join(child for child in self.children if isinstance(child, str))


def clean_text(text: str) -> str:
    """Collapse runs of spaces inside each line and remove empty edges."""
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack: list[Element] = [self.root]

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        if tag in TAGS_THAT_CLOSE_PARAGRAPH and self.stack[-1].tag == "p":
            self.stack.pop()
        element = Element(tag, {name: value or "" for name, value in attributes})
        self.stack[-1].children.append(element)
        if tag not in VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        element = Element(tag, {name: value or "" for name, value in attributes})
        self.stack[-1].children.append(element)

    def handle_endtag(self, tag: str) -> None:
        if not any(element.tag == tag for element in self.stack[1:]):
            return
        while len(self.stack) > 1:
            if self.stack.pop().tag == tag:
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_html(page: str) -> Element:
    builder = TreeBuilder()
    builder.feed(page)
    builder.close()
    return builder.root


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read()


def fetch_document(url: str) -> Element:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        page = response.read().decode(charset, errors="replace")
    return parse_html(page)

import unittest
from pathlib import Path
from unittest import mock

from novelterm.html_tree import parse_html
from novelterm.models import LinkKind
from novelterm.sources.definition import parse_source_definition
from novelterm.sources.toml_source import TomlSource

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sources" / "example-site.toml"

PAGES = {
    "https://example.org/": """
        <div class="novels">
          <a href="/novel/first"><img src="cover.png"></a>
          <a href="/novel/first">First Novel</a>
          <a href="/novel/second/">Second Novel</a>
          <a href="/about">About</a>
        </div>""",
    "https://example.org/novel/first": """
        <h1 class="title">First Novel</h1>
        <p class="status">Status: Ongoing</p>
        <div class="summary"><h2>Summary:</h2>A test summary.</div>
        <ul class="locked"><li><a href="/novel/first/chapter-4">Chapter 4</a></li></ul>
        <ul class="free">
          <li><a href="/novel/first/chapter-3">Chapter 3</a></li>
          <li><a href="/novel/first/chapter-2">Chapter 2</a></li>
          <li><a href="/novel/first/chapter-1">Chapter 1</a></li>
        </ul>""",
    "https://example.org/novel/first/chapter-2": """
        <h1 class="chapter-title">Chapter 2</h1>
        <a class="back" href="/novel/first">Back</a>
        <div class="text"><p>First   line.</p><p>Second<br>line.</p><div class="ad"></div><p></p></div>
        <div class="navigation">
          <a class="previous" href="/novel/first/chapter-1">Previous</a>
          <a class="next" href="/novel/first/chapter-3">Next</a>
        </div>""",
    "https://example.org/search?q=first+novel": """
        <ul class="results">
          <li><a href="/novel/first">First Novel</a></li>
          <li><a href="/novel/first/chapter-1">Chapter 1</a></li>
        </ul>""",
    "https://example.org/novel/first/chapter-3": """
        <h1 class="chapter-title">Chapter 3</h1>
        <div class="text">Line one<br>Line two</div>
        <div class="navigation"><a class="previous" href="/novel/first/chapter-2">Previous</a></div>""",
}


def fake_fetch_document(url: str):
    return parse_html(PAGES[url])


@mock.patch("novelterm.sources.toml_source.fetch_document", fake_fetch_document)
class TomlSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = TomlSource(parse_source_definition(FIXTURE.read_text(encoding="utf-8")), FIXTURE)

    def test_link_kind(self) -> None:
        self.assertEqual(self.source.link_kind("https://example.org/novel/first"), LinkKind.NOVEL)
        self.assertEqual(self.source.link_kind("https://example.org/novel/first/chapter-1"), LinkKind.CHAPTER)
        self.assertEqual(self.source.link_kind("https://example.org/about"), LinkKind.UNKNOWN)
        self.assertEqual(self.source.link_kind("https://other.org/novel/first"), LinkKind.UNKNOWN)

    def test_list_novels(self) -> None:
        novels = self.source.list_novels()
        self.assertEqual([novel.title for novel in novels], ["First Novel", "Second Novel"])
        self.assertEqual(novels[0].url, "https://example.org/novel/first")

    def test_search(self) -> None:
        self.assertTrue(self.source.supports_search)
        self.assertEqual(self.source.search_url("first novel"), "https://example.org/search?q=first+novel")
        results = self.source.search("first novel")
        self.assertEqual([(novel.title, novel.url) for novel in results], [("First Novel", "https://example.org/novel/first")])

    def test_get_novel(self) -> None:
        novel = self.source.get_novel("https://example.org/novel/first")
        self.assertEqual(novel.title, "First Novel")
        self.assertEqual(novel.status, "Ongoing")
        self.assertEqual(novel.description, "A test summary.")
        self.assertEqual([chapter.title for chapter in novel.chapters], ["Chapter 1", "Chapter 2", "Chapter 3"])
        self.assertEqual(novel.locked_chapter_count, 1)

    def test_get_chapter_with_paragraph_elements(self) -> None:
        chapter = self.source.get_chapter("https://example.org/novel/first/chapter-2")
        self.assertEqual(chapter.title, "Chapter 2")
        self.assertEqual(chapter.paragraphs, ["First line.", "Second\nline."])
        self.assertEqual(chapter.novel_url, "https://example.org/novel/first")
        self.assertEqual(chapter.previous_url, "https://example.org/novel/first/chapter-1")
        self.assertEqual(chapter.next_url, "https://example.org/novel/first/chapter-3")

    def test_get_chapter_with_line_breaks_only(self) -> None:
        chapter = self.source.get_chapter("https://example.org/novel/first/chapter-3")
        self.assertEqual(chapter.paragraphs, ["Line one", "Line two"])
        self.assertIsNone(chapter.next_url)
        self.assertIsNone(chapter.novel_url)


if __name__ == "__main__":
    unittest.main()

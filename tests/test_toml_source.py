import unittest
from pathlib import Path
from unittest import mock

from novelterm.html_tree import parse_html
from novelterm.models import LinkKind, Listing, NovelDetails
from novelterm.network import RequestMethod
from novelterm.sources.definition import SourceFileError, parse_source_definition
from novelterm.sources.toml_source import ChapterListPage, TomlSource

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sources" / "example-site.toml"

PAGES = {
    "https://example.org/": """
        <div class="novels">
          <a href="/novel/first"><img src="cover.png"></a>
          <a href="/novel/first">First Novel</a>
          <a href="/novel/second/">Second Novel</a>
          <a href="/about">About</a>
        </div>
        <a class="next-page" href="/?page=2">Next</a>""",
    "https://example.org/?page=2": """
        <div class="novels"><a href="/novel/second/">Second Novel</a><a href="/novel/third">Third Novel</a></div>
        <a class="next-page" href="/?page=2">Next</a>""",
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
        page = self.source.list_novels()
        self.assertEqual([novel.title for novel in page.novels], ["First Novel", "Second Novel"])
        self.assertEqual(page.novels[0].url, "https://example.org/novel/first")
        self.assertEqual(page.next_page_url, "https://example.org/?page=2")

    def test_next_page_link_to_the_same_page_ends_the_list(self) -> None:
        page = self.source.next_novel_page(Listing.NOVEL_LIST, "https://example.org/?page=2")
        self.assertEqual([novel.title for novel in page.novels], ["Second Novel", "Third Novel"])
        self.assertIsNone(page.next_page_url)

    def test_search(self) -> None:
        self.assertTrue(self.source.supports_search)
        self.assertEqual(self.source.search_url("first novel"), "https://example.org/search?q=first+novel")
        results = self.source.search("first novel")
        self.assertEqual([(novel.title, novel.url) for novel in results.novels], [("First Novel", "https://example.org/novel/first")])
        self.assertIsNone(results.next_page_url)

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


IMAGE_CHAPTER_PAGES = {
    "https://example.org/novel/first/chapter-5": """
        <h1 class="chapter-title">Chapter 5</h1>
        <div class="text"><p><img src="/one.png"></p><img src="/two.png"></div>""",
    "https://example.org/novel/first/chapter-6": """
        <h1 class="chapter-title">Chapter 6</h1>
        <div class="text"><p>Text.</p><img src="/one.png"></div>""",
}


class NovelLinkTests(unittest.TestCase):
    def test_first_link_to_a_novel_page_counts(self) -> None:
        content = FIXTURE.read_text(encoding="utf-8").replace('novel_link = "a.back"', 'novel_link = "ol.breadcrumb a"')
        source = TomlSource(parse_source_definition(content), FIXTURE)
        page = """<ol class="breadcrumb"><li><a href="/">Home</a></li><li><a href="/novel/first/">First</a></li></ol>
            <h1 class="chapter-title">Chapter 1</h1><div class="text"><p>Text.</p></div>"""
        chapter = source.parse_chapter("https://example.org/novel/first/chapter-1", parse_html(page))
        self.assertEqual(chapter.novel_url, "https://example.org/novel/first/")


class ChapterImageTests(unittest.TestCase):
    def test_images_are_counted(self) -> None:
        source = TomlSource(parse_source_definition(FIXTURE.read_text(encoding="utf-8")), FIXTURE)
        only_images = source.parse_chapter("https://example.org/novel/first/chapter-5", parse_html(IMAGE_CHAPTER_PAGES["https://example.org/novel/first/chapter-5"]))
        self.assertEqual((only_images.paragraphs, only_images.image_count), ([], 2))
        with_text = source.parse_chapter("https://example.org/novel/first/chapter-6", parse_html(IMAGE_CHAPTER_PAGES["https://example.org/novel/first/chapter-6"]))
        self.assertEqual((with_text.paragraphs, with_text.image_count), (["Text."], 1))


LABELED_STATUS = 'status = { item = "div.row", label = "span.label", label_text = "status", value = "span.value" }'

LABELED_PAGE = """
    <h1 class="title">Labeled</h1>
    <div class="row"><span class="label">Release</span><span class="value">2025</span></div>
    <div class="row"><span class="label"> STATUS: </span><span class="value">OnGoing</span></div>"""


def parse_page(source: TomlSource, url: str, page: str) -> NovelDetails:
    document = parse_html(page)
    return source.parse_novel(url, document, ChapterListPage(url, document))


class LabeledFieldTests(unittest.TestCase):
    def source_with_status(self, status_line: str) -> TomlSource:
        content = FIXTURE.read_text(encoding="utf-8").replace('status = "p.status"', status_line)
        return TomlSource(parse_source_definition(content), FIXTURE)

    def test_value_of_the_row_with_the_label(self) -> None:
        source = self.source_with_status(LABELED_STATUS)
        novel = parse_page(source, "https://example.org/novel/first", LABELED_PAGE)
        self.assertEqual(novel.status, "OnGoing")

    def test_no_matching_label_gives_no_status(self) -> None:
        source = self.source_with_status(LABELED_STATUS.replace('"status"', '"Author"'))
        novel = parse_page(source, "https://example.org/novel/first", LABELED_PAGE)
        self.assertEqual(novel.status, "")

    def test_missing_key_in_the_table_is_an_error(self) -> None:
        with self.assertRaisesRegex(SourceFileError, "novel.status.value"):
            self.source_with_status(LABELED_STATUS.replace(', value = "span.value"', ""))


CHAPTER_LIST_TABLE = """
[novel.chapter_list]
url = "{novel_url}ajax/chapters/"
method = "post"
"""

CHAPTER_LIST_PAGES = {
    ("https://example.org/novel/first/", RequestMethod.GET): '<h1 class="title">First Novel</h1><ul class="free"></ul>',
    ("https://example.org/novel/first/ajax/chapters/", RequestMethod.POST): """
        <ul class="locked"><li><a href="../../chapter-3">Chapter 3</a></li></ul>
        <ul class="free"><li><a href="../../chapter-2">Chapter 2</a></li><li><a href="/novel/first/chapter-1">Chapter 1</a></li></ul>""",
}


class ChapterListRequestTests(unittest.TestCase):
    def source_with(self, table: str) -> TomlSource:
        content = FIXTURE.read_text(encoding="utf-8").replace("\n[chapter]", table + "\n[chapter]")
        return TomlSource(parse_source_definition(content), FIXTURE)

    def test_chapters_come_from_the_second_request(self) -> None:
        requests: list[tuple[str, RequestMethod]] = []

        def fetch_page(url: str, method: RequestMethod = RequestMethod.GET):
            requests.append((url, method))
            return parse_html(CHAPTER_LIST_PAGES[(url, method)])

        source = self.source_with(CHAPTER_LIST_TABLE)
        with mock.patch("novelterm.sources.toml_source.fetch_document", fetch_page):
            novel = source.get_novel("https://example.org/novel/first/")
        self.assertEqual(list(CHAPTER_LIST_PAGES), requests)
        self.assertEqual(
            [chapter.url for chapter in novel.chapters],
            ["https://example.org/novel/first/chapter-1", "https://example.org/novel/first/chapter-2"],
        )
        self.assertEqual(novel.locked_chapter_count, 1)

    def test_locked_chapters_are_not_readable_chapters(self) -> None:
        source = TomlSource(parse_source_definition(FIXTURE.read_text(encoding="utf-8").replace('chapters = "ul.free a"', 'chapters = "ul a"')), FIXTURE)
        with mock.patch("novelterm.sources.toml_source.fetch_document", fake_fetch_document):
            novel = source.get_novel("https://example.org/novel/first")
        self.assertEqual([chapter.title for chapter in novel.chapters], ["Chapter 1", "Chapter 2", "Chapter 3"])
        self.assertEqual(novel.locked_chapter_count, 1)

    def test_url_needs_the_placeholder(self) -> None:
        with self.assertRaisesRegex(SourceFileError, "novel.chapter_list.url"):
            self.source_with(CHAPTER_LIST_TABLE.replace("{novel_url}", "https://example.org/"))

    def test_method_must_be_get_or_post(self) -> None:
        with self.assertRaisesRegex(SourceFileError, "novel.chapter_list.method"):
            self.source_with(CHAPTER_LIST_TABLE.replace('"post"', '"put"'))


if __name__ == "__main__":
    unittest.main()

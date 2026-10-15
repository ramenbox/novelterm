import shutil
import tempfile
import unittest
from pathlib import Path

from novelterm.sources import load_catalog
from novelterm.sources.definition import ChapterOrder, SourceFileError, parse_source_definition, parse_template

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEMPLATE_FILE = FIXTURES / "templates" / "example-theme.toml"
THEMED_SOURCE_FILE = FIXTURES / "templated_sources" / "themed-site.toml"


def template_text() -> str:
    return TEMPLATE_FILE.read_text(encoding="utf-8")


def themed_source_text() -> str:
    return THEMED_SOURCE_FILE.read_text(encoding="utf-8")


class TemplateFormatTests(unittest.TestCase):
    def test_source_gets_the_template_rules(self) -> None:
        templates = {"example-theme": parse_template(template_text())}
        definition = parse_source_definition(themed_source_text(), templates)
        self.assertEqual(definition.template, "example-theme")
        self.assertEqual(definition.novel_list.page, "https://themed.example.org/novels/")
        self.assertEqual(definition.search.url_template if definition.search else None, "https://themed.example.org/?s={query}")
        self.assertEqual(definition.chapter.content.text, "div.text")
        self.assertEqual(definition.novel.chapter_order, ChapterOrder.NEWEST_FIRST)

    def test_source_key_wins_over_template_key(self) -> None:
        templates = {"example-theme": parse_template(template_text())}
        definition = parse_source_definition(themed_source_text(), templates)
        self.assertEqual(definition.novel.title.text, "div.post-title h1")
        self.assertEqual(definition.novel.chapters.text, "ul.chapters a")

    def test_missing_template_is_an_error(self) -> None:
        with self.assertRaisesRegex(SourceFileError, "template 'example-theme' is not installed"):
            parse_source_definition(themed_source_text(), {})

    def test_template_needs_format_version_2_in_the_source(self) -> None:
        content = themed_source_text().replace("format_version = 2", "format_version = 1")
        with self.assertRaisesRegex(SourceFileError, "'template' needs format_version = 2"):
            parse_source_definition(content, {"example-theme": parse_template(template_text())})

    def test_template_file_errors(self) -> None:
        cases = {
            "not a template": (template_text().replace('kind = "template"\n', ""), "'kind'"),
            "site key": (template_text().replace('description = "Test fixture"', 'hosts = ["example.org"]'), "remove hosts"),
            "old format": (template_text().replace("format_version = 2", "format_version = 1"), "format_version"),
        }
        for name, (content, expected) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(SourceFileError, expected):
                parse_template(content)


class TemplateCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.local_sources = self.directory / "config" / "sources"
        self.installed_sources = self.directory / "data" / "sources"
        self.local_sources.mkdir(parents=True)
        shutil.copy(THEMED_SOURCE_FILE, self.local_sources)

    def tearDown(self) -> None:
        shutil.rmtree(self.directory)

    def test_template_in_the_templates_folder_next_to_the_sources_folder(self) -> None:
        (self.directory / "config" / "templates").mkdir()
        shutil.copy(TEMPLATE_FILE, self.directory / "config" / "templates")
        catalog = load_catalog(self.local_sources, self.installed_sources)
        self.assertEqual([loaded.source.identifier for loaded in catalog.loaded], ["themed-site"])
        self.assertEqual([loaded.template.identifier for loaded in catalog.templates], ["example-theme"])
        self.assertEqual(catalog.problems, [])

    def test_source_without_its_template_is_a_problem(self) -> None:
        catalog = load_catalog(self.local_sources, self.installed_sources)
        self.assertEqual(catalog.loaded, [])
        self.assertEqual([problem.message for problem in catalog.problems], ["the template 'example-theme' is not installed"])


if __name__ == "__main__":
    unittest.main()

import re
import unittest
from pathlib import Path

from novelterm.settings import Settings, parse_settings
from novelterm.sources.definition import ChapterOrder, SourceFileError, parse_source_definition

PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent
FIXTURE = PROJECT_DIRECTORY / "tests" / "fixtures" / "sources" / "example-site.toml"


class SourceDefinitionTests(unittest.TestCase):
    def test_fixture_parses(self) -> None:
        definition = parse_source_definition(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(definition.identifier, "example-site")
        self.assertEqual(definition.novel.chapter_order, ChapterOrder.NEWEST_FIRST)

    def test_search_table_is_optional(self) -> None:
        content = FIXTURE.read_text(encoding="utf-8")
        without_search = content[: content.index("[search]")]
        self.assertIsNone(parse_source_definition(without_search).search)
        self.assertIsNotNone(parse_source_definition(content).search)

    def test_readme_example_parses(self) -> None:
        readme = (PROJECT_DIRECTORY / "README.md").read_text(encoding="utf-8")
        examples = [block for block in re.findall(r"```toml\n(.*?)```", readme, re.DOTALL) if "format_version" in block]
        self.assertEqual(len(examples), 1)
        definition = parse_source_definition(examples[0])
        self.assertIsNotNone(definition.search)

    def test_readme_settings_example_parses(self) -> None:
        readme = (PROJECT_DIRECTORY / "README.md").read_text(encoding="utf-8")
        examples = [block for block in re.findall(r"```toml\n(.*?)```", readme, re.DOTALL) if "[reader]" in block]
        self.assertEqual(len(examples), 1)
        self.assertEqual(parse_settings(examples[0]), Settings())

    def test_errors_name_the_key(self) -> None:
        content = FIXTURE.read_text(encoding="utf-8")
        cases = {
            "wrong format version": (content.replace("format_version = 1", "format_version = 2"), "format_version"),
            "bad identifier": (content.replace('"example-site"', '"Example Site"'), "identifier"),
            "bad version": (content.replace('version = "1.0.0"', 'version = "one"'), "version"),
            "bad selector": (content.replace('title = "h1.title"', 'title = "h1 >"'), "novel.title"),
            "bad choice": (content.replace('"newest_first"', '"random"'), "novel.chapter_order"),
            "bad pattern": (content.replace('"^/novel/[^/]+/?$"', '"("'), "urls.novel_pattern"),
            "missing table": (content.replace("[chapter]", "[chapters]"), "[chapter]"),
            "search without placeholder": (content.replace("q={query}", "q=fixed"), "search.url"),
            "search without results": (content.replace('results = "ul.results a"', ""), "search.results"),
        }
        for name, (broken, expected_key) in cases.items():
            with self.subTest(name=name), self.assertRaises(SourceFileError) as context:
                parse_source_definition(broken)
            self.assertIn(expected_key, str(context.exception))


if __name__ == "__main__":
    unittest.main()

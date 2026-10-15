import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from novelterm.checker import check_source_command
from test_toml_source import FIXTURE, PAGES


class CheckSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary_directory)

    def run_check(self, url: str, page: str, *options: str) -> tuple[str, int]:
        html_file = self.temporary_directory / "page.html"
        html_file.write_text(page, encoding="utf-8")
        output = io.StringIO()
        exit_code = 0
        with contextlib.redirect_stdout(output):
            try:
                check_source_command([str(FIXTURE), *([url] if url else []), "--html", str(html_file), *options])
            except SystemExit as exit_request:
                exit_code = 1 if exit_request.code else 0
        return output.getvalue(), exit_code

    def test_chapter_page_prints_counts_and_no_text(self) -> None:
        url = "https://example.org/novel/first/chapter-2"
        output, exit_code = self.run_check(url, PAGES[url])
        self.assertEqual(exit_code, 0)
        self.assertIn("paragraphs", output)
        self.assertIn("No problems found.", output)
        self.assertNotIn("First line", output)
        self.assertNotIn("Second", output)

    def test_novel_page(self) -> None:
        url = "https://example.org/novel/first"
        output, exit_code = self.run_check(url, PAGES[url])
        self.assertEqual(exit_code, 0)
        self.assertRegex(output, r"chapters\s+3\n")
        self.assertRegex(output, r"first chapter\s+Chapter 1\n")
        self.assertRegex(output, r"locked chapters\s+1\n")

    def test_novel_list_is_the_default(self) -> None:
        output, exit_code = self.run_check("", PAGES["https://example.org/"])
        self.assertEqual(exit_code, 0)
        self.assertIn("(novel list)", output)
        self.assertIn('"First Novel", "Second Novel"', output)

    def test_novel_list_reports_the_next_page(self) -> None:
        output, exit_code = self.run_check("", PAGES["https://example.org/"])
        self.assertEqual(exit_code, 0)
        self.assertRegex(output, r"next page\s+https://example.org/\?page=2\n")

    def test_later_novel_list_page_needs_the_option(self) -> None:
        url = "https://example.org/?page=2"
        _, exit_code = self.run_check(url, PAGES[url])
        self.assertEqual(exit_code, 1)
        output, exit_code = self.run_check(url, PAGES[url], "--novel-list")
        self.assertEqual(exit_code, 0)
        self.assertIn('"Second Novel", "Third Novel"', output)

    def test_search(self) -> None:
        output, exit_code = self.run_check("", PAGES["https://example.org/search?q=first+novel"], "--search", "first novel")
        self.assertEqual(exit_code, 0)
        self.assertIn("(search)", output)

    def test_missing_content_is_a_problem(self) -> None:
        url = "https://example.org/novel/first/chapter-2"
        output, exit_code = self.run_check(url, "<h1 class='chapter-title'>Chapter 2</h1>")
        self.assertEqual(exit_code, 1)
        self.assertIn("chapter.content", output)


if __name__ == "__main__":
    unittest.main()

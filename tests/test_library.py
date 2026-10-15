import shutil
import tempfile
import unittest
from pathlib import Path

from novelterm.library import Library


class LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = Path(tempfile.mkdtemp())
        self.library_file = self.temporary_directory / "library.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary_directory)

    def test_progress_is_saved_and_reloaded(self) -> None:
        library = Library(self.library_file)
        library.record_progress("example-site", "First Novel", "https://example.org/novel/first", "Chapter 2", "https://example.org/novel/first/chapter-2", 0.5)

        reloaded = Library(self.library_file)
        recent = reloaded.most_recent_reading()
        self.assertIsNotNone(recent)
        self.assertEqual(recent.chapter_title if recent else None, "Chapter 2")
        self.assertEqual(recent.scroll_fraction if recent else None, 0.5)
        self.assertEqual([entry.novel_title for entry in reloaded.saved_novels()], ["First Novel"])

    def test_removed_novel_keeps_progress(self) -> None:
        library = Library(self.library_file)
        library.record_progress("example-site", "First Novel", "https://example.org/novel/first", "Chapter 2", "https://example.org/novel/first/chapter-2", 0.0)
        library.set_in_library("example-site", "First Novel", "https://example.org/novel/first", False)
        library.record_progress("example-site", "First Novel", "https://example.org/novel/first", "Chapter 3", "https://example.org/novel/first/chapter-3", 0.0)

        self.assertEqual(library.saved_novels(), [])
        entry = library.entry("https://example.org/novel/first")
        self.assertEqual(entry.chapter_title if entry else None, "Chapter 3")


if __name__ == "__main__":
    unittest.main()

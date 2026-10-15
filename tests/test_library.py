import shutil
import tempfile
import unittest
from pathlib import Path

import json

from novelterm.library import Library, LibrarySort, url_with_same_slug


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


    def test_read_markers_and_unread_count(self) -> None:
        library = Library(self.library_file)
        novel_url = "https://example.org/novel/first"
        chapters = [f"{novel_url}/chapter-{number}" for number in range(1, 6)]
        library.record_progress("example-site", "First Novel", novel_url, "Chapter 1", chapters[0], 1.0, finished=True)
        self.assertEqual(library.record_chapter_list(novel_url, chapters[:3]), 0)
        library.record_progress("example-site", "First Novel", novel_url, "Chapter 2", chapters[1], 0.3)

        reloaded = Library(self.library_file)
        entry = reloaded.entry(novel_url)
        assert entry is not None
        self.assertEqual(entry.read_chapter_urls, frozenset({chapters[0]}))
        self.assertEqual(entry.unread_count(), 1)
        self.assertEqual(reloaded.record_chapter_list(novel_url, chapters), 2)
        self.assertEqual(reloaded.entry(novel_url).unread_count(), 3)  # type: ignore[union-attr]

    def test_chapter_list_needs_an_entry(self) -> None:
        library = Library(self.library_file)
        self.assertEqual(library.record_chapter_list("https://example.org/novel/unknown", ["a"]), 0)
        self.assertIsNone(library.entry("https://example.org/novel/unknown"))

    def test_old_library_file_loads(self) -> None:
        old_entry = {
            "source_identifier": "example-site",
            "novel_title": "First Novel",
            "novel_url": "https://example.org/novel/first",
            "in_library": True,
            "chapter_title": None,
            "chapter_url": None,
            "scroll_fraction": 0.0,
            "updated_at": "",
        }
        self.library_file.write_text(json.dumps({"entries": [old_entry]}), encoding="utf-8")
        entry = Library(self.library_file).entry("https://example.org/novel/first")
        self.assertEqual(entry.read_chapter_urls if entry else None, frozenset())

    def test_sort(self) -> None:
        library = Library(self.library_file)
        library.set_in_library("b-site", "Alpha", "https://example.org/novel/alpha", True)
        library.set_in_library("a-site", "Beta", "https://example.org/novel/beta", True)
        library.record_progress("b-site", "Alpha", "https://example.org/novel/alpha", "Chapter 1", "https://example.org/novel/alpha/chapter-1", 0.0)
        self.assertEqual([entry.novel_title for entry in library.saved_novels(LibrarySort.LAST_READ)], ["Alpha", "Beta"])
        self.assertEqual([entry.novel_title for entry in library.saved_novels(LibrarySort.TITLE)], ["Alpha", "Beta"])
        self.assertEqual([entry.novel_title for entry in library.saved_novels(LibrarySort.SOURCE)], ["Beta", "Alpha"])

    def test_export_and_import_merge(self) -> None:
        novel_url = "https://example.org/novel/first"
        other = Library(self.temporary_directory / "other.json")
        other.record_progress("example-site", "First Novel", novel_url, "Chapter 1", f"{novel_url}/chapter-1", 1.0, finished=True)
        library = Library(self.library_file)
        library.record_progress("example-site", "First Novel", novel_url, "Chapter 3", f"{novel_url}/chapter-3", 0.5, finished=False)
        library.set_in_library("example-site", "Second Novel", "https://example.org/novel/second", True)

        backup = self.temporary_directory / "backup.json"
        self.assertEqual(other.export_to(backup), 1)
        self.assertEqual(library.import_from(backup), 1)

        merged = Library(self.library_file).entry(novel_url)
        assert merged is not None
        self.assertEqual(merged.chapter_title, "Chapter 3")
        self.assertEqual(merged.read_chapter_urls, frozenset({f"{novel_url}/chapter-1"}))
        self.assertIsNotNone(Library(self.library_file).entry("https://example.org/novel/second"))

    def test_url_with_same_slug(self) -> None:
        candidates = ["https://example.org/episodes/ep-1/", "https://example.org/episodes/ep-2/"]
        self.assertEqual(url_with_same_slug("https://example.org/archives/episodes/ep-2", candidates), candidates[1])
        self.assertIsNone(url_with_same_slug("https://example.org/archives/episodes/ep-9", candidates))
        self.assertIsNone(url_with_same_slug("https://example.org/a/ep-1", [*candidates, "https://example.org/b/ep-1"]))

    def test_move_novel(self) -> None:
        old_novel = "https://example.org/archives/novels/first"
        library = Library(self.library_file)
        library.record_progress("example-site", "First", old_novel, "Ep 1", f"{old_novel}/ep-1", 1.0, finished=True)
        library.record_progress("example-site", "First", old_novel, "Ep 2", f"{old_novel}/ep-2", 0.4)
        new_chapters = ["https://example.org/episodes/ep-1/", "https://example.org/episodes/ep-2/", "https://example.org/episodes/ep-3/"]
        library.move_novel(old_novel, "https://example.org/novels/first/", "First", "Episode 2", new_chapters[1], 0.4, new_chapters)

        reloaded = Library(self.library_file)
        self.assertIsNone(reloaded.entry(old_novel))
        moved = reloaded.entry("https://example.org/novels/first/")
        assert moved is not None
        self.assertEqual((moved.chapter_url, moved.scroll_fraction), (new_chapters[1], 0.4))
        self.assertEqual(moved.read_chapter_urls, frozenset({new_chapters[0]}))
        self.assertEqual(moved.unread_count(), 1)

    def test_import_rejects_other_files(self) -> None:
        other_file = self.temporary_directory / "other.json"
        other_file.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            Library(self.library_file).import_from(other_file)


if __name__ == "__main__":
    unittest.main()

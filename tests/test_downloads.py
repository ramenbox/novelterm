import shutil
import tempfile
import unittest
from pathlib import Path

from novelterm.downloads import DownloadStore
from novelterm.models import Chapter

NOVEL_URL = "https://example.org/novel/first"


def chapter(number: int) -> Chapter:
    return Chapter(
        title=f"Chapter {number}",
        url=f"{NOVEL_URL}/chapter-{number}",
        novel_url=NOVEL_URL,
        paragraphs=["One.", "Two."],
        previous_url=None,
        next_url=None,
    )


class DownloadStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary_directory)

    def test_save_load_and_delete(self) -> None:
        store = DownloadStore(self.temporary_directory)
        store.save(NOVEL_URL, chapter(1))
        store.save(NOVEL_URL, chapter(2))
        store.save(NOVEL_URL, chapter(2))

        reloaded = DownloadStore(self.temporary_directory)
        self.assertEqual(reloaded.count_for(NOVEL_URL), 2)
        self.assertEqual(reloaded.load(chapter(1).url), chapter(1))
        self.assertIsNone(reloaded.load(f"{NOVEL_URL}/chapter-9"))

        self.assertEqual(reloaded.delete_novel(NOVEL_URL), 2)
        self.assertFalse(reloaded.has(chapter(1).url))
        self.assertEqual(DownloadStore(self.temporary_directory).count_for(NOVEL_URL), 0)


if __name__ == "__main__":
    unittest.main()

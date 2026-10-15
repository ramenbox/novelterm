import unittest

from novelterm.app import LoadedListing
from novelterm.models import Listing, NovelListPage, NovelSummary


def novel(name: str) -> NovelSummary:
    return NovelSummary(title=name, url=f"https://example.org/novel/{name}")


class LoadedListingTests(unittest.TestCase):
    def test_pages_add_up_without_duplicates(self) -> None:
        first = NovelListPage(url="https://example.org/1", novels=[novel("a"), novel("b")], next_page_url="https://example.org/2")
        loaded = LoadedListing.first_page(Listing.NOVEL_LIST, first)
        self.assertEqual(loaded.next_page_url, "https://example.org/2")
        loaded.add_page(NovelListPage(url="https://example.org/2", novels=[novel("b"), novel("c")], next_page_url=None))
        self.assertEqual([summary.title for summary in loaded.novels], ["a", "b", "c"])
        self.assertEqual(loaded.loaded_page_count, 2)
        self.assertIsNone(loaded.next_page_url)

    def test_link_back_to_a_loaded_page_ends_the_list(self) -> None:
        first = NovelListPage(url="https://example.org/1", novels=[novel("a")], next_page_url="https://example.org/2")
        loaded = LoadedListing.first_page(Listing.SEARCH, first)
        loaded.add_page(NovelListPage(url="https://example.org/2", novels=[novel("b")], next_page_url="https://example.org/1"))
        self.assertIsNone(loaded.next_page_url)


if __name__ == "__main__":
    unittest.main()

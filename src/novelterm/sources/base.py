from typing import Protocol, runtime_checkable

from novelterm.models import Chapter, LinkKind, Listing, NovelDetails, NovelListPage


@runtime_checkable
class Source(Protocol):
    """One website that novelterm can read from."""

    identifier: str
    """Stable id, used in the library file. Do not change it after release."""
    name: str
    home_url: str
    description: str

    @property
    def supports_search(self) -> bool: ...

    def handles(self, url: str) -> bool: ...

    def link_kind(self, url: str) -> LinkKind: ...

    def list_novels(self) -> NovelListPage: ...

    def search(self, query: str) -> NovelListPage: ...

    def next_novel_page(self, listing: Listing, page_url: str) -> NovelListPage: ...

    def get_novel(self, url: str) -> NovelDetails: ...

    def get_chapter(self, url: str) -> Chapter: ...

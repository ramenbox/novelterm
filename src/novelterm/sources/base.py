from typing import Protocol, runtime_checkable

from novelterm.models import Chapter, LinkKind, NovelDetails, NovelSummary


@runtime_checkable
class Source(Protocol):
    """One website that novelterm can read from.

    To add a site, make a new module in this package with a class that
    matches this protocol, and add an instance to ALL_SOURCES.
    """

    identifier: str
    """Stable id, used in the library file. Do not change it after release."""
    name: str
    home_url: str
    description: str

    def handles(self, url: str) -> bool: ...

    def link_kind(self, url: str) -> LinkKind: ...

    def list_novels(self) -> list[NovelSummary]: ...

    def get_novel(self, url: str) -> NovelDetails: ...

    def get_chapter(self, url: str) -> Chapter: ...

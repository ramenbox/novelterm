"""Saved novels and reading progress, stored as JSON on disk."""

import json
import tempfile
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from novelterm.paths import LIBRARY_FILE


class LibrarySort(Enum):
    LAST_READ = "last_read"
    TITLE = "title"
    SOURCE = "source"


@dataclass(frozen=True)
class LibraryEntry:
    source_identifier: str
    novel_title: str
    novel_url: str
    in_library: bool
    chapter_title: str | None = None
    chapter_url: str | None = None
    scroll_fraction: float = 0.0
    """How far down the current chapter the reader was, from 0.0 to 1.0."""
    updated_at: str = ""
    read_chapter_urls: frozenset[str] = frozenset()
    """Chapters the reader finished."""
    known_chapter_urls: tuple[str, ...] = ()
    """Readable chapters from the last time novelterm loaded the novel page, oldest first."""

    def unread_count(self) -> int:
        """Known chapters after the current chapter that are not read.

        Before the first chapter is opened, all known chapters count.
        """
        match self.chapter_url:
            case str(chapter_url) if chapter_url in self.known_chapter_urls:
                later = self.known_chapter_urls[self.known_chapter_urls.index(chapter_url) + 1 :]
            case _:
                later = self.known_chapter_urls
        return sum(1 for url in later if url not in self.read_chapter_urls)


def entry_to_json(entry: LibraryEntry) -> dict[str, Any]:
    stored = asdict(entry)
    stored["read_chapter_urls"] = sorted(entry.read_chapter_urls)
    stored["known_chapter_urls"] = list(entry.known_chapter_urls)
    return stored


def entry_from_json(stored: dict[str, Any]) -> LibraryEntry:
    known_names = {field.name for field in fields(LibraryEntry)}
    values = {name: value for name, value in stored.items() if name in known_names}
    values["read_chapter_urls"] = frozenset(stored.get("read_chapter_urls", []))
    values["known_chapter_urls"] = tuple(stored.get("known_chapter_urls", []))
    return LibraryEntry(**values)


def merge_entries(first: LibraryEntry, second: LibraryEntry) -> LibraryEntry:
    """Combine two records of the same novel: the newer position wins, read markers add up."""
    newer, older = (first, second) if first.updated_at >= second.updated_at else (second, first)
    return replace(
        newer,
        read_chapter_urls=newer.read_chapter_urls | older.read_chapter_urls,
        known_chapter_urls=newer.known_chapter_urls or older.known_chapter_urls,
    )


class Library:
    def __init__(self, path: Path = LIBRARY_FILE) -> None:
        self.path = path
        self.entries: dict[str, LibraryEntry] = {}
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            stored = {"entries": []}
        for stored_entry in stored.get("entries", []):
            entry = entry_from_json(stored_entry)
            self.entries[entry.novel_url] = entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps({"entries": [entry_to_json(entry) for entry in self.entries.values()]}, indent=2)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as temporary_file:
            temporary_file.write(content)
        Path(temporary_file.name).replace(self.path)

    def entry(self, novel_url: str) -> LibraryEntry | None:
        return self.entries.get(novel_url)

    def saved_novels(self, sort: LibrarySort = LibrarySort.LAST_READ) -> list[LibraryEntry]:
        saved = [entry for entry in self.entries.values() if entry.in_library]
        match sort:
            case LibrarySort.LAST_READ:
                return sorted(saved, key=lambda entry: entry.updated_at, reverse=True)
            case LibrarySort.TITLE:
                return sorted(saved, key=lambda entry: entry.novel_title.lower())
            case LibrarySort.SOURCE:
                return sorted(saved, key=lambda entry: (entry.source_identifier, entry.novel_title.lower()))

    def most_recent_reading(self) -> LibraryEntry | None:
        started = [entry for entry in self.entries.values() if entry.chapter_url]
        return max(started, key=lambda entry: entry.updated_at, default=None)

    def record_progress(
        self,
        source_identifier: str,
        novel_title: str,
        novel_url: str,
        chapter_title: str,
        chapter_url: str,
        scroll_fraction: float,
        finished: bool = False,
    ) -> None:
        """Save the reading position. A novel you start reading goes into the library.

        With finished set, the chapter is also marked as read.
        """
        previous = self.entries.get(novel_url) or LibraryEntry(
            source_identifier=source_identifier, novel_title=novel_title, novel_url=novel_url, in_library=True
        )
        read_chapter_urls = previous.read_chapter_urls | {chapter_url} if finished else previous.read_chapter_urls
        self.entries[novel_url] = replace(
            previous,
            source_identifier=source_identifier,
            novel_title=novel_title,
            chapter_title=chapter_title,
            chapter_url=chapter_url,
            scroll_fraction=scroll_fraction,
            updated_at=current_time(),
            read_chapter_urls=read_chapter_urls,
        )
        self.save()

    def record_chapter_list(self, novel_url: str, chapter_urls: list[str]) -> int:
        """Save the current chapter list of a novel that has an entry.

        Returns the number of chapters that were not in the previous list. Returns 0
        for the first list, because then nothing is known to be new.
        """
        previous = self.entries.get(novel_url)
        if previous is None or tuple(chapter_urls) == previous.known_chapter_urls:
            return 0
        known = set(previous.known_chapter_urls)
        new_count = sum(1 for url in chapter_urls if url not in known) if known else 0
        self.entries[novel_url] = replace(previous, known_chapter_urls=tuple(chapter_urls))
        self.save()
        return new_count

    def set_in_library(self, source_identifier: str, novel_title: str, novel_url: str, in_library: bool) -> None:
        previous = self.entries.get(novel_url)
        match previous:
            case LibraryEntry():
                self.entries[novel_url] = replace(previous, in_library=in_library)
            case None:
                self.entries[novel_url] = LibraryEntry(
                    source_identifier=source_identifier,
                    novel_title=novel_title,
                    novel_url=novel_url,
                    in_library=in_library,
                    updated_at=current_time(),
                )
        self.save()

    def export_to(self, file_path: Path) -> int:
        """Write a copy of the library. Returns the number of novels written."""
        content = json.dumps({"entries": [entry_to_json(entry) for entry in self.entries.values()]}, indent=2)
        file_path.write_text(content + "\n", encoding="utf-8")
        return len(self.entries)

    def import_from(self, file_path: Path) -> int:
        """Merge a library copy into this library. Returns the number of novels in the copy."""
        stored = json.loads(file_path.read_text(encoding="utf-8"))
        match stored:
            case {"entries": list(stored_entries)}:
                pass
            case _:
                raise ValueError(f"{file_path} is not a novelterm library file")
        for stored_entry in stored_entries:
            imported = entry_from_json(stored_entry)
            match self.entries.get(imported.novel_url):
                case None:
                    self.entries[imported.novel_url] = imported
                case LibraryEntry() as existing:
                    self.entries[imported.novel_url] = merge_entries(existing, imported)
        self.save()
        return len(stored_entries)


def current_time() -> str:
    return datetime.now(timezone.utc).isoformat()

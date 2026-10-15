"""Saved novels and reading progress, stored as JSON on disk."""

import json
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from novelterm.paths import LIBRARY_FILE


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


class Library:
    def __init__(self, path: Path = LIBRARY_FILE) -> None:
        self.path = path
        self.entries: dict[str, LibraryEntry] = {}
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            stored = {"entries": []}
        for fields in stored.get("entries", []):
            entry = LibraryEntry(**fields)
            self.entries[entry.novel_url] = entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps({"entries": [asdict(entry) for entry in self.entries.values()]}, indent=2)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as temporary_file:
            temporary_file.write(content)
        Path(temporary_file.name).replace(self.path)

    def entry(self, novel_url: str) -> LibraryEntry | None:
        return self.entries.get(novel_url)

    def saved_novels(self) -> list[LibraryEntry]:
        """Novels in the library, most recently read first."""
        saved = [entry for entry in self.entries.values() if entry.in_library]
        return sorted(saved, key=lambda entry: entry.updated_at, reverse=True)

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
    ) -> None:
        """Save the reading position. A novel you start reading goes into the library."""
        previous = self.entries.get(novel_url)
        self.entries[novel_url] = LibraryEntry(
            source_identifier=source_identifier,
            novel_title=novel_title,
            novel_url=novel_url,
            in_library=previous.in_library if previous else True,
            chapter_title=chapter_title,
            chapter_url=chapter_url,
            scroll_fraction=scroll_fraction,
            updated_at=current_time(),
        )
        self.save()

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


def current_time() -> str:
    return datetime.now(timezone.utc).isoformat()

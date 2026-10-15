"""Chapters saved on disk for offline reading.

Layout of DATA/downloads:

    chapters/<sha256 of the chapter URL>.json   one parsed chapter
    novels.json                                 novel URL -> list of downloaded chapter URLs
"""

import hashlib
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from novelterm.models import Chapter
from novelterm.paths import DOWNLOADS_DIRECTORY


class DownloadStore:
    def __init__(self, directory: Path = DOWNLOADS_DIRECTORY) -> None:
        self.directory = directory
        self.novels_file = directory / "novels.json"
        try:
            stored = json.loads(self.novels_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            stored = {}
        self.chapters_by_novel: dict[str, list[str]] = {
            novel_url: list(chapter_urls) for novel_url, chapter_urls in stored.get("novels", {}).items()
        }

    def chapter_file(self, chapter_url: str) -> Path:
        return self.directory / "chapters" / f"{hashlib.sha256(chapter_url.encode()).hexdigest()}.json"

    def has(self, chapter_url: str) -> bool:
        return self.chapter_file(chapter_url).is_file()

    def load(self, chapter_url: str) -> Chapter | None:
        try:
            stored = json.loads(self.chapter_file(chapter_url).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        return Chapter(**stored)

    def save(self, novel_url: str, chapter: Chapter) -> None:
        write_atomically(self.chapter_file(chapter.url), json.dumps(asdict(chapter)))
        chapter_urls = self.chapters_by_novel.setdefault(novel_url, [])
        if chapter.url not in chapter_urls:
            chapter_urls.append(chapter.url)
            self.save_novels()

    def count_for(self, novel_url: str) -> int:
        return len(self.chapters_by_novel.get(novel_url, []))

    def delete_novel(self, novel_url: str) -> int:
        """Delete all downloaded chapters of a novel. Returns how many were deleted."""
        chapter_urls = self.chapters_by_novel.pop(novel_url, [])
        for chapter_url in chapter_urls:
            self.chapter_file(chapter_url).unlink(missing_ok=True)
        self.save_novels()
        return len(chapter_urls)

    def save_novels(self) -> None:
        write_atomically(self.novels_file, json.dumps({"novels": self.chapters_by_novel}, indent=2))


def write_atomically(file_path: Path, content: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=file_path.parent, delete=False) as temporary_file:
        temporary_file.write(content)
    Path(temporary_file.name).replace(file_path)

"""Screens of novelterm: home, library, sources, repositories, novel, chapter list, reader and settings."""

import argparse
import curses
import json
import os
import sys
import textwrap
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path

from novelterm.checker import check_source_command
from novelterm.downloads import DownloadStore
from novelterm.library import Library, LibraryEntry, LibrarySort
from novelterm.models import Chapter, LinkKind, NovelDetails, NovelSummary
from novelterm.network import MINIMUM_SECONDS_BETWEEN_REQUESTS, FetchError
from novelterm.paths import LOCAL_SOURCES_DIRECTORY, SETTINGS_FILE
from novelterm.repositories import build_index, EntryStatus, IndexEntry, RepositoryError, RepositoryIndex, RepositoryStore, SavedRepository, fetch_index
from novelterm.settings import (
    LINE_WIDTH_CHOICES,
    PARAGRAPH_SPACING_RANGE,
    ReaderTheme,
    Settings,
    SettingsError,
    load_settings,
    next_in_cycle,
    save_settings,
)
from novelterm.sources import LoadedSource, Source, SourceOrigin, load_catalog
from novelterm.ui import (
    ItemStyle,
    Key,
    KeyAction,
    KeyPress,
    MenuItem,
    ReaderAttributes,
    Selected,
    apply_reader_theme,
    ask_text,
    draw_bar,
    draw_footer,
    is_cancel_key,
    key_waiting,
    put,
    read_key,
    run_menu,
    setup_colors,
    show_loading,
    show_message,
    show_progress,
)

READER_HINT = "Up/Down scroll | Space page | <-/-> chapter | q back"
CHAPTER_CACHE_SIZE = 20
"""Chapters kept in memory, so that going back and forth does not download them again."""
DOWNLOAD_BATCH_SIZES = (10, 50)
NO_SOURCES_HELP = [
    "novelterm ships without sources. A source is a small .toml file that tells novelterm how to read one site.",
    "To get sources, open Manage sources and add a repository URL, or put a .toml file in "
    + str(LOCAL_SOURCES_DIRECTORY)
    + ".",
]
REPOSITORY_WARNING = [
    "A repository is a list of source files that someone else hosts. novelterm does not check who made it.",
    "Source files are data and cannot run code on your computer. Each file is checked against its sha256 checksum.",
    "Only add repositories that you trust, and respect the rules of the sites you read.",
]
PACING_NOTE = f"novelterm waits {MINIMUM_SECONDS_BETWEEN_REQUESTS:g} second between requests to the same site."


class HomeChoice(Enum):
    CONTINUE_READING = auto()
    LIBRARY = auto()
    CHECK_UPDATES = auto()
    BROWSE_SOURCES = auto()
    MANAGE_SOURCES = auto()
    OPEN_LINK = auto()
    SETTINGS = auto()
    QUIT = auto()


@dataclass(frozen=True)
class ReadChapter:
    url: str
    scroll_fraction: float = 0.0


class ShowAllChapters:
    pass


class ShowDownloads:
    pass


class ToggleLibrary:
    pass


class SearchSource:
    pass


class LibraryKey(Enum):
    SORT = auto()
    REMOVE = auto()


@dataclass(frozen=True)
class DownloadChapters:
    limit: int | None
    """Number of chapters from the current chapter on. None means all free chapters."""


class DeleteDownloads:
    pass


class SettingChoice(Enum):
    LINE_WIDTH = auto()
    THEME = auto()
    PARAGRAPH_SPACING = auto()
    LIBRARY_SORT = auto()


class ManageChoice(Enum):
    INSTALLED_SOURCES = auto()
    REPOSITORIES = auto()
    ADD_REPOSITORY = auto()
    RELOAD = auto()
    PROBLEMS = auto()


@dataclass(frozen=True)
class OpenRepository:
    repository: SavedRepository


class AddRepository:
    pass


class RemoveRepository:
    pass


class Confirmation(Enum):
    YES = auto()
    NO = auto()


class ReaderOutcome(Enum):
    NEXT_CHAPTER = auto()
    PREVIOUS_CHAPTER = auto()
    BACK = auto()


@dataclass(frozen=True)
class UpdateFound:
    entry: LibraryEntry
    new_chapter_count: int


class App:
    def __init__(self, screen: curses.window) -> None:
        self.screen = screen
        self.library = Library()
        self.repositories = RepositoryStore()
        self.downloads = DownloadStore()
        self.catalog = load_catalog()
        self.novel_cache: dict[str, NovelDetails] = {}
        self.novel_list_cache: dict[str, list[NovelSummary]] = {}
        self.chapter_cache: dict[str, Chapter] = {}
        self.settings_problem: str | None = None
        try:
            self.settings = load_settings()
        except SettingsError as error:
            self.settings = Settings()
            self.settings_problem = str(error)

    def reload_sources(self) -> None:
        self.catalog = load_catalog()
        self.novel_cache.clear()
        self.novel_list_cache.clear()
        self.chapter_cache.clear()

    def change_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.settings_problem = None
        save_settings(settings)

    # Home

    def run(self) -> None:
        if self.settings_problem:
            show_message(
                self.screen,
                "Problem in the settings file",
                [
                    f"{SETTINGS_FILE}: {self.settings_problem}",
                    "novelterm uses the default settings. A change under Settings replaces this file.",
                ],
                is_error=True,
            )
        while True:
            recent = self.library.most_recent_reading()
            items: list[MenuItem] = []
            if recent:
                items.append(
                    MenuItem(
                        f"Continue reading: {recent.novel_title}",
                        HomeChoice.CONTINUE_READING,
                        hint=recent.chapter_title or "",
                        style=ItemStyle.ACCENT,
                    )
                )
            saved_count = len(self.library.saved_novels())
            items += [
                MenuItem("Library", HomeChoice.LIBRARY, hint=count_label(saved_count, "novel")),
                MenuItem("Check for updates", HomeChoice.CHECK_UPDATES, hint="new chapters of library novels"),
                MenuItem("Browse sources", HomeChoice.BROWSE_SOURCES, hint=count_label(len(self.catalog.loaded), "source")),
                MenuItem("Open a link", HomeChoice.OPEN_LINK, hint="paste a novel or chapter URL"),
                MenuItem("Manage sources", HomeChoice.MANAGE_SOURCES, hint="repositories and source files"),
                MenuItem("Settings", HomeChoice.SETTINGS, hint="reader and library"),
                MenuItem("Quit", HomeChoice.QUIT, style=ItemStyle.DIM),
            ]
            result = run_menu(
                self.screen,
                breadcrumb="Home",
                title="Hi! Welcome to novelterm.",
                intro_lines=["Read web novels in your terminal.", "What do you want to read today?"],
                items=items,
                top_level_notice="You are on Home. Select Quit to close novelterm.",
            )
            match result:
                case Selected(HomeChoice.CONTINUE_READING) if recent:
                    self.continue_reading(recent)
                case Selected(HomeChoice.LIBRARY):
                    self.library_screen()
                case Selected(HomeChoice.CHECK_UPDATES):
                    self.check_updates_screen()
                case Selected(HomeChoice.BROWSE_SOURCES):
                    self.sources_screen()
                case Selected(HomeChoice.MANAGE_SOURCES):
                    self.manage_sources_screen()
                case Selected(HomeChoice.OPEN_LINK):
                    self.open_link_screen()
                case Selected(HomeChoice.SETTINGS):
                    self.settings_screen()
                case Selected(HomeChoice.QUIT):
                    return
                case _:
                    pass

    def continue_reading(self, entry: LibraryEntry) -> None:
        source = self.source_for_entry(entry)
        match (source, entry.chapter_url):
            case (None, _):
                pass
            case (Source(), str(chapter_url)):
                self.read(source, chapter_url, entry.scroll_fraction)
            case (Source(), None):
                self.novel_screen(source, entry.novel_url)

    def source_for_entry(self, entry: LibraryEntry) -> Source | None:
        loaded = self.catalog.by_identifier(entry.source_identifier)
        if loaded is None:
            show_message(
                self.screen,
                "Source not installed",
                [
                    f"This novel uses the source '{entry.source_identifier}', but no source with this identifier is installed.",
                    "Install it from a repository, or put its .toml file in " + str(LOCAL_SOURCES_DIRECTORY) + ".",
                ],
                is_error=True,
            )
            return None
        return loaded.source

    # Library

    def library_screen(self) -> None:
        selected_index = 0
        while True:
            sort = self.settings.library_sort
            saved = self.library.saved_novels(sort)
            if not saved:
                show_message(
                    self.screen,
                    "Your library is empty",
                    ["Novels go into your library when you start to read them.", "You can also add a novel from its page."],
                )
                return
            items = [MenuItem(entry.novel_title, entry, hint=library_hint(entry)) for entry in saved]
            result = run_menu(
                self.screen,
                breadcrumb="Library",
                title="Your library",
                intro_lines=[f"Sorted by {sort_label(sort)}."],
                items=items,
                initial_index=selected_index,
                searchable=True,
                extra_keys={"s": LibraryKey.SORT, "d": LibraryKey.REMOVE},
                extra_hint="s sort | d remove",
            )
            match result:
                case Selected(LibraryEntry() as entry):
                    selected_index = saved.index(entry)
                    source = self.source_for_entry(entry)
                    if source:
                        self.novel_screen(source, entry.novel_url)
                case KeyAction(LibraryKey.SORT, _):
                    self.change_settings(replace(self.settings, library_sort=next_in_cycle(tuple(LibrarySort), sort)))
                    selected_index = 0
                case KeyAction(LibraryKey.REMOVE, LibraryEntry() as entry):
                    selected_index = saved.index(entry)
                    if self.confirm(
                        f"Remove {entry.novel_title} from the library?",
                        ["Your reading position and read markers stay saved. Downloaded chapters stay on disk."],
                    ):
                        self.library.set_in_library(entry.source_identifier, entry.novel_title, entry.novel_url, False)
                case _:
                    return

    def check_updates_screen(self) -> None:
        saved = self.library.saved_novels()
        if not saved:
            show_message(self.screen, "Your library is empty", ["Add novels to your library to check them for new chapters."])
            return
        found: list[UpdateFound] = []
        failures: list[str] = []
        stopped = False
        for position, entry in enumerate(saved, start=1):
            if is_cancel_key(key_waiting(self.screen)):
                stopped = True
                break
            show_progress(
                self.screen,
                "Checking for updates",
                [f"{position} of {len(saved)}: {entry.novel_title}", "", PACING_NOTE],
            )
            loaded = self.catalog.by_identifier(entry.source_identifier)
            if loaded is None:
                failures.append(f"{entry.novel_title}: the source '{entry.source_identifier}' is not installed.")
                continue
            try:
                details = loaded.source.get_novel(entry.novel_url)
            except FetchError as error:
                failures.append(f"{entry.novel_title}: {error.explanation()}")
                continue
            self.novel_cache[entry.novel_url] = details
            new_chapter_count = self.library.record_chapter_list(entry.novel_url, [chapter.url for chapter in details.chapters])
            if new_chapter_count:
                found.append(UpdateFound(entry, new_chapter_count))

        summary = [
            f"Stopped. {count_label(len(found), 'novel')} with new chapters so far." if stopped
            else f"{count_label(len(found), 'novel')} with new chapters.",
            *failures,
        ]
        if not found:
            show_message(self.screen, "No new chapters", summary, is_error=bool(failures))
            return
        while True:
            result = run_menu(
                self.screen,
                breadcrumb="Updates",
                title="New chapters",
                intro_lines=summary,
                items=[
                    MenuItem(update.entry.novel_title, update.entry, hint=count_label(update.new_chapter_count, "new chapter"))
                    for update in found
                ],
            )
            match result:
                case Selected(LibraryEntry() as entry):
                    source = self.source_for_entry(entry)
                    if source:
                        self.novel_screen(source, entry.novel_url)
                case _:
                    return

    # Sources and novels

    def sources_screen(self) -> None:
        while True:
            if not self.catalog.loaded:
                show_message(self.screen, "No sources yet", NO_SOURCES_HELP)
                return
            items = [MenuItem(source.name, source, hint=source.description) for source in self.catalog.sources()]
            result = run_menu(
                self.screen,
                breadcrumb="Sources",
                title="Pick a source",
                intro_lines=["Add more sources under Manage sources."],
                items=items,
            )
            match result:
                case Selected(Source() as source):
                    self.site_novels_screen(source)
                case _:
                    return

    def site_novels_screen(self, source: Source) -> None:
        novels = self.novel_list_cache.get(source.identifier)
        if novels is None:
            show_loading(self.screen, f"Loading novels from {source.name}...")
            try:
                novels = source.list_novels()
            except FetchError as error:
                show_message(self.screen, "Could not load the site", [error.url, error.explanation()], is_error=True)
                return
            self.novel_list_cache[source.identifier] = novels
        selected_index = 0
        while True:
            items: list[MenuItem] = []
            if source.supports_search:
                items.append(MenuItem(f"Search {source.name}", SearchSource(), hint="type a title", style=ItemStyle.ACCENT))
            items += [
                MenuItem(novel.title, novel.url, hint="* in library" if self.is_saved(novel.url) else "")
                for novel in novels
            ]
            result = run_menu(
                self.screen,
                breadcrumb=source.name,
                title=source.name,
                intro_lines=["What would you like to read?"],
                items=items,
                initial_index=selected_index,
                searchable=True,
            )
            match result:
                case Selected(SearchSource()):
                    selected_index = 0
                    self.search_screen(source)
                case Selected(str(novel_url)):
                    selected_index = [item.value for item in items].index(novel_url)
                    self.novel_screen(source, novel_url)
                case _:
                    return

    def search_screen(self, source: Source) -> None:
        query = ask_text(self.screen, f"Search {source.name}", ["Type a title or a part of it."])
        if not query:
            return
        show_loading(self.screen, f"Searching {source.name}...")
        try:
            results = source.search(query)
        except FetchError as error:
            show_message(self.screen, "Could not search the site", [error.url, error.explanation()], is_error=True)
            return
        if not results:
            show_message(self.screen, "No results", [f'{source.name} has no novels for "{query}".'])
            return
        selected_index = 0
        while True:
            result = run_menu(
                self.screen,
                breadcrumb=f"{source.name} > Search",
                title=f'Results for "{query}"',
                intro_lines=[count_label(len(results), "novel")],
                items=[
                    MenuItem(novel.title, novel.url, hint="* in library" if self.is_saved(novel.url) else "")
                    for novel in results
                ],
                initial_index=selected_index,
                searchable=True,
            )
            match result:
                case Selected(str(novel_url)):
                    selected_index = [novel.url for novel in results].index(novel_url)
                    self.novel_screen(source, novel_url)
                case _:
                    return

    def novel_screen(self, source: Source, novel_url: str) -> None:
        details = self.load_novel(source, novel_url)
        if details is None:
            return
        while True:
            entry = self.library.entry(novel_url)
            items: list[MenuItem] = []
            match (entry, details.chapters):
                case (LibraryEntry(chapter_url=str(chapter_url)), _):
                    items.append(
                        MenuItem(
                            f"Continue: {entry.chapter_title}",
                            ReadChapter(chapter_url, entry.scroll_fraction),
                            style=ItemStyle.ACCENT,
                        )
                    )
                case (_, [first_chapter, *_]):
                    items.append(MenuItem(f"Start reading: {first_chapter.title}", ReadChapter(first_chapter.url), style=ItemStyle.ACCENT))
                case _:
                    pass
            downloaded_count = self.downloads.count_for(novel_url)
            if details.chapters:
                newest = details.chapters[-1]
                items.append(MenuItem(f"Newest free chapter: {newest.title}", ReadChapter(newest.url)))
                items.append(MenuItem("All chapters", ShowAllChapters(), hint=count_label(len(details.chapters), "chapter")))
                items.append(MenuItem("Download for offline reading", ShowDownloads(), hint=f"{downloaded_count} downloaded"))
            in_library = entry is not None and entry.in_library
            items.append(MenuItem("Remove from library" if in_library else "Add to library", ToggleLibrary(), style=ItemStyle.DIM))

            intro_lines = [line for line in [f"Status: {details.status}" if details.status else "", details.description] if line]
            chapter_summary = [count_label(len(details.chapters), "free chapter")]
            if entry and entry.known_chapter_urls:
                chapter_summary.append(f"{entry.unread_count()} unread")
            if details.locked_chapter_count:
                chapter_summary.append(f"{details.locked_chapter_count} advance chapters for supporters (not shown)")
            intro_lines.append(" | ".join(chapter_summary))

            result = run_menu(
                self.screen,
                breadcrumb=source.name,
                title=details.title,
                intro_lines=intro_lines,
                items=items,
            )
            match result:
                case Selected(ReadChapter(url, scroll_fraction)):
                    self.read(source, url, scroll_fraction)
                case Selected(ShowAllChapters()):
                    self.chapter_list_screen(source, details)
                case Selected(ShowDownloads()):
                    self.downloads_screen(source, details)
                case Selected(ToggleLibrary()):
                    self.library.set_in_library(source.identifier, details.title, details.url, not in_library)
                    self.remember_chapter_list(details.url)
                case _:
                    return

    def chapter_list_screen(self, source: Source, details: NovelDetails) -> None:
        while True:
            entry = self.library.entry(details.url)
            current_url = entry.chapter_url if entry else None
            read_urls = entry.read_chapter_urls if entry else frozenset()
            items = []
            for chapter in details.chapters:
                is_current = chapter.url == current_url
                is_read = chapter.url in read_urls
                markers = [
                    marker
                    for marker, applies in (
                        ("<- you are here", is_current),
                        ("read", is_read and not is_current),
                        ("offline", self.downloads.has(chapter.url)),
                    )
                    if applies
                ]
                match (is_current, is_read):
                    case (True, _):
                        style = ItemStyle.ACCENT
                    case (False, True):
                        style = ItemStyle.DIM
                    case (False, False):
                        style = ItemStyle.NORMAL
                items.append(MenuItem(chapter.title, chapter.url, hint=" | ".join(markers), style=style))
            chapter_urls = [chapter.url for chapter in details.chapters]
            current_index = chapter_urls.index(current_url) if current_url in chapter_urls else 0
            result = run_menu(
                self.screen,
                breadcrumb=details.title,
                title="Chapters",
                intro_lines=["Oldest first. Read chapters are grey. Press / and type a number to find a chapter."],
                items=items,
                initial_index=current_index,
                searchable=True,
            )
            match result:
                case Selected(str(chapter_url)):
                    self.read(source, chapter_url)
                case _:
                    return

    def downloads_screen(self, source: Source, details: NovelDetails) -> None:
        while True:
            downloaded_count = self.downloads.count_for(details.url)
            missing_count = sum(1 for chapter in details.chapters if not self.downloads.has(chapter.url))
            items = [
                MenuItem(f"Download the next {size} chapters", DownloadChapters(size), hint="from your current chapter")
                for size in DOWNLOAD_BATCH_SIZES
            ]
            items.append(MenuItem("Download all free chapters", DownloadChapters(None), hint=f"{missing_count} not downloaded yet"))
            if downloaded_count:
                items.append(MenuItem("Delete downloaded chapters", DeleteDownloads(), hint=f"{downloaded_count} on disk", style=ItemStyle.DIM))
            result = run_menu(
                self.screen,
                breadcrumb=details.title,
                title="Download for offline reading",
                intro_lines=[
                    f"{count_label(downloaded_count, 'chapter')} downloaded. Downloaded chapters open without a connection.",
                    PACING_NOTE + " Many chapters take a long time. Press q to stop a download.",
                    "Downloads are for your own reading. Do not share them.",
                ],
                items=items,
            )
            match result:
                case Selected(DownloadChapters(limit)):
                    self.download_chapters(source, details, limit)
                case Selected(DeleteDownloads()):
                    if self.confirm(f"Delete {count_label(downloaded_count, 'downloaded chapter')}?", ["You can download them again later."]):
                        self.downloads.delete_novel(details.url)
                case _:
                    return

    def download_chapters(self, source: Source, details: NovelDetails, limit: int | None) -> None:
        entry = self.library.entry(details.url)
        chapter_urls = [chapter.url for chapter in details.chapters]
        match entry:
            case LibraryEntry(chapter_url=str(current_url)) if current_url in chapter_urls:
                start_index = chapter_urls.index(current_url)
            case _:
                start_index = 0
        match limit:
            case None:
                selected = details.chapters
            case int():
                selected = details.chapters[start_index : start_index + limit]
        pending = [chapter for chapter in selected if not self.downloads.has(chapter.url)]
        saved_count = 0
        failure: str | None = None
        for position, chapter_link in enumerate(pending, start=1):
            if is_cancel_key(key_waiting(self.screen)):
                failure = "Stopped."
                break
            show_progress(
                self.screen,
                f"Downloading {details.title}",
                [f"{position} of {len(pending)}: {chapter_link.title}", "", PACING_NOTE],
            )
            try:
                chapter = source.get_chapter(chapter_link.url)
            except FetchError as error:
                failure = error.explanation()
                break
            self.downloads.save(details.url, chapter)
            saved_count += 1
        lines = [f"{count_label(saved_count, 'chapter')} downloaded."]
        match (failure, pending):
            case (str(text), _):
                lines.append(text)
            case (None, []):
                lines = ["All these chapters are already downloaded."]
            case (None, _):
                pass
        show_message(self.screen, "Download", lines, is_error=failure is not None and failure != "Stopped.")

    def open_link_screen(self) -> None:
        url = ask_text(
            self.screen,
            "Open a link",
            ["Paste the URL of a novel page or a chapter page.", "Installed sources: " + (", ".join(source.name for source in self.catalog.sources()) or "none")],
        )
        if not url:
            return
        source = self.catalog.for_url(url)
        match (source, source.link_kind(url) if source else LinkKind.UNKNOWN):
            case (Source(), LinkKind.NOVEL):
                self.novel_screen(source, url)
            case (Source(), LinkKind.CHAPTER):
                self.read(source, url)
            case (Source(), LinkKind.UNKNOWN):
                show_message(self.screen, "Unknown page", [f"This is not a novel or chapter page on {source.name}."], is_error=True)
            case _:
                show_message(self.screen, "No source for this site", [url, *NO_SOURCES_HELP], is_error=True)

    # Settings

    def settings_screen(self) -> None:
        selected_index = 0
        while True:
            settings = self.settings
            choices = [
                MenuItem(f"Line width: {settings.line_width}", SettingChoice.LINE_WIDTH, hint="characters per line"),
                MenuItem(f"Theme: {settings.theme.value}", SettingChoice.THEME, hint="reader colors"),
                MenuItem(f"Paragraph spacing: {settings.paragraph_spacing}", SettingChoice.PARAGRAPH_SPACING, hint="empty lines between paragraphs"),
                MenuItem(f"Library sort: {sort_label(settings.library_sort)}", SettingChoice.LIBRARY_SORT),
            ]
            result = run_menu(
                self.screen,
                breadcrumb="Settings",
                title="Settings",
                intro_lines=[
                    "Press Enter to change a setting. novelterm saves each change in:",
                    str(SETTINGS_FILE),
                    "The sepia theme needs a terminal with 256 colors. Other terminals show the light theme.",
                ],
                items=choices,
                initial_index=selected_index,
            )
            match result:
                case Selected(SettingChoice() as choice):
                    selected_index = [item.value for item in choices].index(choice)
                    self.change_settings(changed_setting(settings, choice))
                case _:
                    return

    # Manage sources

    def manage_sources_screen(self) -> None:
        while True:
            items = [
                MenuItem("Installed sources", ManageChoice.INSTALLED_SOURCES, hint=count_label(len(self.catalog.loaded), "source")),
                MenuItem("Repositories", ManageChoice.REPOSITORIES, hint=count_label(len(self.repositories.repositories), "repository")),
                MenuItem("Add a repository", ManageChoice.ADD_REPOSITORY, hint="paste an index URL"),
                MenuItem("Reload source files", ManageChoice.RELOAD, hint="after you change a local .toml file"),
            ]
            if self.catalog.problems:
                items.append(
                    MenuItem("Problems", ManageChoice.PROBLEMS, hint=count_label(len(self.catalog.problems), "file"), style=ItemStyle.ACCENT)
                )
            result = run_menu(
                self.screen,
                breadcrumb="Manage sources",
                title="Manage sources",
                intro_lines=[
                    "Sources come from repositories, or from .toml files that you put in:",
                    str(LOCAL_SOURCES_DIRECTORY),
                ],
                items=items,
            )
            match result:
                case Selected(ManageChoice.INSTALLED_SOURCES):
                    self.installed_sources_screen()
                case Selected(ManageChoice.REPOSITORIES):
                    self.repositories_screen()
                case Selected(ManageChoice.ADD_REPOSITORY):
                    self.add_repository_screen()
                case Selected(ManageChoice.RELOAD):
                    self.reload_sources()
                    show_message(
                        self.screen,
                        "Sources reloaded",
                        [f"{count_label(len(self.catalog.loaded), 'source')} loaded, {count_label(len(self.catalog.problems), 'problem')}."],
                    )
                case Selected(ManageChoice.PROBLEMS):
                    show_message(
                        self.screen,
                        "Source files with problems",
                        [f"{problem.file_path}: {problem.message}" for problem in self.catalog.problems],
                        is_error=True,
                    )
                case _:
                    return

    def installed_sources_screen(self) -> None:
        while True:
            if not self.catalog.loaded:
                show_message(self.screen, "No sources yet", NO_SOURCES_HELP)
                return
            items = [MenuItem(loaded.source.name, loaded, hint=self.origin_label(loaded)) for loaded in self.catalog.loaded]
            result = run_menu(
                self.screen,
                breadcrumb="Manage sources",
                title="Installed sources",
                intro_lines=["A local file wins over an installed file with the same identifier."],
                items=items,
            )
            match result:
                case Selected(LoadedSource(origin=SourceOrigin.LOCAL) as loaded):
                    show_message(
                        self.screen,
                        loaded.source.name,
                        [
                            f"Version {loaded.source.definition.version}, local file:",
                            str(loaded.source.file_path),
                            "To remove it, delete the file and select Reload source files.",
                        ],
                    )
                case Selected(LoadedSource(origin=SourceOrigin.INSTALLED) as loaded):
                    if self.confirm(f"Remove {loaded.source.name}?", ["Novels from this source stay in your library."]):
                        self.repositories.uninstall(loaded.source.identifier)
                        self.reload_sources()
                case _:
                    return

    def origin_label(self, loaded: LoadedSource) -> str:
        version = loaded.source.definition.version
        match loaded.origin:
            case SourceOrigin.LOCAL:
                return f"v{version} | local file"
            case SourceOrigin.INSTALLED:
                record = self.repositories.installed.get(loaded.source.identifier)
                origin = self.repositories.repository_name(record.repository_url) if record else "unknown repository"
                return f"v{version} | {origin}"

    def repositories_screen(self) -> None:
        while True:
            items: list[MenuItem] = [
                MenuItem(repository.name, OpenRepository(repository), hint=repository.url)
                for repository in self.repositories.repositories
            ]
            items.append(MenuItem("Add a repository", AddRepository(), style=ItemStyle.ACCENT))
            result = run_menu(
                self.screen,
                breadcrumb="Manage sources",
                title="Repositories",
                intro_lines=["Open a repository to install, update or remove its sources."],
                items=items,
            )
            match result:
                case Selected(OpenRepository(repository)):
                    self.repository_screen(repository)
                case Selected(AddRepository()):
                    self.add_repository_screen()
                case _:
                    return

    def add_repository_screen(self) -> None:
        url = ask_text(self.screen, "Add a repository", [*REPOSITORY_WARNING, "", "Paste the URL of the repository index (index.json):"])
        if not url:
            return
        show_loading(self.screen, "Loading repository...")
        try:
            index = fetch_index(url)
        except RepositoryError as error:
            show_message(self.screen, "Could not add the repository", [str(error)], is_error=True)
            return
        self.repositories.add_repository(index)
        self.repository_screen(SavedRepository(url=index.url, name=index.name), index)

    def repository_screen(self, repository: SavedRepository, index: RepositoryIndex | None = None) -> None:
        while True:
            if index is None:
                show_loading(self.screen, f"Loading {repository.name}...")
                try:
                    index = fetch_index(repository.url)
                except RepositoryError as error:
                    show_message(self.screen, "Could not load the repository", [str(error)], is_error=True)
                    index = RepositoryIndex(url=repository.url, name=repository.name, entries=[])
            items: list[MenuItem] = [
                MenuItem(entry.name, entry, hint=self.entry_hint(entry, repository.url)) for entry in index.entries
            ]
            items.append(MenuItem("Remove this repository", RemoveRepository(), style=ItemStyle.DIM))
            result = run_menu(
                self.screen,
                breadcrumb="Repositories",
                title=index.name,
                intro_lines=[repository.url, f"{count_label(len(index.entries), 'source')}. Select a source to install, update or remove it."],
                items=items,
            )
            match result:
                case Selected(IndexEntry() as entry):
                    self.repository_entry_action(entry, repository)
                case Selected(RemoveRepository()):
                    if self.confirm(f"Remove {repository.name}?", ["Sources you installed from it stay installed."]):
                        self.repositories.remove_repository(repository.url)
                        return
                case _:
                    return

    def entry_hint(self, entry: IndexEntry, repository_url: str) -> str:
        match self.repositories.status_of(entry, repository_url):
            case EntryStatus.NOT_INSTALLED:
                return f"v{entry.version} | not installed"
            case EntryStatus.INSTALLED:
                return f"v{entry.version} | installed"
            case EntryStatus.UPDATE_AVAILABLE:
                installed_version = self.repositories.installed[entry.identifier].version
                return f"update v{installed_version} -> v{entry.version}"
            case EntryStatus.FROM_OTHER_REPOSITORY:
                return "installed from another repository"

    def repository_entry_action(self, entry: IndexEntry, repository: SavedRepository) -> None:
        status = self.repositories.status_of(entry, repository.url)
        match status:
            case EntryStatus.NOT_INSTALLED | EntryStatus.UPDATE_AVAILABLE:
                self.install_entry(entry, repository)
            case EntryStatus.INSTALLED:
                if self.confirm(f"Remove {entry.name}?", ["Novels from this source stay in your library."]):
                    self.repositories.uninstall(entry.identifier)
                    self.reload_sources()
            case EntryStatus.FROM_OTHER_REPOSITORY:
                if self.confirm(
                    f"Replace {entry.name}?",
                    [f"A source with the identifier '{entry.identifier}' is installed from another repository.", "Install this one instead?"],
                ):
                    self.install_entry(entry, repository)

    def install_entry(self, entry: IndexEntry, repository: SavedRepository) -> None:
        show_loading(self.screen, f"Installing {entry.name}...")
        try:
            self.repositories.install(entry, repository.url)
        except RepositoryError as error:
            show_message(self.screen, f"Could not install {entry.name}", [str(error)], is_error=True)
            return
        self.reload_sources()
        lines = [f"{entry.name} v{entry.version} is installed. You find it under Browse sources."]
        match self.catalog.by_identifier(entry.identifier):
            case LoadedSource(origin=SourceOrigin.LOCAL, source=local_source):
                lines.append(f"Note: the local file {local_source.file_path} has the same identifier and is used instead.")
            case _:
                pass
        show_message(self.screen, "Installed", lines)

    def confirm(self, question: str, lines: list[str]) -> bool:
        result = run_menu(
            self.screen,
            breadcrumb="Confirm",
            title=question,
            intro_lines=lines,
            items=[MenuItem("No", Confirmation.NO), MenuItem("Yes", Confirmation.YES, style=ItemStyle.ACCENT)],
        )
        match result:
            case Selected(Confirmation.YES):
                return True
            case _:
                return False

    # Reader

    def read(self, source: Source, chapter_url: str, scroll_fraction: float = 0.0) -> None:
        url: str | None = chapter_url
        attributes = apply_reader_theme(self.settings.theme)
        try:
            while url is not None:
                chapter = self.load_chapter(source, url)
                if chapter is None:
                    return
                novel_url = chapter.novel_url or chapter.url
                novel_title = self.novel_title(source, novel_url, fallback=chapter.title)
                outcome = self.show_chapter(source, chapter, novel_url, novel_title, scroll_fraction, attributes)
                scroll_fraction = 0.0
                match outcome:
                    case ReaderOutcome.NEXT_CHAPTER:
                        url = chapter.next_url
                    case ReaderOutcome.PREVIOUS_CHAPTER:
                        url = chapter.previous_url
                    case ReaderOutcome.BACK:
                        url = None
        finally:
            self.screen.bkgd(" ", 0)

    def load_chapter(self, source: Source, url: str) -> Chapter | None:
        """The chapter from memory, from the downloads, or from the site, in this order."""
        cached = self.chapter_cache.get(url) or self.downloads.load(url)
        if cached is not None:
            return cached
        show_loading(self.screen, "Loading chapter...")
        try:
            chapter = source.get_chapter(url)
        except FetchError as error:
            show_message(self.screen, "Could not load the chapter", [url, error.explanation()], is_error=True)
            return None
        self.chapter_cache[url] = chapter
        while len(self.chapter_cache) > CHAPTER_CACHE_SIZE:
            self.chapter_cache.pop(next(iter(self.chapter_cache)))
        return chapter

    def show_chapter(
        self,
        source: Source,
        chapter: Chapter,
        novel_url: str,
        novel_title: str,
        scroll_fraction: float,
        attributes: ReaderAttributes,
    ) -> ReaderOutcome:
        def save_progress(fraction: float, finished: bool) -> None:
            self.library.record_progress(source.identifier, novel_title, novel_url, chapter.title, chapter.url, fraction, finished)
            self.remember_chapter_list(novel_url)

        notice = ""
        lines: list[tuple[str, int]] = []
        top_line = 0
        layout_width = -1
        offline_label = " (offline)" if self.downloads.has(chapter.url) else ""

        while True:
            height, width = self.screen.getmaxyx()
            visible_rows = max(1, height - 2)
            text_width = min(self.settings.line_width, width - 4)
            if width != layout_width:
                lines = layout_chapter(chapter, text_width, self.settings.paragraph_spacing, attributes)
                layout_width = width
                top_line = round(scroll_fraction * max(0, len(lines) - visible_rows))
            last_top_line = max(0, len(lines) - visible_rows)
            top_line = max(0, min(top_line, last_top_line))
            scroll_fraction = top_line / last_top_line if last_top_line else 1.0

            self.screen.bkgd(" ", attributes.text)
            self.screen.erase()
            draw_bar(self.screen, 0, f"{novel_title} > {chapter.title}{offline_label}")
            left_margin = max(0, (width - text_width) // 2)
            for row, (text, line_attributes) in enumerate(lines[top_line : top_line + visible_rows]):
                put(self.screen, row + 1, left_margin, text, line_attributes)
            percent = f"{round(100 * scroll_fraction)}%"
            match notice:
                case "":
                    draw_footer(self.screen, READER_HINT, attributes.dim)
                case _:
                    draw_footer(self.screen, notice, attributes.accent)
            put(self.screen, height - 1, width - len(percent) - 2, percent, attributes.dim)
            self.screen.refresh()

            notice = ""
            at_end = top_line >= last_top_line
            pressed = read_key(self.screen)
            match pressed:
                case KeyPress(Key.UP) | KeyPress(Key.CHARACTER, "k"):
                    top_line -= 1
                case KeyPress(Key.DOWN) | KeyPress(Key.CHARACTER, "j"):
                    top_line += 1
                case KeyPress(Key.PAGE_DOWN) | KeyPress(Key.CHARACTER, " ") if at_end and chapter.next_url:
                    save_progress(1.0, finished=True)
                    return ReaderOutcome.NEXT_CHAPTER
                case KeyPress(Key.PAGE_DOWN) | KeyPress(Key.CHARACTER, " ") if at_end:
                    notice = "End of the newest free chapter."
                case KeyPress(Key.PAGE_DOWN) | KeyPress(Key.CHARACTER, " "):
                    top_line += visible_rows - 2
                case KeyPress(Key.PAGE_UP) | KeyPress(Key.CHARACTER, "b"):
                    top_line -= visible_rows - 2
                case KeyPress(Key.HOME) | KeyPress(Key.CHARACTER, "g"):
                    top_line = 0
                case KeyPress(Key.END) | KeyPress(Key.CHARACTER, "G"):
                    top_line = last_top_line
                case KeyPress(Key.RIGHT) | KeyPress(Key.CHARACTER, "n"):
                    match chapter.next_url:
                        case str():
                            save_progress(1.0, finished=True)
                            return ReaderOutcome.NEXT_CHAPTER
                        case None:
                            notice = "This is the newest free chapter."
                case KeyPress(Key.LEFT) | KeyPress(Key.CHARACTER, "p"):
                    match chapter.previous_url:
                        case str():
                            return ReaderOutcome.PREVIOUS_CHAPTER
                        case None:
                            notice = "This is the first chapter."
                case KeyPress(Key.ESCAPE) | KeyPress(Key.BACKSPACE) | KeyPress(Key.CHARACTER, "q"):
                    save_progress(scroll_fraction, finished=at_end)
                    return ReaderOutcome.BACK
                case _:
                    pass

    # Helpers

    def load_novel(self, source: Source, novel_url: str) -> NovelDetails | None:
        if novel_url in self.novel_cache:
            return self.novel_cache[novel_url]
        show_loading(self.screen, "Loading novel...")
        try:
            details = source.get_novel(novel_url)
        except FetchError as error:
            show_message(self.screen, "Could not load the novel", [novel_url, error.explanation()], is_error=True)
            return None
        self.novel_cache[novel_url] = details
        self.remember_chapter_list(novel_url)
        return details

    def remember_chapter_list(self, novel_url: str) -> None:
        """Save the loaded chapter list of a novel in its library entry, when both exist."""
        match self.novel_cache.get(novel_url):
            case NovelDetails(chapters=chapters):
                self.library.record_chapter_list(novel_url, [chapter.url for chapter in chapters])
            case None:
                pass

    def novel_title(self, source: Source, novel_url: str, fallback: str) -> str:
        entry = self.library.entry(novel_url)
        match (self.novel_cache.get(novel_url), entry):
            case (NovelDetails(title=title), _):
                return title
            case (None, LibraryEntry(novel_title=title)):
                return title
            case _:
                details = self.load_novel(source, novel_url)
                return details.title if details else fallback

    def is_saved(self, novel_url: str) -> bool:
        entry = self.library.entry(novel_url)
        return entry is not None and entry.in_library


def count_label(count: int, noun: str) -> str:
    match (count, noun):
        case (1, _):
            return f"{count} {noun}"
        case (_, str(text)) if text.endswith("y"):
            return f"{count} {text[:-1]}ies"
        case _:
            return f"{count} {noun}s"


def sort_label(sort: LibrarySort) -> str:
    match sort:
        case LibrarySort.LAST_READ:
            return "last read"
        case LibrarySort.TITLE:
            return "title"
        case LibrarySort.SOURCE:
            return "source"


def library_hint(entry: LibraryEntry) -> str:
    position = entry.chapter_title or "not started"
    unread = entry.unread_count()
    return f"{position} | {unread} unread" if unread else position


def changed_setting(settings: Settings, choice: SettingChoice) -> Settings:
    match choice:
        case SettingChoice.LINE_WIDTH:
            return replace(settings, line_width=next_in_cycle(LINE_WIDTH_CHOICES, settings.line_width))
        case SettingChoice.THEME:
            return replace(settings, theme=next_in_cycle(tuple(ReaderTheme), settings.theme))
        case SettingChoice.PARAGRAPH_SPACING:
            return replace(settings, paragraph_spacing=next_in_cycle(tuple(PARAGRAPH_SPACING_RANGE), settings.paragraph_spacing))
        case SettingChoice.LIBRARY_SORT:
            return replace(settings, library_sort=next_in_cycle(tuple(LibrarySort), settings.library_sort))


def layout_chapter(chapter: Chapter, width: int, paragraph_spacing: int, attributes: ReaderAttributes) -> list[tuple[str, int]]:
    width = max(20, width)
    lines: list[tuple[str, int]] = [(line, attributes.title) for line in textwrap.wrap(chapter.title, width)]
    lines.append(("", attributes.text))
    spacing = [("", attributes.text)] * paragraph_spacing
    for paragraph in chapter.paragraphs:
        for paragraph_line in paragraph.split("\n"):
            lines += [(wrapped, attributes.text) for wrapped in textwrap.wrap(paragraph_line, width)]
        lines += spacing
    lines.append(("", attributes.text))
    lines.append(("-- End of chapter --".center(width), attributes.dim))
    if chapter.next_url:
        lines.append(("Press Space or -> for the next chapter".center(width), attributes.accent))
    return lines


def make_index_command(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="novelterm make-index",
        description="Make a repository index.json for all .toml source files in a folder.",
    )
    parser.add_argument("folder", type=Path, help="folder with the .toml source files")
    parser.add_argument("--output", type=Path, default=Path("index.json"), help="index file to write (default: index.json)")
    parser.add_argument("--name", default="novelterm sources", help="repository name shown in the app")
    options = parser.parse_args(arguments)
    try:
        index = build_index(options.folder, options.output, options.name)
    except RepositoryError as error:
        sys.exit(f"error: {error}")
    options.output.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {options.output} with {count_label(len(index['sources']), 'source')}.")


def export_library_command(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="novelterm export-library", description="Write a copy of your library and reading positions.")
    parser.add_argument("file", type=Path, help="file to write, for example novelterm-library.json")
    options = parser.parse_args(arguments)
    count = Library().export_to(options.file)
    print(f"Wrote {options.file} with {count_label(count, 'novel')}.")


def import_library_command(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="novelterm import-library",
        description=(
            "Merge a library copy into your library. For a novel in both, the newer reading position "
            "is kept and the read markers are combined."
        ),
    )
    parser.add_argument("file", type=Path, help="a file written by export-library")
    options = parser.parse_args(arguments)
    try:
        count = Library().import_from(options.file)
    except (OSError, ValueError, TypeError) as error:
        sys.exit(f"error: {error}")
    print(f"Merged {count_label(count, 'novel')} from {options.file}.")


USAGE = """usage: novelterm                          start the reader
       novelterm check-source FILE [URL]    check a source file against one page
       novelterm make-index FOLDER          make a repository index
       novelterm export-library FILE        write a copy of your library
       novelterm import-library FILE        merge a library copy into your library
Add --help after a command for its options."""


def main() -> None:
    match sys.argv[1:]:
        case ["check-source", *arguments]:
            check_source_command(arguments)
            return
        case ["make-index", *arguments]:
            make_index_command(arguments)
            return
        case ["export-library", *arguments]:
            export_library_command(arguments)
            return
        case ["import-library", *arguments]:
            import_library_command(arguments)
            return
        case ["--help" | "-h" | "help"]:
            print(USAGE)
            return
        case []:
            pass
        case _:
            sys.exit(USAGE)
    os.environ.setdefault("ESCDELAY", "25")

    def start(screen: curses.window) -> None:
        setup_colors()
        App(screen).run()

    try:
        curses.wrapper(start)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

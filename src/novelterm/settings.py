"""User settings, stored in CONFIG/config.toml.

    [reader]
    line_width = 80          # 40 to 200
    theme = "terminal"       # "terminal", "dark", "light" or "sepia"
    paragraph_spacing = 1    # empty lines between paragraphs, 0 to 3

    [library]
    sort = "last_read"       # "last_read", "title" or "source"
"""

import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from novelterm.library import LibrarySort
from novelterm.paths import SETTINGS_FILE

LINE_WIDTH_RANGE = range(40, 201)
PARAGRAPH_SPACING_RANGE = range(0, 4)
LINE_WIDTH_CHOICES = (60, 70, 80, 100, 120)


class SettingsError(ValueError):
    pass


class ReaderTheme(Enum):
    TERMINAL = "terminal"
    """The colors of the terminal."""
    DARK = "dark"
    LIGHT = "light"
    SEPIA = "sepia"
    """Brown text on cream. Needs a terminal with 256 colors; other terminals show the light theme."""


@dataclass(frozen=True)
class Settings:
    line_width: int = 80
    theme: ReaderTheme = ReaderTheme.TERMINAL
    paragraph_spacing: int = 1
    library_sort: LibrarySort = LibrarySort.LAST_READ


def integer_setting(table: dict[str, Any], key: str, allowed: range, default: int) -> int:
    value = table.get(key, default)
    match value:
        case bool():
            raise SettingsError(f"'{key}' must be a whole number")
        case int() if value in allowed:
            return value
        case _:
            raise SettingsError(f"'{key}' must be a whole number from {allowed.start} to {allowed.stop - 1}")


def choice_setting[ChoiceType: Enum](table: dict[str, Any], key: str, choices: type[ChoiceType], default: ChoiceType) -> ChoiceType:
    value = table.get(key, default.value)
    try:
        return choices(value)
    except ValueError as error:
        allowed = ", ".join(f'"{choice.value}"' for choice in choices)
        raise SettingsError(f"'{key}' must be one of {allowed}") from error


def table_setting(document: dict[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key, {})
    match value:
        case dict():
            return value
        case _:
            raise SettingsError(f"'{key}' must be a table")


def parse_settings(content: str) -> Settings:
    try:
        document = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise SettingsError(f"not valid TOML: {error}") from error
    reader = table_setting(document, "reader")
    library = table_setting(document, "library")
    defaults = Settings()
    return Settings(
        line_width=integer_setting(reader, "line_width", LINE_WIDTH_RANGE, defaults.line_width),
        theme=choice_setting(reader, "theme", ReaderTheme, defaults.theme),
        paragraph_spacing=integer_setting(reader, "paragraph_spacing", PARAGRAPH_SPACING_RANGE, defaults.paragraph_spacing),
        library_sort=choice_setting(library, "sort", LibrarySort, defaults.library_sort),
    )


def load_settings(file_path: Path = SETTINGS_FILE) -> Settings:
    """Read the settings file. A missing file gives the defaults. Raises SettingsError for a bad file."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings()
    return parse_settings(content)


def settings_to_toml(settings: Settings) -> str:
    return (
        "[reader]\n"
        f"line_width = {settings.line_width}\n"
        f'theme = "{settings.theme.value}"\n'
        f"paragraph_spacing = {settings.paragraph_spacing}\n"
        "\n"
        "[library]\n"
        f'sort = "{settings.library_sort.value}"\n'
    )


def save_settings(settings: Settings, file_path: Path = SETTINGS_FILE) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(settings_to_toml(settings), encoding="utf-8")


def next_in_cycle[ItemType](items: tuple[ItemType, ...], current: ItemType) -> ItemType:
    """The item after current, or the first item when current is the last one or not in the list."""
    return items[(items.index(current) + 1) % len(items)] if current in items else items[0]

"""Where novelterm keeps its files.

Windows: config in %APPDATA%\\novelterm, data in %LOCALAPPDATA%\\novelterm.
Linux and macOS: config in $XDG_CONFIG_HOME/novelterm (default ~/.config/novelterm),
data in $XDG_DATA_HOME/novelterm (default ~/.local/share/novelterm).
"""

import os
import sys
from pathlib import Path


def base_directories() -> tuple[Path, Path]:
    """Return (config directory, data directory) for this platform."""
    match sys.platform:
        case "win32":
            config = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        case _:
            config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return config / "novelterm", data / "novelterm"


CONFIG_DIRECTORY, DATA_DIRECTORY = base_directories()

LIBRARY_FILE = DATA_DIRECTORY / "library.json"
INSTALLED_SOURCES_DIRECTORY = DATA_DIRECTORY / "sources"
"""Source files installed from repositories. novelterm manages this folder."""
INSTALLED_SOURCES_FILE = DATA_DIRECTORY / "installed.json"
REPOSITORIES_FILE = DATA_DIRECTORY / "repositories.json"
LOCAL_SOURCES_DIRECTORY = CONFIG_DIRECTORY / "sources"
"""Source files you write or copy by hand."""


def templates_directory_for(sources_directory: Path) -> Path:
    """The templates folder next to a sources folder: CONFIG/templates and DATA/templates."""
    return sources_directory.parent / "templates"
SETTINGS_FILE = CONFIG_DIRECTORY / "config.toml"
DOWNLOADS_DIRECTORY = DATA_DIRECTORY / "downloads"
"""Chapters saved for offline reading."""

"""Source repositories: an index file on any web host that lists source files.

Index format (index.json):

    {
      "format_version": 1,
      "name": "Example sources",
      "sources": [
        {
          "identifier": "example-site",
          "name": "Example Site",
          "version": "1.0.0",
          "description": "Short text",
          "file": "sources/example-site.toml",
          "sha256": "<hex digest of the file>"
        }
      ]
    }

"file" is relative to the index URL, or an absolute URL. novelterm checks the
sha256 before it installs a file. Source files are data and never run code.
"""

import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from novelterm.html_tree import fetch_bytes
from novelterm.network import FetchError
from novelterm.paths import INSTALLED_SOURCES_DIRECTORY, INSTALLED_SOURCES_FILE, REPOSITORIES_FILE
from novelterm.sources.definition import (
    IDENTIFIER_PATTERN,
    VERSION_PATTERN,
    SourceFileError,
    parse_source_definition,
    version_key,
)

INDEX_FORMAT_VERSION = 1
ALLOWED_URL_SCHEMES = frozenset({"https", "http", "file"})
DOWNLOAD_ERRORS = (FetchError, ValueError)


class RepositoryError(ValueError):
    pass


@dataclass(frozen=True)
class IndexEntry:
    identifier: str
    name: str
    version: str
    description: str
    file_url: str
    sha256: str


@dataclass(frozen=True)
class RepositoryIndex:
    url: str
    name: str
    entries: list[IndexEntry]


@dataclass(frozen=True)
class SavedRepository:
    url: str
    name: str


@dataclass(frozen=True)
class InstalledRecord:
    repository_url: str
    version: str
    sha256: str


class EntryStatus(Enum):
    NOT_INSTALLED = auto()
    INSTALLED = auto()
    UPDATE_AVAILABLE = auto()
    FROM_OTHER_REPOSITORY = auto()
    """A source with this identifier is installed from a different repository."""


def check_url(url: str) -> str:
    url = url.strip()
    if urlparse(url).scheme not in ALLOWED_URL_SCHEMES:
        raise RepositoryError("the URL must start with https://, http:// or file://")
    return url


def download(url: str) -> bytes:
    try:
        return fetch_bytes(check_url(url))
    except DOWNLOAD_ERRORS as error:
        raise RepositoryError(f"cannot download {url}: {error}") from error


def required_text(fields: dict[str, Any], key: str, where: str) -> str:
    value = fields.get(key)
    match value:
        case str() if value.strip():
            return value.strip()
        case _:
            raise RepositoryError(f"{where}: '{key}' is missing or not a text")


def parse_index(url: str, content: bytes) -> RepositoryIndex:
    try:
        document = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RepositoryError(f"the index is not valid JSON: {error}") from error
    match document:
        case {"format_version": int(format_version), "sources": list(raw_entries)}:
            pass
        case _:
            raise RepositoryError("the index must have 'format_version' and a 'sources' list")
    if format_version != INDEX_FORMAT_VERSION:
        raise RepositoryError(f"index format_version {format_version} is not supported (expected {INDEX_FORMAT_VERSION})")

    entries: list[IndexEntry] = []
    for position, raw_entry in enumerate(raw_entries, start=1):
        where = f"source {position} in the index"
        if not isinstance(raw_entry, dict):
            raise RepositoryError(f"{where} is not an object")
        identifier = required_text(raw_entry, "identifier", where)
        version = required_text(raw_entry, "version", where)
        if not IDENTIFIER_PATTERN.match(identifier):
            raise RepositoryError(f"{where}: identifier '{identifier}' may only use a-z, 0-9, '-' and '_'")
        if not VERSION_PATTERN.match(version):
            raise RepositoryError(f"{where}: version '{version}' must look like 1.0.0")
        entries.append(
            IndexEntry(
                identifier=identifier,
                name=required_text(raw_entry, "name", where),
                version=version,
                description=str(raw_entry.get("description", "")),
                file_url=urljoin(url, required_text(raw_entry, "file", where)),
                sha256=required_text(raw_entry, "sha256", where).lower(),
            )
        )
    name = document.get("name")
    return RepositoryIndex(url=url, name=name if isinstance(name, str) and name else url, entries=entries)


def fetch_index(url: str) -> RepositoryIndex:
    url = check_url(url)
    return parse_index(url, download(url))


class RepositoryStore:
    """Saved repositories and the record of which sources came from where."""

    def __init__(
        self,
        repositories_file: Path = REPOSITORIES_FILE,
        installed_file: Path = INSTALLED_SOURCES_FILE,
        installed_directory: Path = INSTALLED_SOURCES_DIRECTORY,
    ) -> None:
        self.repositories_file = repositories_file
        self.installed_file = installed_file
        self.installed_directory = installed_directory
        self.repositories = [SavedRepository(**fields) for fields in read_json(repositories_file).get("repositories", [])]
        self.installed = {
            identifier: InstalledRecord(**fields)
            for identifier, fields in read_json(installed_file).get("sources", {}).items()
        }

    def add_repository(self, index: RepositoryIndex) -> None:
        self.repositories = [repository for repository in self.repositories if repository.url != index.url]
        self.repositories.append(SavedRepository(url=index.url, name=index.name))
        self.save_repositories()

    def remove_repository(self, url: str) -> None:
        self.repositories = [repository for repository in self.repositories if repository.url != url]
        self.save_repositories()

    def status_of(self, entry: IndexEntry, repository_url: str) -> EntryStatus:
        record = self.installed.get(entry.identifier)
        match record:
            case None:
                return EntryStatus.NOT_INSTALLED
            case InstalledRecord() if record.repository_url != repository_url:
                return EntryStatus.FROM_OTHER_REPOSITORY
            case InstalledRecord() if version_key(entry.version) > version_key(record.version):
                return EntryStatus.UPDATE_AVAILABLE
            case InstalledRecord():
                return EntryStatus.INSTALLED

    def install(self, entry: IndexEntry, repository_url: str) -> None:
        """Download, check and save one source file. Nothing changes on disk when a check fails."""
        content = download(entry.file_url)
        digest = hashlib.sha256(content).hexdigest()
        if digest != entry.sha256:
            raise RepositoryError(
                f"checksum mismatch for {entry.file_url}: the index says {entry.sha256}, the file is {digest}"
            )
        try:
            definition = parse_source_definition(content.decode("utf-8"))
        except (SourceFileError, UnicodeDecodeError) as error:
            raise RepositoryError(f"the source file is not valid: {error}") from error
        if definition.identifier != entry.identifier or definition.version != entry.version:
            raise RepositoryError(
                f"the file says {definition.identifier} {definition.version}, "
                f"the index says {entry.identifier} {entry.version}"
            )
        write_atomically(self.installed_directory / f"{entry.identifier}.toml", content)
        self.installed[entry.identifier] = InstalledRecord(repository_url=repository_url, version=entry.version, sha256=digest)
        self.save_installed()

    def uninstall(self, identifier: str) -> None:
        (self.installed_directory / f"{identifier}.toml").unlink(missing_ok=True)
        self.installed.pop(identifier, None)
        self.save_installed()

    def repository_name(self, url: str) -> str:
        return next((repository.name for repository in self.repositories if repository.url == url), url)

    def save_repositories(self) -> None:
        content = {"repositories": [asdict(repository) for repository in self.repositories]}
        write_atomically(self.repositories_file, json.dumps(content, indent=2).encode())

    def save_installed(self) -> None:
        content = {"sources": {identifier: asdict(record) for identifier, record in self.installed.items()}}
        write_atomically(self.installed_file, json.dumps(content, indent=2).encode())


def build_index(source_directory: Path, index_path: Path, repository_name: str) -> dict[str, Any]:
    """Make an index for all source files in a folder. File paths are relative to the index file."""
    index_directory = index_path.resolve().parent
    if not source_directory.resolve().is_relative_to(index_directory):
        raise RepositoryError(
            f"the index must be in {source_directory} or in a parent folder of it, "
            "because the file paths in the index are relative to the index"
        )
    entries: list[dict[str, str]] = []
    for file_path in sorted(source_directory.glob("*.toml")):
        content = file_path.read_bytes()
        try:
            definition = parse_source_definition(content.decode("utf-8"))
        except (SourceFileError, UnicodeDecodeError) as error:
            raise RepositoryError(f"{file_path}: {error}") from error
        entries.append(
            {
                "identifier": definition.identifier,
                "name": definition.name,
                "version": definition.version,
                "description": definition.description,
                "file": file_path.resolve().relative_to(index_directory).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    identifiers = [entry["identifier"] for entry in entries]
    duplicates = sorted({identifier for identifier in identifiers if identifiers.count(identifier) > 1})
    if duplicates:
        raise RepositoryError(f"more than one file uses the identifier: {', '.join(duplicates)}")
    return {"format_version": INDEX_FORMAT_VERSION, "name": repository_name, "sources": entries}


def read_json(file_path: Path) -> dict[str, Any]:
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write_atomically(file_path: Path, content: bytes) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=file_path.parent, delete=False) as temporary_file:
        temporary_file.write(content)
    Path(temporary_file.name).replace(file_path)

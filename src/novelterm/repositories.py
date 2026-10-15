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
      ],
      "templates": [
        {
          "identifier": "example-theme",
          "name": "Example theme",
          "version": "1.0.0",
          "description": "Short text",
          "file": "templates/example-theme.toml",
          "sha256": "<hex digest of the file>"
        }
      ]
    }

"templates" is optional. "file" is relative to the index URL, or an absolute URL.
novelterm checks the sha256 before it installs a file. Source files and templates
are data and never run code.
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
from novelterm.paths import INSTALLED_SOURCES_DIRECTORY, INSTALLED_SOURCES_FILE, REPOSITORIES_FILE, templates_directory_for
from novelterm.sources.definition import (
    IDENTIFIER_PATTERN,
    VERSION_PATTERN,
    SourceFileError,
    SourceTemplate,
    parse_source_definition,
    parse_template,
    template_name,
    version_key,
)

INDEX_FORMAT_VERSION = 1
ALLOWED_URL_SCHEMES = frozenset({"https", "http", "file"})
DOWNLOAD_ERRORS = (FetchError, ValueError)


class RepositoryError(ValueError):
    pass


class EntryKind(Enum):
    SOURCE = "sources"
    TEMPLATE = "templates"
    """The value is the list name in index.json and installed.json."""


@dataclass(frozen=True)
class IndexEntry:
    kind: EntryKind
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

    def template(self, identifier: str) -> "IndexEntry | None":
        return next(
            (entry for entry in self.entries if entry.kind == EntryKind.TEMPLATE and entry.identifier == identifier),
            None,
        )


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
        case {"format_version": int(format_version), "sources": list(raw_sources)}:
            pass
        case _:
            raise RepositoryError("the index must have 'format_version' and a 'sources' list")
    if format_version != INDEX_FORMAT_VERSION:
        raise RepositoryError(f"index format_version {format_version} is not supported (expected {INDEX_FORMAT_VERSION})")
    match document.get("templates", []):
        case list(raw_templates):
            pass
        case _:
            raise RepositoryError("'templates' in the index must be a list")

    entries = [
        parse_entry(url, EntryKind.SOURCE, f"source {position} in the index", raw_entry)
        for position, raw_entry in enumerate(raw_sources, start=1)
    ] + [
        parse_entry(url, EntryKind.TEMPLATE, f"template {position} in the index", raw_entry)
        for position, raw_entry in enumerate(raw_templates, start=1)
    ]
    name = document.get("name")
    return RepositoryIndex(url=url, name=name if isinstance(name, str) and name else url, entries=entries)


def parse_entry(index_url: str, kind: EntryKind, where: str, raw_entry: Any) -> IndexEntry:
    if not isinstance(raw_entry, dict):
        raise RepositoryError(f"{where} is not an object")
    identifier = required_text(raw_entry, "identifier", where)
    version = required_text(raw_entry, "version", where)
    if not IDENTIFIER_PATTERN.match(identifier):
        raise RepositoryError(f"{where}: identifier '{identifier}' may only use a-z, 0-9, '-' and '_'")
    if not VERSION_PATTERN.match(version):
        raise RepositoryError(f"{where}: version '{version}' must look like 1.0.0")
    return IndexEntry(
        kind=kind,
        identifier=identifier,
        name=required_text(raw_entry, "name", where),
        version=version,
        description=str(raw_entry.get("description", "")),
        file_url=urljoin(index_url, required_text(raw_entry, "file", where)),
        sha256=required_text(raw_entry, "sha256", where).lower(),
    )


def fetch_index(url: str) -> RepositoryIndex:
    url = check_url(url)
    return parse_index(url, download(url))


@dataclass(frozen=True)
class CheckedFile:
    """A downloaded file that matches its sha256 and is a valid source file or template."""

    entry: IndexEntry
    content: bytes
    sha256: str


class RepositoryStore:
    """Saved repositories and the record of which sources and templates came from where."""

    def __init__(
        self,
        repositories_file: Path = REPOSITORIES_FILE,
        installed_file: Path = INSTALLED_SOURCES_FILE,
        installed_directory: Path = INSTALLED_SOURCES_DIRECTORY,
    ) -> None:
        self.repositories_file = repositories_file
        self.installed_file = installed_file
        self.installed_directory = installed_directory
        self.templates_directory = templates_directory_for(installed_directory)
        self.repositories = [SavedRepository(**fields) for fields in read_json(repositories_file).get("repositories", [])]
        installed = read_json(installed_file)
        self.installed = {
            identifier: InstalledRecord(**fields) for identifier, fields in installed.get("sources", {}).items()
        }
        self.installed_templates = {
            identifier: InstalledRecord(**fields) for identifier, fields in installed.get("templates", {}).items()
        }

    def add_repository(self, index: RepositoryIndex) -> None:
        self.repositories = [repository for repository in self.repositories if repository.url != index.url]
        self.repositories.append(SavedRepository(url=index.url, name=index.name))
        self.save_repositories()

    def remove_repository(self, url: str) -> None:
        self.repositories = [repository for repository in self.repositories if repository.url != url]
        self.save_repositories()

    def records(self, kind: EntryKind) -> dict[str, InstalledRecord]:
        match kind:
            case EntryKind.SOURCE:
                return self.installed
            case EntryKind.TEMPLATE:
                return self.installed_templates

    def directory(self, kind: EntryKind) -> Path:
        match kind:
            case EntryKind.SOURCE:
                return self.installed_directory
            case EntryKind.TEMPLATE:
                return self.templates_directory

    def status_of(self, entry: IndexEntry, repository_url: str) -> EntryStatus:
        record = self.records(entry.kind).get(entry.identifier)
        match record:
            case None:
                return EntryStatus.NOT_INSTALLED
            case InstalledRecord() if record.repository_url != repository_url:
                return EntryStatus.FROM_OTHER_REPOSITORY
            case InstalledRecord() if version_key(entry.version) > version_key(record.version):
                return EntryStatus.UPDATE_AVAILABLE
            case InstalledRecord():
                return EntryStatus.INSTALLED

    def install(self, entry: IndexEntry, index: RepositoryIndex) -> list[IndexEntry]:
        """Download, check and save a source file or a template. Returns the entries that were written.

        A source that names a template also gets that template from the same
        repository, when it is not installed or has an update. Nothing changes on
        disk when a check fails.
        """
        match entry.kind:
            case EntryKind.TEMPLATE:
                checked = [self.check_template(entry)]
            case EntryKind.SOURCE:
                checked = self.check_source(entry, index)
        for checked_file in checked:
            self.write(checked_file, index.url)
        return [checked_file.entry for checked_file in checked]

    def check_template(self, entry: IndexEntry) -> CheckedFile:
        content = download_checked(entry)
        try:
            template = parse_template(content.decode("utf-8"))
        except (SourceFileError, UnicodeDecodeError) as error:
            raise RepositoryError(f"the template file is not valid: {error}") from error
        check_identity(entry, template.identifier, template.version)
        return CheckedFile(entry, content, hashlib.sha256(content).hexdigest())

    def check_source(self, entry: IndexEntry, index: RepositoryIndex) -> list[CheckedFile]:
        """The checked source file, after the checked template it needs, if that must be installed."""
        content = download_checked(entry)
        try:
            text = content.decode("utf-8")
            needed_template = template_name(text)
        except (SourceFileError, UnicodeDecodeError) as error:
            raise RepositoryError(f"the source file is not valid: {error}") from error
        templates = self.installed_template_files()
        checked: list[CheckedFile] = []
        match needed_template:
            case None:
                pass
            case str(name):
                template_entry = index.template(name)
                match (template_entry, self.status_of(template_entry, index.url) if template_entry else None):
                    case (None, _) if name in templates:
                        pass
                    case (None, _):
                        raise RepositoryError(f"the source needs the template '{name}', which this repository does not list")
                    case (IndexEntry(), EntryStatus.FROM_OTHER_REPOSITORY):
                        raise RepositoryError(
                            f"the source needs the template '{name}', which is installed from another repository. "
                            "Remove that template first."
                        )
                    case (IndexEntry() as found, EntryStatus.NOT_INSTALLED | EntryStatus.UPDATE_AVAILABLE):
                        checked_template = self.check_template(found)
                        templates[name] = parse_template(checked_template.content.decode("utf-8"))
                        checked.append(checked_template)
                    case (IndexEntry(), _):
                        pass
        try:
            definition = parse_source_definition(text, templates)
        except SourceFileError as error:
            raise RepositoryError(f"the source file is not valid: {error}") from error
        check_identity(entry, definition.identifier, definition.version)
        checked.append(CheckedFile(entry, content, hashlib.sha256(content).hexdigest()))
        return checked

    def installed_template_files(self) -> dict[str, SourceTemplate]:
        """The installed templates that load without errors, by identifier."""
        templates: dict[str, SourceTemplate] = {}
        for identifier in self.installed_templates:
            try:
                templates[identifier] = parse_template((self.templates_directory / f"{identifier}.toml").read_text(encoding="utf-8"))
            except (OSError, SourceFileError):
                continue
        return templates

    def write(self, checked: CheckedFile, repository_url: str) -> None:
        entry = checked.entry
        write_atomically(self.directory(entry.kind) / f"{entry.identifier}.toml", checked.content)
        self.records(entry.kind)[entry.identifier] = InstalledRecord(
            repository_url=repository_url, version=entry.version, sha256=checked.sha256
        )
        self.save_installed()

    def uninstall(self, kind: EntryKind, identifier: str) -> None:
        (self.directory(kind) / f"{identifier}.toml").unlink(missing_ok=True)
        self.records(kind).pop(identifier, None)
        self.save_installed()

    def repository_name(self, url: str) -> str:
        return next((repository.name for repository in self.repositories if repository.url == url), url)

    def save_repositories(self) -> None:
        content = {"repositories": [asdict(repository) for repository in self.repositories]}
        write_atomically(self.repositories_file, json.dumps(content, indent=2).encode())

    def save_installed(self) -> None:
        content = {
            kind.value: {identifier: asdict(record) for identifier, record in self.records(kind).items()}
            for kind in EntryKind
        }
        write_atomically(self.installed_file, json.dumps(content, indent=2).encode())


def download_checked(entry: IndexEntry) -> bytes:
    content = download(entry.file_url)
    digest = hashlib.sha256(content).hexdigest()
    if digest != entry.sha256:
        raise RepositoryError(f"checksum mismatch for {entry.file_url}: the index says {entry.sha256}, the file is {digest}")
    return content


def check_identity(entry: IndexEntry, identifier: str, version: str) -> None:
    if identifier != entry.identifier or version != entry.version:
        raise RepositoryError(f"the file says {identifier} {version}, the index says {entry.identifier} {entry.version}")


def index_entry(file_path: Path, index_directory: Path, identifier: str, name: str, version: str, description: str) -> dict[str, str]:
    return {
        "identifier": identifier,
        "name": name,
        "version": version,
        "description": description,
        "file": file_path.resolve().relative_to(index_directory).as_posix(),
        "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
    }


def check_inside(directory: Path, index_directory: Path) -> None:
    if not directory.resolve().is_relative_to(index_directory):
        raise RepositoryError(
            f"the index must be in {directory} or in a parent folder of it, "
            "because the file paths in the index are relative to the index"
        )


def check_unique(entries: list[dict[str, str]], what: str) -> None:
    identifiers = [entry["identifier"] for entry in entries]
    duplicates = sorted({identifier for identifier in identifiers if identifiers.count(identifier) > 1})
    if duplicates:
        raise RepositoryError(f"more than one {what} file uses the identifier: {', '.join(duplicates)}")


def build_index(
    source_directory: Path, index_path: Path, repository_name: str, template_directory: Path | None = None
) -> dict[str, Any]:
    """Make an index for all source files in a folder, and all templates in template_directory.

    File paths are relative to the index file. Each source file is checked with these templates.
    """
    index_directory = index_path.resolve().parent
    check_inside(source_directory, index_directory)
    template_entries: list[dict[str, str]] = []
    templates: dict[str, SourceTemplate] = {}
    for file_path in sorted(template_directory.glob("*.toml")) if template_directory else []:
        check_inside(file_path.parent, index_directory)
        try:
            template = parse_template(file_path.read_text(encoding="utf-8"))
        except (SourceFileError, UnicodeDecodeError) as error:
            raise RepositoryError(f"{file_path}: {error}") from error
        templates[template.identifier] = template
        template_entries.append(
            index_entry(file_path, index_directory, template.identifier, template.name, template.version, template.description)
        )
    check_unique(template_entries, "template")

    entries: list[dict[str, str]] = []
    for file_path in sorted(source_directory.glob("*.toml")):
        try:
            definition = parse_source_definition(file_path.read_text(encoding="utf-8"), templates)
        except (SourceFileError, UnicodeDecodeError) as error:
            raise RepositoryError(f"{file_path}: {error}") from error
        entries.append(
            index_entry(file_path, index_directory, definition.identifier, definition.name, definition.version, definition.description)
        )
    check_unique(entries, "source")
    index: dict[str, Any] = {"format_version": INDEX_FORMAT_VERSION, "name": repository_name, "sources": entries}
    if template_entries:
        index["templates"] = template_entries
    return index


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

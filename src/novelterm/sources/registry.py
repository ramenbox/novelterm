"""Find and load all source files on this computer."""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from novelterm.paths import INSTALLED_SOURCES_DIRECTORY, LOCAL_SOURCES_DIRECTORY
from novelterm.sources.definition import SourceFileError, parse_source_definition
from novelterm.sources.toml_source import TomlSource


class SourceOrigin(Enum):
    LOCAL = auto()
    """A file in the local sources folder, written or copied by hand."""
    INSTALLED = auto()
    """A file installed from a repository."""


@dataclass(frozen=True)
class LoadedSource:
    source: TomlSource
    origin: SourceOrigin


@dataclass(frozen=True)
class SourceProblem:
    file_path: Path
    message: str


@dataclass(frozen=True)
class SourceCatalog:
    loaded: list[LoadedSource]
    problems: list[SourceProblem]

    def sources(self) -> list[TomlSource]:
        return [entry.source for entry in self.loaded]

    def by_identifier(self, identifier: str) -> LoadedSource | None:
        return next((entry for entry in self.loaded if entry.source.identifier == identifier), None)

    def for_url(self, url: str) -> TomlSource | None:
        return next((entry.source for entry in self.loaded if entry.source.handles(url)), None)


def load_source_file(file_path: Path) -> TomlSource:
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as error:
        raise SourceFileError(f"cannot read the file: {error}") from error
    return TomlSource(parse_source_definition(content), file_path)


def load_catalog(
    local_directory: Path = LOCAL_SOURCES_DIRECTORY,
    installed_directory: Path = INSTALLED_SOURCES_DIRECTORY,
) -> SourceCatalog:
    """Load all source files. A local file wins over an installed file with the same identifier."""
    loaded: dict[str, LoadedSource] = {}
    problems: list[SourceProblem] = []
    for directory, origin in ((local_directory, SourceOrigin.LOCAL), (installed_directory, SourceOrigin.INSTALLED)):
        for file_path in sorted(directory.glob("*.toml")) if directory.is_dir() else []:
            try:
                source = load_source_file(file_path)
            except SourceFileError as error:
                problems.append(SourceProblem(file_path, str(error)))
                continue
            match loaded.get(source.identifier):
                case None:
                    loaded[source.identifier] = LoadedSource(source, origin)
                case LoadedSource(source=existing):
                    problems.append(
                        SourceProblem(
                            file_path,
                            f"identifier '{source.identifier}' is also used by {existing.file_path}; that file is used",
                        )
                    )
    ordered = sorted(loaded.values(), key=lambda entry: entry.source.name.lower())
    return SourceCatalog(loaded=ordered, problems=problems)

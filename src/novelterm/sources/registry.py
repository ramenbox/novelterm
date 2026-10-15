"""Find and load all source files and templates on this computer."""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from novelterm.paths import INSTALLED_SOURCES_DIRECTORY, LOCAL_SOURCES_DIRECTORY, templates_directory_for
from novelterm.sources.definition import SourceFileError, SourceTemplate, parse_source_definition, parse_template
from novelterm.sources.toml_source import TomlSource


class SourceOrigin(Enum):
    LOCAL = auto()
    """A file in a local folder, written or copied by hand."""
    INSTALLED = auto()
    """A file installed from a repository."""


@dataclass(frozen=True)
class LoadedSource:
    source: TomlSource
    origin: SourceOrigin


@dataclass(frozen=True)
class LoadedTemplate:
    template: SourceTemplate
    file_path: Path
    origin: SourceOrigin


@dataclass(frozen=True)
class SourceProblem:
    file_path: Path
    message: str


@dataclass(frozen=True)
class SourceCatalog:
    loaded: list[LoadedSource]
    templates: list[LoadedTemplate]
    problems: list[SourceProblem]

    def sources(self) -> list[TomlSource]:
        return [entry.source for entry in self.loaded]

    def by_identifier(self, identifier: str) -> LoadedSource | None:
        return next((entry for entry in self.loaded if entry.source.identifier == identifier), None)

    def for_url(self, url: str) -> TomlSource | None:
        return next((entry.source for entry in self.loaded if entry.source.handles(url)), None)


def load_source_file(file_path: Path, templates: dict[str, SourceTemplate] | None = None) -> TomlSource:
    return TomlSource(parse_source_definition(read_file(file_path), templates), file_path)


def load_template_file(file_path: Path) -> SourceTemplate:
    return parse_template(read_file(file_path))


def read_file(file_path: Path) -> str:
    try:
        return file_path.read_text(encoding="utf-8")
    except OSError as error:
        raise SourceFileError(f"cannot read the file: {error}") from error


def toml_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.toml")) if directory.is_dir() else []


def load_templates(
    local_directory: Path, installed_directory: Path
) -> tuple[dict[str, LoadedTemplate], list[SourceProblem]]:
    """Load all template files. A local file wins over an installed file with the same identifier."""
    loaded: dict[str, LoadedTemplate] = {}
    problems: list[SourceProblem] = []
    for directory, origin in ((local_directory, SourceOrigin.LOCAL), (installed_directory, SourceOrigin.INSTALLED)):
        for file_path in toml_files(directory):
            try:
                template = load_template_file(file_path)
            except SourceFileError as error:
                problems.append(SourceProblem(file_path, str(error)))
                continue
            match loaded.get(template.identifier):
                case None:
                    loaded[template.identifier] = LoadedTemplate(template, file_path, origin)
                case LoadedTemplate(file_path=existing_path):
                    problems.append(
                        SourceProblem(
                            file_path,
                            f"template identifier '{template.identifier}' is also used by {existing_path}; that file is used",
                        )
                    )
    return loaded, problems


def load_catalog(
    local_directory: Path = LOCAL_SOURCES_DIRECTORY,
    installed_directory: Path = INSTALLED_SOURCES_DIRECTORY,
) -> SourceCatalog:
    """Load all templates, then all source files. A local file wins over an installed file with the same identifier.

    Templates come from the templates folders next to the two sources folders.
    """
    loaded_templates, problems = load_templates(
        templates_directory_for(local_directory), templates_directory_for(installed_directory)
    )
    templates = {identifier: loaded.template for identifier, loaded in loaded_templates.items()}
    loaded: dict[str, LoadedSource] = {}
    for directory, origin in ((local_directory, SourceOrigin.LOCAL), (installed_directory, SourceOrigin.INSTALLED)):
        for file_path in toml_files(directory):
            try:
                source = load_source_file(file_path, templates)
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
    ordered_templates = sorted(loaded_templates.values(), key=lambda entry: entry.template.name.lower())
    return SourceCatalog(loaded=ordered, templates=ordered_templates, problems=problems)

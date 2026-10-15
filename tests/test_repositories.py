import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from novelterm.repositories import EntryKind, EntryStatus, RepositoryIndex, RepositoryError, RepositoryStore, build_index, fetch_index
from novelterm.sources import SourceOrigin, load_catalog

FIXTURE_DIRECTORY = Path(__file__).resolve().parent / "fixtures" / "sources"


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = Path(tempfile.mkdtemp())
        self.repository_directory = self.temporary_directory / "repository"
        self.data_directory = self.temporary_directory / "data"
        shutil.copytree(FIXTURE_DIRECTORY, self.repository_directory / "sources")
        self.index_path = self.repository_directory / "index.json"
        self.write_index()
        self.index_url = self.index_path.as_uri()
        self.store = RepositoryStore(
            self.data_directory / "repositories.json",
            self.data_directory / "installed.json",
            self.data_directory / "sources",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary_directory)

    def write_index(self) -> None:
        index = build_index(self.repository_directory / "sources", self.index_path, "Test repository")
        self.index_path.write_text(json.dumps(index), encoding="utf-8")

    def source_file(self) -> Path:
        return self.repository_directory / "sources" / "example-site.toml"

    def test_install_update_uninstall(self) -> None:
        index = fetch_index(self.index_url)
        self.store.add_repository(index)
        entry = index.entries[0]
        self.assertEqual(self.store.status_of(entry, self.index_url), EntryStatus.NOT_INSTALLED)

        self.store.install(entry, fetch_index(self.index_url))
        self.assertEqual(self.store.status_of(entry, self.index_url), EntryStatus.INSTALLED)
        catalog = load_catalog(self.temporary_directory / "no-local-files", self.data_directory / "sources")
        loaded = catalog.by_identifier("example-site")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.origin if loaded else None, SourceOrigin.INSTALLED)

        content = self.source_file().read_text(encoding="utf-8")
        self.source_file().write_text(content.replace('version = "1.0.0"', 'version = "1.1.0"'), encoding="utf-8")
        self.write_index()
        updated_entry = fetch_index(self.index_url).entries[0]
        self.assertEqual(self.store.status_of(updated_entry, self.index_url), EntryStatus.UPDATE_AVAILABLE)
        self.store.install(updated_entry, fetch_index(self.index_url))
        self.assertEqual(self.store.installed["example-site"].version, "1.1.0")

        self.store.uninstall(EntryKind.SOURCE, "example-site")
        self.assertEqual(self.store.status_of(updated_entry, self.index_url), EntryStatus.NOT_INSTALLED)
        self.assertEqual(list((self.data_directory / "sources").glob("*.toml")), [])

    def test_changed_file_is_rejected(self) -> None:
        entry = fetch_index(self.index_url).entries[0]
        self.source_file().write_text(self.source_file().read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        with self.assertRaises(RepositoryError) as context:
            self.store.install(entry, fetch_index(self.index_url))
        self.assertIn("checksum", str(context.exception))
        self.assertFalse((self.data_directory / "sources" / "example-site.toml").exists())

    def test_rejected_urls(self) -> None:
        for url in ["ftp://example.org/index.json", "example.org/index.json"]:
            with self.subTest(url=url), self.assertRaises(RepositoryError):
                fetch_index(url)

    def test_duplicate_identifiers_fail_index_build(self) -> None:
        shutil.copy(self.source_file(), self.repository_directory / "sources" / "copy.toml")
        with self.assertRaises(RepositoryError):
            build_index(self.repository_directory / "sources", self.index_path, "Test repository")



TEMPLATE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "templates" / "example-theme.toml"
THEMED_SOURCE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "templated_sources" / "themed-site.toml"


class TemplateRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = Path(tempfile.mkdtemp())
        self.repository_directory = self.temporary_directory / "repository"
        self.data_directory = self.temporary_directory / "data"
        (self.repository_directory / "sources").mkdir(parents=True)
        (self.repository_directory / "templates").mkdir()
        shutil.copy(THEMED_SOURCE_FIXTURE, self.repository_directory / "sources")
        shutil.copy(TEMPLATE_FIXTURE, self.repository_directory / "templates")
        self.index_path = self.repository_directory / "index.json"
        self.index_url = self.index_path.as_uri()
        self.store = RepositoryStore(
            self.data_directory / "repositories.json",
            self.data_directory / "installed.json",
            self.data_directory / "sources",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary_directory)

    def write_index(self) -> None:
        index = build_index(self.repository_directory / "sources", self.index_path, "Test repository", self.repository_directory / "templates")
        self.index_path.write_text(json.dumps(index), encoding="utf-8")

    def entry(self, kind: EntryKind, identifier: str):
        index = fetch_index(self.index_url)
        return next(entry for entry in index.entries if entry.kind == kind and entry.identifier == identifier), index

    def test_index_lists_templates(self) -> None:
        self.write_index()
        index = fetch_index(self.index_url)
        self.assertEqual([(entry.kind, entry.identifier) for entry in index.entries],
                         [(EntryKind.SOURCE, "themed-site"), (EntryKind.TEMPLATE, "example-theme")])

    def test_index_build_fails_without_the_template(self) -> None:
        with self.assertRaisesRegex(RepositoryError, "not installed"):
            build_index(self.repository_directory / "sources", self.index_path, "Test repository")

    def test_source_installs_its_template(self) -> None:
        self.write_index()
        source_entry, index = self.entry(EntryKind.SOURCE, "themed-site")
        written = self.store.install(source_entry, index)
        self.assertEqual([entry.identifier for entry in written], ["example-theme", "themed-site"])
        self.assertTrue((self.data_directory / "templates" / "example-theme.toml").is_file())
        catalog = load_catalog(self.temporary_directory / "no-local-files", self.data_directory / "sources")
        self.assertEqual([loaded.source.identifier for loaded in catalog.loaded], ["themed-site"])
        template_entry, _ = self.entry(EntryKind.TEMPLATE, "example-theme")
        self.assertEqual(self.store.status_of(template_entry, self.index_url), EntryStatus.INSTALLED)

        reloaded = RepositoryStore(
            self.data_directory / "repositories.json", self.data_directory / "installed.json", self.data_directory / "sources"
        )
        self.assertEqual(sorted(reloaded.installed_templates), ["example-theme"])

    def test_template_update_is_shown(self) -> None:
        self.write_index()
        source_entry, index = self.entry(EntryKind.SOURCE, "themed-site")
        self.store.install(source_entry, index)
        template_file = self.repository_directory / "templates" / "example-theme.toml"
        template_file.write_text(template_file.read_text(encoding="utf-8").replace('version = "1.0.0"', 'version = "1.1.0"'), encoding="utf-8")
        self.write_index()
        template_entry, index = self.entry(EntryKind.TEMPLATE, "example-theme")
        self.assertEqual(self.store.status_of(template_entry, self.index_url), EntryStatus.UPDATE_AVAILABLE)
        self.store.install(template_entry, index)
        self.assertEqual(self.store.installed_templates["example-theme"].version, "1.1.0")

    def test_source_whose_template_is_not_listed_is_rejected(self) -> None:
        self.write_index()
        source_entry, index = self.entry(EntryKind.SOURCE, "themed-site")
        without_templates = RepositoryIndex(
            url=index.url, name=index.name, entries=[entry for entry in index.entries if entry.kind == EntryKind.SOURCE]
        )
        with self.assertRaisesRegex(RepositoryError, "does not list"):
            self.store.install(source_entry, without_templates)
        self.assertFalse((self.data_directory / "sources" / "themed-site.toml").exists())
        self.assertFalse((self.data_directory / "templates").exists())

    def test_bad_source_writes_no_template(self) -> None:
        source_file = self.repository_directory / "sources" / "themed-site.toml"
        self.write_index()
        source_entry, index = self.entry(EntryKind.SOURCE, "themed-site")
        source_file.write_text(source_file.read_text(encoding="utf-8").replace('version = "1.0.0"', 'version = "9.0.0"'), encoding="utf-8")
        changed_entry = replace(source_entry, sha256=hashlib.sha256(source_file.read_bytes()).hexdigest())
        with self.assertRaisesRegex(RepositoryError, "the index says"):
            self.store.install(changed_entry, index)
        self.assertFalse((self.data_directory / "templates").exists())


if __name__ == "__main__":
    unittest.main()

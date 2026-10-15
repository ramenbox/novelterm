import json
import shutil
import tempfile
import unittest
from pathlib import Path

from novelterm.repositories import EntryStatus, RepositoryError, RepositoryStore, build_index, fetch_index
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

        self.store.install(entry, self.index_url)
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
        self.store.install(updated_entry, self.index_url)
        self.assertEqual(self.store.installed["example-site"].version, "1.1.0")

        self.store.uninstall("example-site")
        self.assertEqual(self.store.status_of(updated_entry, self.index_url), EntryStatus.NOT_INSTALLED)
        self.assertEqual(list((self.data_directory / "sources").glob("*.toml")), [])

    def test_changed_file_is_rejected(self) -> None:
        entry = fetch_index(self.index_url).entries[0]
        self.source_file().write_text(self.source_file().read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        with self.assertRaises(RepositoryError) as context:
            self.store.install(entry, self.index_url)
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


if __name__ == "__main__":
    unittest.main()

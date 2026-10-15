import shutil
import tempfile
import unittest
from pathlib import Path

from novelterm.library import LibrarySort
from novelterm.settings import ReaderTheme, Settings, SettingsError, load_settings, next_in_cycle, parse_settings, save_settings


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary_directory)

    def test_missing_file_gives_defaults(self) -> None:
        self.assertEqual(load_settings(self.temporary_directory / "config.toml"), Settings())

    def test_round_trip(self) -> None:
        settings = Settings(line_width=100, theme=ReaderTheme.SEPIA, paragraph_spacing=0, library_sort=LibrarySort.TITLE)
        file_path = self.temporary_directory / "config.toml"
        save_settings(settings, file_path)
        self.assertEqual(load_settings(file_path), settings)

    def test_partial_file_uses_defaults_for_the_rest(self) -> None:
        self.assertEqual(parse_settings('[reader]\ntheme = "dark"\n'), Settings(theme=ReaderTheme.DARK))

    def test_errors_name_the_key(self) -> None:
        cases = {
            "line width too small": ("[reader]\nline_width = 10\n", "line_width"),
            "line width as text": ('[reader]\nline_width = "80"\n', "line_width"),
            "spacing as boolean": ("[reader]\nparagraph_spacing = true\n", "paragraph_spacing"),
            "unknown theme": ('[reader]\ntheme = "pink"\n', "theme"),
            "unknown sort": ('[library]\nsort = "random"\n', "sort"),
            "reader not a table": ('reader = 1\n', "reader"),
            "not toml": ("[reader\n", "TOML"),
        }
        for name, (content, expected) in cases.items():
            with self.subTest(name=name), self.assertRaises(SettingsError) as context:
                parse_settings(content)
            self.assertIn(expected, str(context.exception))

    def test_next_in_cycle(self) -> None:
        self.assertEqual(next_in_cycle((60, 80, 100), 80), 100)
        self.assertEqual(next_in_cycle((60, 80, 100), 100), 60)
        self.assertEqual(next_in_cycle((60, 80, 100), 90), 60)


if __name__ == "__main__":
    unittest.main()

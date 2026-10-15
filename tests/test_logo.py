import unittest

from novelterm.logo import BOOKMARK, FULL_WIDTH, ICON_WIDTH, LOGO_HEIGHT, NAME, PROMPT, LogoSize, logo_size


class LogoTests(unittest.TestCase):
    def test_parts_are_ascii_and_have_even_lines(self) -> None:
        for part in (PROMPT, BOOKMARK, NAME):
            self.assertEqual(len(part), LOGO_HEIGHT)
            self.assertEqual(len({len(line) for line in part}), 1)
            self.assertTrue(all(line.isascii() for line in part))

    def test_largest_logo_that_fits(self) -> None:
        enough_rows = LOGO_HEIGHT + 1
        self.assertEqual(logo_size(FULL_WIDTH + 4, enough_rows), LogoSize.FULL)
        self.assertEqual(logo_size(FULL_WIDTH + 3, enough_rows), LogoSize.ICON)
        self.assertEqual(logo_size(ICON_WIDTH + 4, enough_rows), LogoSize.ICON)
        self.assertIsNone(logo_size(ICON_WIDTH + 3, enough_rows))

    def test_no_logo_without_free_rows(self) -> None:
        self.assertIsNone(logo_size(200, LOGO_HEIGHT))


if __name__ == "__main__":
    unittest.main()

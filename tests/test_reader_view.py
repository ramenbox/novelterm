import unittest

from novelterm.reader_view import ReaderView

# 30 laid-out lines: text on even lines, empty odd lines.
LINES = [index % 2 == 0 for index in range(30)]


def view_at_start(visible_rows: int = 10) -> ReaderView:
    return ReaderView.at_fraction(LINES, visible_rows, 0.0)


class ReaderViewTests(unittest.TestCase):
    def test_pointer_starts_on_the_first_text_line(self) -> None:
        view = view_at_start()
        self.assertEqual((view.pointer_line, view.top_line, view.fraction), (0, 0, 0.0))

    def test_pointer_skips_empty_lines(self) -> None:
        self.assertEqual(view_at_start().line_down().pointer_line, 2)
        self.assertEqual(view_at_start().line_down().line_up().pointer_line, 0)

    def test_screen_scrolls_only_when_the_pointer_leaves_it(self) -> None:
        view = view_at_start()
        for _ in range(4):
            view = view.line_down()
        self.assertEqual((view.pointer_line, view.top_line), (8, 0))
        view = view.line_down()
        self.assertEqual((view.pointer_line, view.top_line), (10, 1))

    def test_page_down_puts_the_pointer_on_the_first_new_line(self) -> None:
        view = view_at_start().page_down()
        self.assertEqual((view.top_line, view.pointer_line), (8, 10))

    def test_page_up_puts_the_pointer_on_the_first_visible_text_line(self) -> None:
        view = view_at_start().page_down().page_down().page_up()
        self.assertEqual((view.top_line, view.pointer_line), (8, 8))

    def test_last_and_first(self) -> None:
        view = view_at_start().last()
        self.assertEqual((view.pointer_line, view.top_line, view.at_end, view.fraction), (28, 20, True, 1.0))
        self.assertEqual(view.first().pointer_line, 0)

    def test_saved_fraction_restores_the_pointer(self) -> None:
        view = ReaderView.at_fraction(LINES, 10, 0.5)
        self.assertEqual(view.pointer_line, 14)
        self.assertLessEqual(view.top_line, view.pointer_line)
        self.assertLess(view.pointer_line, view.top_line + 10)
        self.assertEqual(ReaderView.at_fraction(LINES, 10, view.fraction).pointer_line, 14)

    def test_pointer_stays_inside_the_chapter(self) -> None:
        self.assertEqual(view_at_start().line_up().pointer_line, 0)
        self.assertEqual(view_at_start().last().line_down().pointer_line, 28)

    def test_short_chapter_fits_on_one_screen(self) -> None:
        view = ReaderView.at_fraction([True, False, True, False, False], 10, 0.0)
        self.assertTrue(view.at_end)
        self.assertEqual(view.page_down().pointer_line, 2)


if __name__ == "__main__":
    unittest.main()

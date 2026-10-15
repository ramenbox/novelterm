import unittest
from dataclasses import replace

from novelterm.app import LayoutLine, image_notice, layout_chapter
from novelterm.models import Chapter
from novelterm.ui import ReaderAttributes


def chapter(paragraphs: list[str], image_count: int) -> Chapter:
    return Chapter(
        title="Chapter",
        url="https://example.org/novel/first/chapter-1",
        novel_url=None,
        paragraphs=paragraphs,
        previous_url=None,
        next_url=None,
        image_count=image_count,
    )


class ImageNoticeTests(unittest.TestCase):
    def test_no_images_no_notice(self) -> None:
        self.assertIsNone(image_notice(chapter(["Text."], 0)))

    def test_only_images(self) -> None:
        notice = image_notice(chapter([], 2)) or ""
        self.assertIn("only images (2)", notice)
        self.assertIn("https://example.org/novel/first/chapter-1", notice)

    def test_images_between_text(self) -> None:
        self.assertEqual(image_notice(chapter(["Text."], 1)), "1 image in this chapter not shown. novelterm shows text only.")

    def test_notice_is_below_the_title(self) -> None:
        attributes = ReaderAttributes(text=0, title=1, dim=2, accent=3)
        lines = layout_chapter(chapter(["Text."], 3), 80, 1, attributes)
        self.assertEqual(lines[2], LayoutLine("3 images in this chapter not shown. novelterm shows text only.", 2))

    def test_only_title_and_text_are_readable(self) -> None:
        attributes = ReaderAttributes(text=0, title=1, dim=1, accent=1)
        lines = layout_chapter(replace(chapter(["Text."], 1), next_url="https://example.org/novel/first/chapter-2"), 80, 1, attributes)
        self.assertEqual([line.text for line in lines if line.readable], ["Chapter", "Text."])


if __name__ == "__main__":
    unittest.main()

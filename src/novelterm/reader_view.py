"""The reading pointer and the visible part of a laid-out chapter.

The pointer is always on a line of chapter text or the chapter title. Empty
lines, notices and the end-of-chapter lines are skipped. The view
scrolls only as far as needed to keep the pointer on screen.
"""

from dataclasses import dataclass, replace

PAGE_OVERLAP_LINES = 2
"""Lines of the previous page that stay on screen after a page jump."""


@dataclass(frozen=True)
class ReaderView:
    text_lines: tuple[int, ...]
    """Indexes of the laid-out lines that the pointer can be on. Never empty."""
    line_count: int
    visible_rows: int
    pointer: int
    """Position in text_lines of the line the reader is on."""
    top_line: int
    """Index of the first visible laid-out line."""

    @classmethod
    def at_fraction(cls, readable: list[bool], visible_rows: int, fraction: float) -> "ReaderView":
        """A view with the pointer at a saved position: 0.0 is the first text line, 1.0 the last.

        readable has one value per laid-out line: True for a line that the pointer can be on.
        """
        text_lines = tuple(index for index, is_readable in enumerate(readable) if is_readable) or (0,)
        pointer = round(max(0.0, min(1.0, fraction)) * (len(text_lines) - 1))
        top_line = max(0, text_lines[pointer] - visible_rows // 3)
        view = cls(text_lines, len(readable), max(1, visible_rows), pointer, top_line)
        return view.with_pointer(pointer)

    @property
    def pointer_line(self) -> int:
        return self.text_lines[self.pointer]

    @property
    def last_top_line(self) -> int:
        return max(0, self.line_count - self.visible_rows)

    @property
    def at_end(self) -> bool:
        """The last line of the chapter is on screen."""
        return self.top_line >= self.last_top_line

    @property
    def fraction(self) -> float:
        """The pointer position from 0.0 (first text line) to 1.0 (last text line)."""
        last = len(self.text_lines) - 1
        return self.pointer / last if last else 1.0

    def with_top_line(self, top_line: int) -> "ReaderView":
        return replace(self, top_line=max(0, min(top_line, self.last_top_line)))

    def with_pointer(self, pointer: int) -> "ReaderView":
        """Move the pointer and scroll just enough to keep it on screen."""
        pointer = max(0, min(pointer, len(self.text_lines) - 1))
        line = self.text_lines[pointer]
        match line:
            case _ if line < self.top_line:
                top_line = line
            case _ if line >= self.top_line + self.visible_rows:
                top_line = line - self.visible_rows + 1
            case _:
                top_line = self.top_line
        return replace(self, pointer=pointer).with_top_line(top_line)

    def first_text_line_from(self, line: int) -> int:
        """Position of the first text line at or after a laid-out line. The last text line when there is none."""
        return next((position for position, index in enumerate(self.text_lines) if index >= line), len(self.text_lines) - 1)

    def line_down(self) -> "ReaderView":
        return self.with_pointer(self.pointer + 1)

    def line_up(self) -> "ReaderView":
        return self.with_pointer(self.pointer - 1)

    def page_down(self) -> "ReaderView":
        """Show the next page. The pointer goes to the first line that was not on screen."""
        first_new_line = self.top_line + self.visible_rows
        moved = self.with_top_line(self.top_line + max(1, self.visible_rows - PAGE_OVERLAP_LINES))
        return moved.with_pointer(moved.first_text_line_from(first_new_line))

    def page_up(self) -> "ReaderView":
        """Show the previous page. The pointer goes to the first text line on screen."""
        moved = self.with_top_line(self.top_line - max(1, self.visible_rows - PAGE_OVERLAP_LINES))
        return moved.with_pointer(moved.first_text_line_from(moved.top_line))

    def first(self) -> "ReaderView":
        return self.with_top_line(0).with_pointer(0)

    def last(self) -> "ReaderView":
        return self.with_top_line(self.last_top_line).with_pointer(len(self.text_lines) - 1)

"""The novelterm logo in ASCII for the Home screen: a prompt, a bookmark and the name.

Home shows the largest form that fits the terminal, so the menu always keeps its space.
"""

from enum import Enum, auto

PROMPT = (
    " __     ",
    " \\ \\    ",
    "  \\ \\   ",
    "  / /   ",
    " /_/    ",
)
BOOKMARK = (
    " _____ ",
    "|     |",
    "|     |",
    "|     |",
    "|__^__|",
)
NAME = (
    " _   _   ___  __     __ _____  _      _____  _____  ____   __  __ ",
    "| \\ | | / _ \\ \\ \\   / /| ____|| |    |_   _|| ____||  _ \\ |  \\/  |",
    "|  \\| || | | | \\ \\ / / |  _|  | |      | |  |  _|  | |_) || |\\/| |",
    "| |\\  || |_| |  \\ V /  | |___ | |___   | |  | |___ |  _ < | |  | |",
    "|_| \\_| \\___/    \\_/   |_____||_____|  |_|  |_____||_| \\_\\|_|  |_|",
)
NAME_GAP = "   "
LOGO_HEIGHT = len(PROMPT)
ICON_WIDTH = len(PROMPT[0]) + len(BOOKMARK[0])
FULL_WIDTH = ICON_WIDTH + len(NAME_GAP) + len(NAME[0])
SIDE_MARGIN = 2
"""Columns kept free on each side of the logo."""


class LogoSize(Enum):
    FULL = auto()
    """Icon and name."""
    ICON = auto()
    """Icon only."""


def logo_size(width: int, free_rows: int) -> LogoSize | None:
    """The largest logo that fits. free_rows are the rows that the screen does not need for other content.

    The logo needs its own rows plus one empty row below it. None when it does not fit.
    """
    match (width, free_rows):
        case (_, rows) if rows < LOGO_HEIGHT + 1:
            return None
        case (columns, _) if columns >= FULL_WIDTH + 2 * SIDE_MARGIN:
            return LogoSize.FULL
        case (columns, _) if columns >= ICON_WIDTH + 2 * SIDE_MARGIN:
            return LogoSize.ICON
        case _:
            return None

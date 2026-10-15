"""Curses building blocks: colors, keys, menus, messages and text input."""

import curses
import textwrap
from dataclasses import dataclass
from enum import Enum, auto

APP_NAME = "novelterm"


class ColorPair:
    HEADER = 1
    SELECTED = 2
    TITLE = 3
    ACCENT = 4
    DIM = 5
    ERROR = 6


def setup_colors() -> None:
    curses.curs_set(0)
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(ColorPair.HEADER, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(ColorPair.SELECTED, curses.COLOR_BLACK, curses.COLOR_YELLOW)
    curses.init_pair(ColorPair.TITLE, curses.COLOR_CYAN, -1)
    curses.init_pair(ColorPair.ACCENT, curses.COLOR_YELLOW, -1)
    curses.init_pair(ColorPair.DIM, curses.COLOR_WHITE, -1)
    curses.init_pair(ColorPair.ERROR, curses.COLOR_RED, -1)


def color(pair: int) -> int:
    return curses.color_pair(pair) if curses.has_colors() else 0


def dim() -> int:
    return color(ColorPair.DIM) | curses.A_DIM


class Key(Enum):
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    PAGE_UP = auto()
    PAGE_DOWN = auto()
    HOME = auto()
    END = auto()
    ENTER = auto()
    ESCAPE = auto()
    BACKSPACE = auto()
    RESIZE = auto()
    CHARACTER = auto()


@dataclass(frozen=True)
class KeyPress:
    key: Key
    character: str = ""


def read_key(screen: curses.window) -> KeyPress:
    pressed = screen.get_wch()
    match pressed:
        case curses.KEY_UP:
            return KeyPress(Key.UP)
        case curses.KEY_DOWN:
            return KeyPress(Key.DOWN)
        case curses.KEY_LEFT:
            return KeyPress(Key.LEFT)
        case curses.KEY_RIGHT:
            return KeyPress(Key.RIGHT)
        case curses.KEY_PPAGE:
            return KeyPress(Key.PAGE_UP)
        case curses.KEY_NPAGE:
            return KeyPress(Key.PAGE_DOWN)
        case curses.KEY_HOME:
            return KeyPress(Key.HOME)
        case curses.KEY_END:
            return KeyPress(Key.END)
        case curses.KEY_ENTER | "\n" | "\r":
            return KeyPress(Key.ENTER)
        case "\x1b":
            return KeyPress(Key.ESCAPE)
        case curses.KEY_BACKSPACE | "\x7f" | "\b":
            return KeyPress(Key.BACKSPACE)
        case curses.KEY_RESIZE:
            return KeyPress(Key.RESIZE)
        case str():
            return KeyPress(Key.CHARACTER, pressed)
        case _:
            return KeyPress(Key.CHARACTER, "")


def put(screen: curses.window, row: int, column: int, text: str, attributes: int = 0) -> None:
    """Write text and cut it at the screen edge, so curses never raises."""
    height, width = screen.getmaxyx()
    if not (0 <= row < height and 0 <= column < width):
        return
    try:
        screen.addnstr(row, column, text, width - column - (1 if row == height - 1 else 0), attributes)
    except curses.error:
        pass


def draw_bar(screen: curses.window, row: int, left: str, right: str = "") -> None:
    width = screen.getmaxyx()[1]
    bar = f" {left}".ljust(width)
    if right:
        bar = bar[: max(0, width - len(right) - 1)] + right + " "
    put(screen, row, 0, bar.ljust(width), color(ColorPair.HEADER) | curses.A_BOLD)


def draw_footer(screen: curses.window, text: str, attributes: int | None = None) -> None:
    height = screen.getmaxyx()[0]
    put(screen, height - 1, 1, text, dim() if attributes is None else attributes)


class ItemStyle(Enum):
    NORMAL = auto()
    ACCENT = auto()
    DIM = auto()


@dataclass(frozen=True)
class MenuItem:
    label: str
    value: object
    hint: str = ""
    style: ItemStyle = ItemStyle.NORMAL


@dataclass(frozen=True)
class Selected:
    value: object


@dataclass(frozen=True)
class WentBack:
    pass


MenuResult = Selected | WentBack

MENU_HINT = "Up/Down move | Enter open | <- back"
TOP_LEVEL_HINT = "Up/Down move | Enter open"
FILTER_HINT = "Up/Down move | Enter open | / search | <- back"


def item_attributes(style: ItemStyle) -> int:
    match style:
        case ItemStyle.NORMAL:
            return 0
        case ItemStyle.ACCENT:
            return color(ColorPair.ACCENT) | curses.A_BOLD
        case ItemStyle.DIM:
            return dim()


def run_menu(
    screen: curses.window,
    breadcrumb: str,
    title: str,
    intro_lines: list[str],
    items: list[MenuItem],
    initial_index: int = 0,
    searchable: bool = False,
    top_level_notice: str | None = None,
) -> MenuResult:
    """Show a list. The user picks one item with the arrow keys and Enter, or goes back.

    With top_level_notice set, the back keys show that notice and do not leave the menu.
    This stops a quick double "back" from closing the app.
    """
    selected_index = max(0, min(initial_index, len(items) - 1))
    first_visible_index = 0
    search_text = ""
    typing_search = False
    notice = ""

    while True:
        visible_items = [item for item in items if search_text.lower() in item.label.lower()]
        selected_index = max(0, min(selected_index, len(visible_items) - 1))

        screen.erase()
        height, width = screen.getmaxyx()
        draw_bar(screen, 0, APP_NAME, breadcrumb)
        row = 2
        put(screen, row, 2, title, color(ColorPair.TITLE) | curses.A_BOLD)
        row += 1
        text_width = max(20, min(width - 4, 90))
        for line in intro_lines:
            for wrapped in textwrap.wrap(line, text_width) or [""]:
                row += 1
                put(screen, row, 2, wrapped)
        row += 2

        list_height = max(1, height - row - 2)
        if selected_index < first_visible_index:
            first_visible_index = selected_index
        if selected_index >= first_visible_index + list_height:
            first_visible_index = selected_index - list_height + 1
        first_visible_index = max(0, min(first_visible_index, max(0, len(visible_items) - list_height)))

        for offset, item in enumerate(visible_items[first_visible_index : first_visible_index + list_height]):
            index = first_visible_index + offset
            is_selected = index == selected_index
            line_row = row + offset
            if is_selected:
                put(screen, line_row, 1, " " * (width - 2), color(ColorPair.SELECTED))
                put(screen, line_row, 2, f"> {item.label}", color(ColorPair.SELECTED) | curses.A_BOLD)
            else:
                put(screen, line_row, 2, f"  {item.label}", item_attributes(item.style))
            if item.hint:
                hint_column = max(len(item.label) + 6, width - len(item.hint) - 3)
                hint_attributes = color(ColorPair.SELECTED) if is_selected else dim()
                put(screen, line_row, hint_column, item.hint, hint_attributes)

        if not visible_items:
            put(screen, row, 4, "Nothing matches your search.", dim())
        if len(visible_items) > list_height:
            position = f"{selected_index + 1}/{len(visible_items)}"
            put(screen, height - 1, width - len(position) - 2, position, dim())

        match (typing_search, search_text, notice):
            case (_, _, str(text)) if text:
                draw_footer(screen, text, color(ColorPair.ACCENT))
            case (True, _, _):
                draw_footer(screen, f"Search: {search_text}_  (Enter done | Esc clear)", color(ColorPair.ACCENT))
            case (False, str(text), _) if text:
                draw_footer(screen, f"Search: {text}  (/ change | Esc clear) | <- back", color(ColorPair.ACCENT))
            case _ if top_level_notice:
                draw_footer(screen, TOP_LEVEL_HINT)
            case _:
                draw_footer(screen, FILTER_HINT if searchable else MENU_HINT)
        screen.refresh()

        notice = ""
        pressed = read_key(screen)
        match (typing_search, pressed):
            case (_, KeyPress(Key.UP)):
                selected_index = max(0, selected_index - 1)
            case (_, KeyPress(Key.DOWN)):
                selected_index = min(len(visible_items) - 1, selected_index + 1)
            case (_, KeyPress(Key.PAGE_UP)):
                selected_index = max(0, selected_index - list_height)
            case (_, KeyPress(Key.PAGE_DOWN)):
                selected_index = min(len(visible_items) - 1, selected_index + list_height)
            case (_, KeyPress(Key.HOME)):
                selected_index = 0
            case (_, KeyPress(Key.END)):
                selected_index = len(visible_items) - 1
            case (_, KeyPress(Key.RESIZE)):
                pass
            case (True, KeyPress(Key.ENTER)):
                typing_search = False
            case (True, KeyPress(Key.ESCAPE)):
                typing_search = False
                search_text = ""
            case (True, KeyPress(Key.BACKSPACE)):
                search_text = search_text[:-1]
            case (True, KeyPress(Key.CHARACTER, character)) if character.isprintable():
                search_text += character
                selected_index = 0
            case (True, _):
                pass
            case (False, KeyPress(Key.ENTER) | KeyPress(Key.RIGHT)) if visible_items:
                return Selected(visible_items[selected_index].value)
            case (False, KeyPress(Key.ESCAPE)) if search_text:
                search_text = ""
            case (False, KeyPress(Key.LEFT) | KeyPress(Key.ESCAPE) | KeyPress(Key.BACKSPACE) | KeyPress(Key.CHARACTER, "q")):
                match top_level_notice:
                    case str():
                        notice = top_level_notice
                    case None:
                        return WentBack()
            case (False, KeyPress(Key.CHARACTER, "k")):
                selected_index = max(0, selected_index - 1)
            case (False, KeyPress(Key.CHARACTER, "j")):
                selected_index = min(len(visible_items) - 1, selected_index + 1)
            case (False, KeyPress(Key.CHARACTER, "/")) if searchable:
                typing_search = True
            case _:
                pass


def show_loading(screen: curses.window, message: str) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    draw_bar(screen, 0, APP_NAME)
    put(screen, height // 2, max(0, (width - len(message)) // 2), message, color(ColorPair.ACCENT))
    screen.refresh()


def show_message(screen: curses.window, title: str, lines: list[str], is_error: bool = False) -> None:
    """Show a message. Any key closes it."""
    screen.erase()
    height, width = screen.getmaxyx()
    draw_bar(screen, 0, APP_NAME)
    title_attributes = (color(ColorPair.ERROR) if is_error else color(ColorPair.TITLE)) | curses.A_BOLD
    put(screen, 2, 2, title, title_attributes)
    row = 4
    for line in lines:
        for wrapped in textwrap.wrap(line, max(20, min(width - 4, 90))) or [""]:
            put(screen, row, 2, wrapped)
            row += 1
    draw_footer(screen, "Press any key to go back")
    screen.refresh()
    read_key(screen)


def ask_text(screen: curses.window, title: str, prompt_lines: list[str]) -> str | None:
    """Ask for one line of text. Returns None when the user cancels with Esc."""
    typed = ""
    curses.curs_set(1)
    try:
        while True:
            screen.erase()
            draw_bar(screen, 0, APP_NAME)
            put(screen, 2, 2, title, color(ColorPair.TITLE) | curses.A_BOLD)
            row = 4
            width = screen.getmaxyx()[1]
            for line in prompt_lines:
                for wrapped in textwrap.wrap(line, max(20, min(width - 4, 90))) or [""]:
                    put(screen, row, 2, wrapped)
                    row += 1
            visible_typed = typed[-(width - 6) :]
            put(screen, row + 1, 2, "> ", color(ColorPair.ACCENT) | curses.A_BOLD)
            put(screen, row + 1, 4, visible_typed)
            draw_footer(screen, "Enter confirm | Esc cancel")
            screen.move(row + 1, min(width - 2, 4 + len(visible_typed)))
            screen.refresh()
            pressed = read_key(screen)
            match pressed:
                case KeyPress(Key.ENTER):
                    return typed.strip()
                case KeyPress(Key.ESCAPE):
                    return None
                case KeyPress(Key.BACKSPACE):
                    typed = typed[:-1]
                case KeyPress(Key.CHARACTER, character) if character.isprintable():
                    typed += character
                case _:
                    pass
    finally:
        curses.curs_set(0)

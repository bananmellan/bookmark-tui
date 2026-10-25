"""Curses rendering layer for bookmark-tui.

Thin: it renders screen dataclasses from app.py and translates
keystrokes into the symbolic key names the App controller understands.
All behavior lives in app.py; this module only draws.

The search bar is centered: as you type, the prompt stays in the
middle of the screen.

Key bindings:
- enter: Return, Ctrl+m or Ctrl+j — open URL (in list/detail)
- back/quit: Esc or Ctrl+l
- up/down: arrow keys, Ctrl+p / Ctrl+n (emacs style)
- left/right: arrow keys (cursor movement in edit form)
- quit: Ctrl+c
- details: Ctrl+o (in list)
- add: Ctrl+a or Tab (in list)
- edit: e (in detail); delete: d (in detail)
- save: Ctrl+s or Enter on last field (in edit form)
"""

from __future__ import annotations

import curses
import locale

from .app import (
    App,
    ConfirmScreen,
    DetailScreen,
    EditScreen,
    ListScreen,
    OpenRequested,
    QuitRequested,
    EDIT_FIELDS,
)
from .models import Bookmark

_ITEM_HEIGHT = 2
_LIST_TOP = 3
_INDENT = "  "

_PAIR_TITLE = 1
_PAIR_URL = 2
_PAIR_CATEGORY = 3
_PAIR_PROMPT = 4
_PAIR_DIM = 5
_PAIR_SELECTED = 6
_COLORS_READY = False


def _init_colors() -> None:
    global _COLORS_READY
    if _COLORS_READY or not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    if curses.COLORS < 8:
        return
    curses.init_pair(_PAIR_TITLE, curses.COLOR_WHITE, bg)
    curses.init_pair(_PAIR_URL, curses.COLOR_BLUE, bg)
    curses.init_pair(_PAIR_CATEGORY, curses.COLOR_MAGENTA, bg)
    curses.init_pair(_PAIR_PROMPT, curses.COLOR_YELLOW, bg)
    curses.init_pair(_PAIR_DIM, curses.COLOR_CYAN, bg)
    curses.init_pair(_PAIR_SELECTED, curses.COLOR_BLACK, curses.COLOR_GREEN)
    _COLORS_READY = True


def _pair(n: int) -> int:
    return curses.color_pair(n) if _COLORS_READY else 0


def _sel_attr() -> int:
    """Selection highlight: black on green when colors are available,
    plain reverse video otherwise — high contrast either way."""
    if _COLORS_READY:
        return _pair(_PAIR_SELECTED)
    return curses.A_REVERSE


def _key_name(ch: int) -> str:
    if ch == curses.KEY_UP:
        return "up"
    if ch == curses.KEY_DOWN:
        return "down"
    if ch == curses.KEY_LEFT:
        return "left"
    if ch == curses.KEY_RIGHT:
        return "right"
    if ch == curses.KEY_PPAGE:
        return "pageup"
    if ch == curses.KEY_NPAGE:
        return "pagedown"
    if ch == curses.KEY_HOME:
        return "home"
    if ch == curses.KEY_END:
        return "end"
    if ch in (10, 13, curses.KEY_ENTER):
        return "enter"
    if ch == 27:
        return "esc"
    if ch == 12:
        return "esc"  # Ctrl+l
    if ch in (curses.KEY_BACKSPACE, 127, 8):
        return "backspace"
    if ch == 9:
        return "tab"
    if ch == 3:
        return "ctrl_c"
    if ch == 14:
        return "down"  # Ctrl+n
    if ch == 16:
        return "up"  # Ctrl+p
    if ch == 1:
        return "ctrl_a"  # Ctrl+a: add new
    if ch == 15:
        return "ctrl_o"  # Ctrl+o: open detail view
    if ch == 19:
        return "ctrl_s"  # Ctrl+s: save
    if 32 <= ch < 127:
        return chr(ch)
    if 0 < ch < 32:
        return f"ctrl_{chr(ch + 96)}"
    return ""


def _read_key(stdscr) -> str:
    """Read one key, reassembling multibyte UTF-8 input."""
    ch = stdscr.getch()
    if ch == -1:
        return ""
    if not (128 <= ch < 256):
        return _key_name(ch)
    raw = bytearray([ch])
    if ch & 0xE0 == 0xC0:
        needed = 1
    elif ch & 0xF0 == 0xE0:
        needed = 2
    elif ch & 0xF8 == 0xF0:
        needed = 3
    else:
        return ""
    for _ in range(needed):
        nxt = stdscr.getch()
        if nxt == -1 or not (128 <= nxt < 256) or nxt & 0xC0 != 0x80:
            return ""
        raw.append(nxt)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def _put(stdscr, y: int, x: int, text: str, attr: int) -> None:
    """Write text at (y, x), clipped to the screen edge."""
    height, width = stdscr.getmaxyx()
    if y < 0 or y >= height or x >= width - 1:
        return
    last_col = width - 2 if y == height - 1 else width - 1
    room = max(0, min(len(text), last_col - x))
    try:
        stdscr.addnstr(y, x, text, room, attr)
    except curses.error:
        pass


def _put_centered(stdscr, y: int, text: str, attr: int) -> None:
    """Write text centered horizontally on row y."""
    height, width = stdscr.getmaxyx()
    if y < 0 or y >= height:
        return
    x = max(0, (width - len(text)) // 2)
    _put(stdscr, y, x, text, attr)


def _draw_list(stdscr, app: App) -> None:
    screen = app.screen
    assert isinstance(screen, ListScreen)
    height, width = stdscr.getmaxyx()
    list_height = max(1, (height - 1 - _LIST_TOP) // _ITEM_HEIGHT)
    app._clamp(screen, list_height)

    stdscr.erase()

    # Centered search bar
    prompt = f"> {screen.query}"
    _put_centered(stdscr, 0, prompt, _pair(_PAIR_PROMPT))

    visible = screen.visible

    if not screen.query.strip():
        hint = "type to search"
        _put_centered(stdscr, _LIST_TOP, hint, curses.A_DIM)
    else:
        title_attr = _pair(_PAIR_TITLE)
        url_attr = _pair(_PAIR_URL)
        cat_attr = _pair(_PAIR_CATEGORY)
        sel_attr = _sel_attr()
        avail = max(1, width - 1 - len(_INDENT))

        for row in range(list_height):
            idx = screen.offset + row
            if idx >= len(visible):
                break
            bm = visible[idx]
            is_selected = idx == screen.selected

            y_title = _LIST_TOP + row * _ITEM_HEIGHT
            y_url = y_title + 1

            if is_selected:
                # Paint the selection bar across the full row width so the
                # highlight reads as a solid bar, not just the text. The
                # text itself uses the selection pair so it stays readable
                # (black on green, or reverse video without colors).
                bar = " " * (width - 1)
                _put(stdscr, y_title, 0, bar, sel_attr)
                _put(stdscr, y_url, 0, bar, sel_attr)
                _put(stdscr, y_title, 2, _truncate(bm.title or bm.url, avail), sel_attr)
                _put(stdscr, y_url, 2, _truncate(bm.url, avail), sel_attr)
                if bm.category:
                    cat_text = _truncate(f"  [{bm.category}]", avail)
                    _put(stdscr, y_url, max(2, width - len(cat_text) - 1), cat_text, sel_attr)
                continue

            _put(stdscr, y_title, 2, _truncate(bm.title or bm.url, avail), title_attr)
            _put(stdscr, y_url, 2, _truncate(bm.url, avail), url_attr)
            if bm.category:
                cat_text = _truncate(f"  [{bm.category}]", avail)
                _put(stdscr, y_url, max(2, width - len(cat_text) - 1), cat_text, cat_attr)

    # Status bar
    status = f"{len(visible)}/{len(screen.bookmarks)} bookmarks"
    if screen.message:
        status = f"{screen.message}  —  {status}"
    status += "  ·  enter: open  ctrl-o: details  ctrl-a/tab: add  esc: quit"
    _put(stdscr, height - 1, 0, _truncate(status, width - 1), curses.A_DIM)

    # Position cursor in the centered search bar
    prompt_len = len(prompt)
    cursor_x = max(0, (width - prompt_len) // 2) + prompt_len
    stdscr.move(0, min(cursor_x, width - 1))
    stdscr.refresh()


def _draw_detail(stdscr, app: App) -> None:
    screen = app.screen
    assert isinstance(screen, DetailScreen)
    height, width = stdscr.getmaxyx()
    bm = screen.bookmark

    stdscr.erase()
    if bm is None:
        _put(stdscr, 0, 0, "No bookmark selected", curses.A_BOLD)
        _put(stdscr, height - 1, 0, "esc: back", curses.A_DIM)
        stdscr.refresh()
        return

    title = bm.title or "(untitled)"
    _put(stdscr, 0, 0, _truncate(title, width - 1), curses.A_BOLD | _pair(_PAIR_TITLE))
    _put(stdscr, 1, 0, _truncate(f"#{bm.id}", width - 1), curses.A_DIM)

    fields = [
        ("URL", bm.url),
        ("Title", bm.title),
        ("Category", bm.category or "(none)"),
    ]
    label_w = max(len(label) for label, _ in fields) + 2
    for i, (label, value) in enumerate(fields):
        y = 3 + i * 2
        _put(stdscr, y, 2, label.ljust(label_w), curses.A_BOLD | _pair(_PAIR_CATEGORY))
        _put(stdscr, y, 2 + label_w, _truncate(value, width - label_w - 4), curses.A_NORMAL)

    if screen.message:
        _put(stdscr, height - 2, 0, _truncate(screen.message, width - 1), _pair(_PAIR_PROMPT))
    status = "enter: open URL  e: edit  d: delete  ctrl-a: add  esc: back"
    _put(stdscr, height - 1, 0, _truncate(status, width - 1), curses.A_DIM)
    stdscr.refresh()


def _draw_edit(stdscr, app: App) -> None:
    screen = app.screen
    assert isinstance(screen, EditScreen)
    height, width = stdscr.getmaxyx()
    app._clamp(screen, 0)

    stdscr.erase()
    header = "Add bookmark" if screen.is_new else "Edit bookmark"
    _put(stdscr, 0, 0, _truncate(header, width - 1), curses.A_BOLD)

    labels = {"url": "URL", "title": "Title", "category": "Category"}
    label_w = max(len(v) for v in labels.values()) + 2

    for i, field_name in enumerate(EDIT_FIELDS):
        y = 2 + i * 2
        is_current = i == screen.field_idx
        base = curses.A_REVERSE if is_current else curses.A_NORMAL
        label = labels[field_name]
        _put(stdscr, y, 2, label.ljust(label_w), base | curses.A_BOLD | _pair(_PAIR_CATEGORY))
        value = screen.values.get(field_name, "")
        _put(stdscr, y, 2 + label_w, _truncate(value, width - label_w - 4), base)

    if screen.message:
        _put(stdscr, height - 2, 0, _truncate(screen.message, width - 1), _pair(_PAIR_PROMPT))
    status = "tab/enter: next field  ctrl-s: save  esc: cancel"
    _put(stdscr, height - 1, 0, _truncate(status, width - 1), curses.A_DIM)

    # Position cursor at the current field value
    field_row = 2 + screen.field_idx * 2
    cursor_x = 2 + label_w + screen.cursor
    stdscr.move(field_row, min(cursor_x, width - 1))
    stdscr.refresh()


def _draw_confirm(stdscr, app: App) -> None:
    screen = app.screen
    assert isinstance(screen, ConfirmScreen)
    height, width = stdscr.getmaxyx()

    stdscr.erase()
    bm = screen.bookmark
    title = bm.title if bm else "?"
    url = bm.url if bm else ""
    _put(stdscr, 0, 0, _truncate(f"Delete: {title}", width - 1), curses.A_BOLD)
    _put(stdscr, 1, 0, _truncate(url, width - 1), _pair(_PAIR_URL))

    _put(stdscr, 3, 2, "Are you sure?", curses.A_NORMAL)
    yes_attr = curses.A_REVERSE if screen.selected == 0 else curses.A_NORMAL
    no_attr = curses.A_REVERSE if screen.selected == 1 else curses.A_NORMAL
    _put(stdscr, 5, 4, "Yes", yes_attr)
    _put(stdscr, 5, 12, "No", no_attr)

    if screen.message:
        _put(stdscr, height - 2, 0, _truncate(screen.message, width - 1), _pair(_PAIR_PROMPT))
    _put(stdscr, height - 1, 0, _truncate("enter/y: confirm  n/esc: cancel  ←→: select", width - 1), curses.A_DIM)
    stdscr.refresh()


def run(app: App) -> Bookmark | None:
    """Run the curses event loop. Returns the bookmark to open, or None
    when the user quit without selecting."""
    locale.setlocale(locale.LC_ALL, "")
    app.start()
    return curses.wrapper(_loop, app)


def _loop(stdscr, app: App) -> Bookmark | None:
    curses.curs_set(1)
    stdscr.keypad(True)
    stdscr.nodelay(False)
    _init_colors()
    while True:
        screen = app.screen
        if isinstance(screen, ListScreen):
            _draw_list(stdscr, app)
        elif isinstance(screen, DetailScreen):
            _draw_detail(stdscr, app)
        elif isinstance(screen, EditScreen):
            _draw_edit(stdscr, app)
        elif isinstance(screen, ConfirmScreen):
            _draw_confirm(stdscr, app)
        try:
            name = _read_key(stdscr)
        except KeyboardInterrupt:
            return None
        if not name:
            continue
        try:
            app.handle_key(name)
        except OpenRequested as exc:
            return exc.bookmark
        except QuitRequested:
            return None
        except KeyboardInterrupt:
            return None

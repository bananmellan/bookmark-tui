"""Curses rendering layer for buku-tui.

Thin: it renders screen dataclasses from app.py and translates
keystrokes into the symbolic key names the App controller understands.
All behavior lives in app.py; this module only draws.

Key bindings:
- enter: Return, Ctrl+m or Ctrl+j — open URL (in list/detail)
- back/quit: Esc or Ctrl+l
- up/down: arrow keys, Ctrl+p / Ctrl+n (emacs style)
- left/right: arrow keys (cursor movement in edit form)
- refresh: Ctrl+r; quit: Ctrl+c
- details: Ctrl+o (in list)
- add: Ctrl+a or Tab (in list)
- edit: e (in detail); delete: d (in detail)
- save: Ctrl+s or Enter on last field (in edit form)

The list renders three-line blocks (title, url, tags) so rows line up;
columns are colored when the terminal supports colors.
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
from .models import BookmarkRef

_ITEM_HEIGHT = 3
_LIST_TOP = 2
_INDENT = "  "

_PAIR_TITLE = 1
_PAIR_URL = 2
_PAIR_TAGS = 3
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
    curses.init_pair(_PAIR_TAGS, curses.COLOR_MAGENTA, bg)
    curses.init_pair(_PAIR_PROMPT, curses.COLOR_YELLOW, bg)
    curses.init_pair(_PAIR_DIM, curses.COLOR_CYAN, bg)
    curses.init_pair(_PAIR_SELECTED, curses.COLOR_GREEN, bg)
    _COLORS_READY = True


def _pair(n: int) -> int:
    return curses.color_pair(n) if _COLORS_READY else 0


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
    if ch == 18:
        return "ctrl_r"
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
    return text[: width - 1] + "\u2026"


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


def _draw_list(stdscr, app: App) -> None:
    screen = app.screen
    assert isinstance(screen, ListScreen)
    height, width = stdscr.getmaxyx()
    list_height = max(1, (height - 1 - _LIST_TOP) // _ITEM_HEIGHT)
    app._clamp(screen, list_height)

    stdscr.erase()
    header = "buku"
    if screen.host_filter:
        header += f"  ({screen.host_filter})"
    _put(stdscr, 0, 0, _truncate(header, width - 1), curses.A_BOLD)

    prompt = f"> {screen.query}"
    _put(stdscr, 1, 0, _truncate(prompt, width - 1), _pair(_PAIR_PROMPT))

    visible = screen.visible
    title_attr = _pair(_PAIR_TITLE)
    url_attr = _pair(_PAIR_URL)
    tags_attr = _pair(_PAIR_TAGS)
    avail = max(1, width - 1 - len(_INDENT))

    for row in range(list_height):
        idx = screen.offset + row
        if idx >= len(visible):
            break
        ref = visible[idx]
        y = _LIST_TOP + row * _ITEM_HEIGHT
        selected = idx == screen.selected
        base = curses.A_REVERSE if selected else curses.A_NORMAL

        _put(stdscr, y, 0, _truncate(ref.title, avail), base | title_attr)
        _put(stdscr, y + 1, 0, _truncate(_INDENT + ref.url, avail), base | url_attr)
        tags = ",".join(ref.tags)
        if tags:
            _put(stdscr, y + 2, 0, _truncate(_INDENT + tags, avail), base | tags_attr)
        else:
            _put(stdscr, y + 2, 0, " " * min(avail, width - 1), base)

    if not screen.query.strip():
        hint = "type to search bookmarks  \u00b7  ctrl-a: add"
        _put(stdscr, _LIST_TOP, 0, _truncate(hint, width - 1), curses.A_DIM)

    status = f"{len(visible)}/{len(screen.refs)} bookmarks"
    if screen.message:
        status = f"{screen.message}  \u2014  {status}"
    status += "  \u00b7  enter: open URL  ctrl-o: details  ctrl-a/tab: add  esc/ctrl-l: quit  ctrl-r: refresh"
    _put(stdscr, height - 1, 0, _truncate(status, width - 1), curses.A_DIM)
    stdscr.move(1, min(2 + len(screen.query), width - 1))
    stdscr.refresh()


def _draw_detail(stdscr, app: App) -> None:
    screen = app.screen
    assert isinstance(screen, DetailScreen)
    height, width = stdscr.getmaxyx()
    ref = screen.ref

    stdscr.erase()
    if ref is not None:
        title = ref.title or ref.url
        _put(stdscr, 0, 0, _truncate(title, width - 1), curses.A_BOLD | _pair(_PAIR_TITLE))
    else:
        _put(stdscr, 0, 0, "Bookmark", curses.A_BOLD)

    if ref is None:
        _put(stdscr, height - 1, 0, "esc: back", curses.A_DIM)
        stdscr.refresh()
        return

    y = 2
    fields = [
        ("URL", ref.url),
        ("Title", ref.title or "(none)"),
        ("Tags", ", ".join(ref.tags) if ref.tags else "(none)"),
        ("Desc", ref.description or "(none)"),
        ("Index", f"#{ref.index}"),
    ]
    label_w = max(len(label) for label, _ in fields)
    for label, value in fields:
        _put(stdscr, y, 0, label.ljust(label_w), curses.A_BOLD | _pair(_PAIR_TAGS))
        _put(stdscr, y, label_w + 2, _truncate(value, width - label_w - 3), _pair(_PAIR_TITLE))
        y += 1
        if y >= height - 2:
            break

    if screen.message:
        _put(stdscr, height - 2, 0, _truncate(screen.message, width - 1), _pair(_PAIR_PROMPT))
    status = "enter: open URL  e: edit  d: delete  ctrl-a: add  esc/ctrl-l: back"
    _put(stdscr, height - 1, 0, _truncate(status, width - 1), curses.A_DIM)
    stdscr.refresh()


_FIELD_LABELS = {
    "url": "URL",
    "title": "Title",
    "tags": "Tags",
    "desc": "Description",
}


def _draw_edit(stdscr, app: App) -> None:
    screen = app.screen
    assert isinstance(screen, EditScreen)
    height, width = stdscr.getmaxyx()
    app._clamp(screen, height)

    stdscr.erase()
    header = "Edit bookmark" if not screen.is_new else "Add bookmark"
    _put(stdscr, 0, 0, _truncate(header, width - 1), curses.A_BOLD)

    y = 2
    label_w = max(len(_FIELD_LABELS[f]) for f in EDIT_FIELDS)
    for i, field_name in enumerate(EDIT_FIELDS):
        label = _FIELD_LABELS[field_name]
        value = screen.values.get(field_name, "")
        is_current = i == screen.field_idx
        base = curses.A_REVERSE if is_current else curses.A_NORMAL

        _put(stdscr, y, 0, label.ljust(label_w), base | curses.A_BOLD | _pair(_PAIR_TAGS))
        _put(stdscr, y, label_w + 2, _truncate(value, width - label_w - 3), base | _pair(_PAIR_TITLE))
        y += 1
        if y >= height - 3:
            break

    if screen.message:
        _put(stdscr, height - 2, 0, _truncate(screen.message, width - 1), _pair(_PAIR_PROMPT))

    is_last = screen.field_idx == len(EDIT_FIELDS) - 1
    if is_last:
        status = "enter/ctrl-s: save  esc: cancel  \u2191\u2193: navigate"
    else:
        status = "enter/tab: next  \u2191\u2193: navigate  esc: cancel"
    _put(stdscr, height - 1, 0, _truncate(status, width - 1), curses.A_DIM)

    value = screen.current_value
    cursor_x = label_w + 2 + screen.cursor
    stdscr.move(2 + screen.field_idx, min(cursor_x, width - 1))
    stdscr.refresh()


def _draw_confirm(stdscr, app: App) -> None:
    screen = app.screen
    assert isinstance(screen, ConfirmScreen)
    height, width = stdscr.getmaxyx()

    stdscr.erase()
    if screen.ref is not None:
        title = screen.ref.title or screen.ref.url
        _put(stdscr, 0, 0, _truncate(f"Delete: {title}", width - 1), curses.A_BOLD)
        _put(stdscr, 1, 0, _truncate(screen.ref.url, width - 1), _pair(_PAIR_URL))

    _put(stdscr, 3, 0, _truncate("Are you sure? (y/n)", width - 1), _pair(_PAIR_PROMPT))

    yes_attr = curses.A_REVERSE if screen.selected == 0 else curses.A_NORMAL
    no_attr = curses.A_REVERSE if screen.selected == 1 else curses.A_NORMAL
    _put(stdscr, 5, 4, " Yes ", yes_attr | _pair(_PAIR_SELECTED))
    _put(stdscr, 5, 12, " No ", no_attr)

    if screen.message:
        _put(stdscr, height - 2, 0, _truncate(screen.message, width - 1), _pair(_PAIR_PROMPT))
    _put(stdscr, height - 1, 0, _truncate("enter/y: confirm  n/esc: cancel  \u2190\u2192: select", width - 1), curses.A_DIM)
    stdscr.refresh()


def run(app: App) -> BookmarkRef | None:
    """Run the curses event loop. Returns the bookmark to open, or None
    when the user quit without selecting."""
    locale.setlocale(locale.LC_ALL, "")
    app.start()
    return curses.wrapper(_loop, app)


def _loop(stdscr, app: App) -> BookmarkRef | None:
    curses.curs_set(1)
    stdscr.keypad(True)
    stdscr.timeout(80)
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
            return exc.ref
        except QuitRequested:
            return None
        except KeyboardInterrupt:
            return None

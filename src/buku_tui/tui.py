"""Curses rendering layer for buku-tui.

Thin: it renders :class:`~buku_tui.app.ListScreen` values and translates
keystrokes into the symbolic key names the App controller understands.
All behavior lives in app.py; this module only draws.

Key bindings (in addition to the arrow keys, page up/down, home/end):

- enter: ``Return``, ``Ctrl+m`` or ``Ctrl+j`` — open the bookmark
- quit: ``Esc`` or ``Ctrl+l`` (Esc first clears the search query)
- up/down: arrow keys, ``Ctrl+p`` / ``Ctrl+n`` (emacs style)
- refresh: ``Ctrl+r``; quit: ``Ctrl+c``

The list renders fixed-width columns (title, url, tags) so rows line up;
columns are colored when the terminal supports colors.
"""

from __future__ import annotations

import curses
import locale

from .app import App, OpenRequested, QuitRequested
from .models import BookmarkRef

# Each bookmark renders as a three-line block: title, url, tags.
_ITEM_HEIGHT = 3
_LIST_TOP = 2  # first item row (below the header and the prompt)
_INDENT = "  "

# Color pairs (initialized in _loop when the terminal supports colors).
_PAIR_TITLE = 1
_PAIR_URL = 2
_PAIR_TAGS = 3
_PAIR_PROMPT = 4
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
    _COLORS_READY = True


def _pair(n: int) -> int:
    """Color-pair attribute, or 0 when colors are unavailable (tests)."""
    return curses.color_pair(n) if _COLORS_READY else 0


def _key_name(ch: int) -> str:
    if ch == curses.KEY_UP:
        return "up"
    if ch == curses.KEY_DOWN:
        return "down"
    if ch == curses.KEY_PPAGE:
        return "pageup"
    if ch == curses.KEY_NPAGE:
        return "pagedown"
    if ch == curses.KEY_HOME:
        return "home"
    if ch == curses.KEY_END:
        return "end"
    if ch in (10, 13, curses.KEY_ENTER):
        # 10 = Ctrl+j (line feed), 13 = Ctrl+m (carriage return)
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
    if 32 <= ch < 127:
        return chr(ch)
    if 0 < ch < 32:
        return f"ctrl_{chr(ch + 96)}"
    return ""


def _read_key(stdscr) -> str:
    """Read one key, reassembling multibyte UTF-8 input.

    curses' getch() returns one byte at a time for non-ASCII input, so
    a character like 'å' (0xC3 0xA5) arrives as two key events. Collect
    the continuation bytes of a UTF-8 sequence and decode the whole
    character before handing it to the controller, so search accepts
    å/ä/ö and any other non-ASCII text.

    A timeout window (set on the window) bounds every read: -1 means
    "nothing arrived in time", a lone 27 is the Esc key (the escape
    timeout expired with no sequence bytes), and anything else is either
    a special key (arrows etc., already decoded by keypad mode) or the
    start of a UTF-8 sequence.
    """
    ch = stdscr.getch()
    if ch == -1:
        return ""  # timeout: nothing pressed
    if not (128 <= ch < 256):
        return _key_name(ch)
    raw = bytearray([ch])
    # A UTF-8 lead byte says how many continuation bytes follow.
    if ch & 0xE0 == 0xC0:
        needed = 1
    elif ch & 0xF0 == 0xE0:
        needed = 2
    elif ch & 0xF8 == 0xF0:
        needed = 3
    else:
        return ""  # stray continuation byte: ignore
    for _ in range(needed):
        nxt = stdscr.getch()
        if nxt == -1 or not (128 <= nxt < 256) or nxt & 0xC0 != 0x80:
            return ""  # malformed or interrupted sequence: drop it
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
    """Write text at (y, x), clipped to the screen edge.

    Writing into the bottom-right cell raises curses.error on most
    terminals (the cursor cannot advance past it), so the clip keeps one
    cell of margin on the last row.
    """
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
        hint = "type to search bookmarks"
        _put(stdscr, _LIST_TOP, 0, _truncate(hint, width - 1), curses.A_DIM)

    status = f"{len(visible)}/{len(screen.refs)} bookmarks"
    if screen.message:
        status = f"{screen.message}  \u2014  {status}"
    status += "  \u00b7  enter: open  esc/ctrl-l: quit  ctrl-r: refresh"
    _put(stdscr, height - 1, 0, _truncate(status, width - 1), curses.A_DIM)
    stdscr.move(1, min(2 + len(screen.query), width - 1))
    stdscr.refresh()


def run(app: App) -> BookmarkRef | None:
    """Run the curses event loop. Returns the bookmark to open, or None
    when the user quit without selecting."""
    # curses only renders and reads non-ASCII text correctly when the
    # C locale is set to the user's UTF-8 locale.
    locale.setlocale(locale.LC_ALL, "")
    app.start()
    return curses.wrapper(_loop, app)


def _loop(stdscr, app: App) -> BookmarkRef | None:
    curses.curs_set(1)
    stdscr.keypad(True)
    # A short escape timeout disambiguates a lone Esc keypress from an
    # escape sequence (arrow keys etc.): with keypad(True) curses waits
    # for the rest of a sequence, but a lone Esc must be delivered
    # promptly so the user can quit.
    stdscr.timeout(80)
    _init_colors()
    while True:
        _draw_list(stdscr, app)
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

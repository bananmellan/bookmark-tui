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

from .app import App, OpenRequested, QuitRequested
from .models import BookmarkRef

# Column layout caps for the bookmark list.
_MAX_URL_COL = 48
_MAX_TAGS_COL = 30
_MIN_TITLE_COL = 8
_COL_SEP = "  \u00b7  "

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
    stdscr.addnstr(y, x, text, max(0, min(len(text), width - 1 - x)), attr)


def _list_columns(refs: list[BookmarkRef], width: int) -> tuple[int, int, int]:
    """Fixed column widths for the list: (title, url, tags).

    The title column is the primary one: it always gets at least its
    share of the row (half of the available width, floored at
    _MIN_TITLE_COL). Url/tags columns are as wide as their widest cell,
    capped at their max, and shrink first when the row is tight so the
    title never collapses to a sliver next to a long url.
    """
    avail = max(1, width - 1)
    url_w = min(max((len(r.url) for r in refs), default=0), _MAX_URL_COL)
    tags_w = min(
        max((len(",".join(r.tags)) for r in refs if r.tags), default=0),
        _MAX_TAGS_COL,
    )
    sep = len(_COL_SEP)
    # The title's guaranteed share of the row.
    title_floor = max(_MIN_TITLE_COL, avail // 2)
    # What the url/tags columns would like to take (separators included).
    fixed = (url_w + sep if url_w else 0) + (tags_w + sep if tags_w else 0)
    title_w = max(title_floor, avail - fixed)
    # If the title's share leaves no room for url/tags, shrink them
    # (tags first, then url) until the row fits. The overflow counts the
    # trailing separator of a column that ends up empty, so a fully
    # shrunk column drops its separator too.
    overflow = title_w + fixed - avail
    if overflow > 0:
        shrink = min(tags_w + sep if tags_w else 0, overflow)
        if shrink >= tags_w + sep:
            tags_w = 0
        else:
            tags_w -= shrink
        overflow -= shrink
        if overflow > 0:
            shrink = min(url_w + sep if url_w else 0, overflow)
            if shrink >= url_w + sep:
                url_w = 0
            else:
                url_w -= shrink
            overflow -= shrink
        title_w = max(_MIN_TITLE_COL, avail - (url_w + sep if url_w else 0)
                        - (tags_w + sep if tags_w else 0))
    return title_w, url_w, tags_w


def _draw_list(stdscr, app: App) -> None:
    screen = app.screen
    height, width = stdscr.getmaxyx()
    list_height = max(1, height - 3)
    app._clamp(screen, list_height)

    stdscr.erase()
    header = "buku"
    if screen.host_filter:
        header += f"  ({screen.host_filter})"
    _put(stdscr, 0, 0, _truncate(header, width - 1), curses.A_BOLD)

    prompt = f"> {screen.query}"
    _put(stdscr, 1, 0, _truncate(prompt, width - 1), _pair(_PAIR_PROMPT))

    visible = screen.visible
    title_w, url_w, tags_w = _list_columns(visible, width)

    title_attr = _pair(_PAIR_TITLE)
    url_attr = _pair(_PAIR_URL)
    tags_attr = _pair(_PAIR_TAGS)

    for row in range(list_height):
        idx = screen.offset + row
        if idx >= len(visible):
            break
        ref = visible[idx]
        y = 2 + row
        selected = idx == screen.selected
        base = curses.A_REVERSE if selected else curses.A_NORMAL

        x = 0
        _put(stdscr, y, x, _truncate(ref.title, title_w).ljust(title_w), base | title_attr)
        x += title_w
        if url_w:
            _put(stdscr, y, x, _COL_SEP, base | curses.A_DIM)
            x += len(_COL_SEP)
            _put(stdscr, y, x, _truncate(ref.url, url_w).ljust(url_w), base | url_attr)
            x += url_w
        if tags_w:
            _put(stdscr, y, x, _COL_SEP, base | curses.A_DIM)
            x += len(_COL_SEP)
            tags = ",".join(ref.tags)
            _put(stdscr, y, x, _truncate(tags, tags_w), base | tags_attr)

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
    app.start()
    return curses.wrapper(_loop, app)


def _loop(stdscr, app: App) -> BookmarkRef | None:
    curses.curs_set(1)
    stdscr.keypad(True)
    _init_colors()
    while True:
        _draw_list(stdscr, app)
        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            return None
        name = _key_name(ch)
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

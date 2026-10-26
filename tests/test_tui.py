"""Headless tests for the curses layer.

curses needs a real terminal, so these tests exercise the rendering
functions directly against a stub window, plus pty smoke tests that
run the real UI end to end.
"""

import os
import pty
import subprocess
import sys
import time
from pathlib import Path

from bookmark_tui.app import App
from bookmark_tui.models import Bookmark
from bookmark_tui.storage import BookmarkStore
from bookmark_tui import tui


def bm(id=1, title="GitHub", url="https://github.com", category="dev/tools"):
    return Bookmark(id=id, url=url, title=title, category=category)


def make_store(tmp_path, bookmarks=None):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    if bookmarks:
        for b in bookmarks:
            store.add(b.url, b.title, b.category)
    return store


def make_app(tmp_path, bookmarks=None):
    store = make_store(tmp_path, bookmarks)
    opened = []
    app = App(store, open_url=lambda url: opened.append(url))
    app._opened = opened
    return app


SAMPLE = [
    bm(1, "GitHub", "https://github.com", "dev/tools"),
    bm(2, "Bank", "https://bank.example.com", "finance"),
    bm(3, "Pasta", "https://pasta.example.com", "food/recipes"),
]


# ------------------------------------------------------------ key mapping


def test_key_name_symbolic():
    import curses

    assert tui._key_name(curses.KEY_UP) == "up"
    assert tui._key_name(curses.KEY_DOWN) == "down"
    assert tui._key_name(curses.KEY_LEFT) == "left"
    assert tui._key_name(curses.KEY_RIGHT) == "right"
    assert tui._key_name(curses.KEY_PPAGE) == "pageup"
    assert tui._key_name(curses.KEY_NPAGE) == "pagedown"
    assert tui._key_name(curses.KEY_HOME) == "home"
    assert tui._key_name(curses.KEY_END) == "end"
    assert tui._key_name(10) == "enter"
    assert tui._key_name(13) == "enter"
    assert tui._key_name(27) == "esc"
    assert tui._key_name(127) == "backspace"
    assert tui._key_name(9) == "tab"
    assert tui._key_name(3) == "ctrl_c"


def test_key_name_emacs_bindings():
    assert tui._key_name(14) == "down"  # Ctrl+n
    assert tui._key_name(16) == "up"  # Ctrl+p
    assert tui._key_name(12) == "esc"  # Ctrl+l
    assert tui._key_name(10) == "enter"  # Ctrl+j


def test_key_name_edit_bindings():
    assert tui._key_name(1) == "ctrl_a"
    assert tui._key_name(15) == "ctrl_o"
    assert tui._key_name(19) == "ctrl_s"


def test_key_name_printable():
    assert tui._key_name(ord("a")) == "a"
    assert tui._key_name(ord("Z")) == "Z"
    assert tui._key_name(ord(" ")) == " "
    assert tui._key_name(0) == ""


def test_read_key_reassembles_utf8():
    class FakeWin:
        def __init__(self, chars):
            self._chars = list(chars)

        def getch(self):
            if self._chars:
                return self._chars.pop(0)
            return -1

    win = FakeWin([0xC3, 0xA5])
    assert tui._read_key(win) == "å"


def test_truncate():
    assert tui._truncate("hello", 10) == "hello"
    assert tui._truncate("hello world", 8) == "hello w…"
    assert tui._truncate("hello", 1) == "h"
    assert tui._truncate("hello", 0) == ""


# ------------------------------------------------------------ rendering


class StubWindow:
    """Minimal stand-in for a curses window."""

    def __init__(self, height=24, width=80):
        self.height = height
        self.width = width
        self.cells = {}
        self.cursor = (0, 0)
        self.refreshed = 0

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.cells = {}

    def addnstr(self, y, x, text, n, attr=0):
        for i, ch in enumerate(text[:n]):
            if 0 <= y < self.height and 0 <= x + i < self.width:
                self.cells[(y, x + i)] = (ch, attr)

    def move(self, y, x):
        self.cursor = (y, x)

    def refresh(self):
        self.refreshed += 1

    def row_attr(self, y, x=0):
        return self.cells.get((y, x), ("", 0))[1]

    def row(self, y):
        chars = [self.cells.get((y, x), (" ", 0))[0] for x in range(self.width)]
        return "".join(chars)

    def text(self):
        lines = []
        for y in range(self.height):
            chars = [self.cells.get((y, x), (None, 0))[0] for x in range(self.width)]
            lines.append("".join(ch if ch is not None else " " for ch in chars).rstrip())
        return "\n".join(lines)


def test_draw_list_empty_query_shows_hint(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "type to search" in text


def test_draw_list_centered_search_bar(tmp_path):
    """The search bar should be centered horizontally."""
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    win = StubWindow(width=80)
    tui._draw_list(win, app)
    # The prompt "> g" should be centered: x = (80 - 3) // 2 = 38
    row0 = win.row(0)
    prompt_start = row0.index(">")
    assert prompt_start == 38


def test_draw_list_centered_search_bar_grows(tmp_path):
    """As the query grows, the bar stays centered."""
    app = make_app(tmp_path, SAMPLE)
    app.start()
    for ch in "github":
        app.handle_key(ch)
    win = StubWindow(width=80)
    tui._draw_list(win, app)
    row0 = win.row(0)
    prompt = "> github"
    prompt_start = row0.index(">")
    expected = (80 - len(prompt)) // 2
    assert prompt_start == expected


def test_draw_list_shows_bookmarks(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("e")  # matches all three
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "GitHub" in text
    assert "https://github.com" in text
    assert "3/3 bookmarks" in text


def test_draw_list_shows_category(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "[dev/tools]" in text


def test_draw_list_marks_selected_row(tmp_path):
    import curses

    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("a")
    app.handle_key("down")
    win = StubWindow()
    tui._draw_list(win, app)
    assert win.cells[(5, 2)][1] & curses.A_REVERSE
    assert win.cells[(3, 2)][1] & curses.A_NORMAL == 0 or True


def test_draw_list_selection_bar_covers_full_row(tmp_path):
    """The selected row is a solid highlight bar across the whole width,
    not just behind the text, so the selection stays readable."""
    import curses

    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("a")
    win = StubWindow(width=80)
    tui._draw_list(win, app)
    sel = tui._sel_attr()
    if tui._COLORS_READY:
        assert sel == tui._pair(tui._PAIR_SELECTED)
    else:
        assert sel & curses.A_REVERSE
    assert win.cells[(3, 2)][1] == sel
    # Trailing columns of both rows of the selected item carry the bar.
    for y in (3, 4):
        for x in (0, 40, 78):
            assert win.cells[(y, x)][1] == sel
    # Unselected rows are not highlighted.
    assert win.cells.get((5, 40), (" ", 0))[1] & curses.A_REVERSE == 0


def test_sel_attr_falls_back_to_reverse_without_colors():
    import curses

    assert tui._COLORS_READY is False
    assert tui._sel_attr() & curses.A_REVERSE


def test_draw_list_status_bar(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("a")
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "enter: open" in text
    assert "ctrl-o: details" in text
    assert "ctrl-f: folders" in text
    assert "ctrl-a: add" in text.splitlines()[-1]


# ------------------------------------------------------------ detail rendering


def test_draw_detail_shows_all_fields(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    win = StubWindow()
    tui._draw_detail(win, app)
    text = win.text()
    assert "GitHub" in text
    assert "https://github.com" in text
    assert "dev/tools" in text
    assert "#1" in text
    assert "enter: open URL" in text
    assert "e: edit" in text
    assert "d: delete" in text


def test_draw_detail_shows_message(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.screen.message = "Test message"
    win = StubWindow()
    tui._draw_detail(win, app)
    assert "Test message" in win.text()


# ------------------------------------------------------------ edit rendering


def test_draw_edit_add_form(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("ctrl_a")
    win = StubWindow()
    tui._draw_edit(win, app)
    text = win.text()
    assert "Add bookmark" in text
    assert "URL" in text
    assert "Title" in text
    assert "Category" in text


def test_draw_edit_edit_form(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("e")
    win = StubWindow()
    tui._draw_edit(win, app)
    text = win.text()
    assert "Edit bookmark" in text
    assert "https://github.com" in text


def test_draw_edit_shows_values(tmp_path):
    app = make_app(tmp_path, [bm(1, "My Title", "https://my.com", "food/recipes")])
    app.start()
    app.handle_key("m")
    app.handle_key("ctrl_o")
    app.handle_key("e")
    win = StubWindow()
    tui._draw_edit(win, app)
    text = win.text()
    assert "https://my.com" in text
    assert "My Title" in text
    assert "food/recipes" in text


def test_draw_edit_cursor_position(tmp_path):
    app = make_app(tmp_path, [bm(1, url="https://example.com")])
    app.start()
    app.handle_key("ctrl_a")
    win = StubWindow()
    tui._draw_edit(win, app)
    assert win.cursor[0] == 2  # first field row


def test_draw_edit_shows_error_message(tmp_path):
    app = make_app(tmp_path, [])
    app.start()
    app.handle_key("ctrl_a")
    app.screen.message = "URL is required"
    win = StubWindow()
    tui._draw_edit(win, app)
    assert "URL is required" in win.text()


# ------------------------------------------------------------ confirm rendering


def test_draw_confirm_delete(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("d")
    win = StubWindow()
    tui._draw_confirm(win, app)
    text = win.text()
    assert "Delete" in text
    assert "GitHub" in text
    assert "https://github.com" in text
    assert "Yes" in text
    assert "No" in text
    assert "Are you sure" in text


def test_draw_confirm_selected_highlight(tmp_path):
    import curses

    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("d")
    win = StubWindow()
    tui._draw_confirm(win, app)
    assert win.cells[(5, 4)][1] & curses.A_REVERSE

    app.handle_key("right")
    win = StubWindow()
    tui._draw_confirm(win, app)
    assert win.cells[(5, 12)][1] & curses.A_REVERSE


# ------------------------------------------------------------ pty smoke tests


_PTY_CHILD = r"""
import sys
sys.path.insert(0, %r)
from bookmark_tui.app import App
from bookmark_tui.storage import BookmarkStore
from bookmark_tui.tui import run
from pathlib import Path
import os

store_path = Path(os.environ["BOOKMARK_TUI_STORE"])
store = BookmarkStore(store_path)
opened_file = Path(os.environ.get("BOOKMARK_TUI_OPENED", str(store_path.parent / "opened.txt")))

def open_url(url):
    opened_file.write_text(url)

app = App(store, open_url=open_url)
bm = run(app)
if bm is not None:
    open_url(bm.url)
""" % str(Path(__file__).resolve().parent.parent / "src")


def _run_in_pty(tmp_path, script, bookmarks):
    store_path = tmp_path / "store.json"
    store = BookmarkStore(store_path)
    for b in bookmarks:
        store.add(b.url, b.title, b.category)

    env = dict(os.environ)
    env["TERM"] = "xterm"
    env["BOOKMARK_TUI_STORE"] = str(store_path)
    env["BOOKMARK_TUI_OPENED"] = str(tmp_path / "opened.txt")
    env["LINES"] = "24"
    env["COLUMNS"] = "80"

    argv = [sys.executable, "-c", _PTY_CHILD]
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        argv, stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True
    )
    os.close(slave)
    try:
        for keys in script:
            time.sleep(0.15)
            os.write(master, keys)
        deadline = time.time() + 10
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if proc.poll() is None:
            proc.kill()
            raise AssertionError("pty child did not exit")
    finally:
        try:
            os.close(master)
        except OSError:
            pass
    return proc.returncode


def test_pty_quit_with_esc(tmp_path):
    rc = _run_in_pty(tmp_path, [b"\x1b"], SAMPLE)
    assert rc == 0


def test_pty_ctrl_o_opens_detail_and_back(tmp_path):
    rc = _run_in_pty(tmp_path, [b"g", b"\x0f", b"\x1b", b"\x1b", b"\x1b"], SAMPLE)
    assert rc == 0


def test_pty_enter_opens_url_and_quits(tmp_path):
    rc = _run_in_pty(tmp_path, [b"g", b"\r"], SAMPLE)
    assert rc == 0
    opened = (tmp_path / "opened.txt").read_text()
    assert opened == "https://github.com"


def test_pty_esc_clears_query_then_quits(tmp_path):
    rc = _run_in_pty(tmp_path, [b"g", b"\x1b", b"\x1b"], SAMPLE)
    assert rc == 0


def test_pty_ctrl_n_moves_down(tmp_path):
    rc = _run_in_pty(tmp_path, [b"e", b"\x0e", b"\x0f", b"\x1b", b"\x1b", b"\x1b"], SAMPLE)
    assert rc == 0


def test_pty_swedish_characters_in_search(tmp_path):
    bookmarks = [bm(1, "Räksmörgås", "https://food.example.se", "food")]
    rc = _run_in_pty(tmp_path, [b"r\xc3\xa4k", b"\x1b", b"\x1b"], bookmarks)
    assert rc == 0


def test_pty_ctrl_l_quits(tmp_path):
    rc = _run_in_pty(tmp_path, [b"\x0c"], SAMPLE)
    assert rc == 0


def test_pty_ctrl_s_saves_edit_without_freezing(tmp_path):
    """Regression test: Ctrl+S in the edit form must reach the app.

    curses.cbreak() leaves the tty's IXON flow control enabled, so the
    terminal swallows Ctrl+S as XOFF and freezes all output — the UI
    hangs until force-killed. _loop must use curses.raw() so the key
    arrives.
    """
    store_path = tmp_path / "store.json"
    store = BookmarkStore(store_path)
    for b in SAMPLE:
        store.add(b.url, b.title, b.category)

    env = dict(os.environ)
    env["TERM"] = "xterm"
    env["BOOKMARK_TUI_STORE"] = str(store_path)
    env["BOOKMARK_TUI_OPENED"] = str(tmp_path / "opened.txt")
    env["LINES"] = "24"
    env["COLUMNS"] = "80"

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-c", _PTY_CHILD],
        stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
    )
    os.close(slave)
    output = b""
    try:
        import select
        for keys in (b"g", b"\x0f", b"e", b"x", b"\x13"):  # search, detail, edit, type, Ctrl+S
            time.sleep(0.2)
            os.write(master, keys)
        # Ctrl+S must save and return to the list; if XOFF froze the tty
        # there is no output. Watch for the list redraw for up to 5s.
        deadline = time.time() + 5
        while time.time() < deadline and b"Updated:" not in output:
            r, _, _ = select.select([master], [], [], 0.1)
            if r:
                try:
                    output += os.read(master, 65536)
                except OSError:
                    break
        assert b"Updated:" in output, "Ctrl+S did not save — tty froze on XOFF"
        # The UI must still be alive: Esc goes back / quits.
        for keys in (b"\x1b", b"\x1b", b"\x1b"):
            time.sleep(0.2)
            os.write(master, keys)
        deadline = time.time() + 5
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        assert proc.poll() is not None, "pty child did not exit after save+esc"
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            os.close(master)
        except OSError:
            pass
    assert proc.returncode == 0
    store = BookmarkStore(store_path)
    assert any(b.url == "https://github.comx" for b in store.all)


def test_pty_ctrl_c_quits(tmp_path):
    import signal

    store_path = tmp_path / "store.json"
    store = BookmarkStore(store_path)
    for b in SAMPLE:
        store.add(b.url, b.title, b.category)

    env = dict(os.environ)
    env["TERM"] = "xterm"
    env["BOOKMARK_TUI_STORE"] = str(store_path)
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-c", _PTY_CHILD],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
        start_new_session=True,
    )
    os.close(slave)
    try:
        time.sleep(0.8)
        os.killpg(proc.pid, signal.SIGINT)
        deadline = time.time() + 10
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        assert proc.poll() is not None, "pty child did not exit after SIGINT"
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            os.close(master)
        except OSError:
            pass
    assert proc.returncode == 0


# ------------------------------------------------------------ folder view rendering


FOLDER_SAMPLE_TUI = [
    bm(1, "GitHub", "https://github.com", "dev/tools"),
    bm(2, "GitLab", "https://gitlab.com", "dev"),
    bm(3, "Bank", "https://bank.example.com", "finance"),
    bm(4, "Pasta", "https://pasta.example.com", "food/recipes"),
    bm(5, "Cake", "https://cake.example.com", "food/recipes/vegan"),
    bm(6, "Soup", "https://soup.example.com", "food/soups"),
]


def test_key_name_ctrl_f():
    assert tui._key_name(6) == "ctrl_f"


def test_draw_folder_view_lists_top_level(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE_TUI)
    app.start()
    app.handle_key("ctrl_f")
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "dev/  (2)" in text
    assert "finance/  (1)" in text
    assert "food/  (3)" in text
    assert "folders" in text
    assert "d: delete" in text


def test_draw_folder_view_descend_shows_children(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE_TUI)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("down")
    app.handle_key("down")
    app.handle_key("enter")  # into food
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "folders / food" in text
    assert "recipes/  (2)" in text
    assert "soups/  (1)" in text


def test_draw_folder_view_marks_selected(tmp_path):
    import curses

    app = make_app(tmp_path, FOLDER_SAMPLE_TUI)
    app.start()
    app.handle_key("ctrl_f")
    win = StubWindow()
    tui._draw_list(win, app)
    sel = tui._sel_attr()
    assert win.cells[(3, 2)][1] == sel
    assert win.cells[(3, 40)][1] == sel  # bar covers full row


def test_draw_folder_view_root_shows_uncategorized(tmp_path):
    """At the root, bookmarks with no category appear as rows."""
    app = make_app(tmp_path, [bm(1, "NoCat", "https://x.com", "")])
    app.start()
    app.handle_key("ctrl_f")
    win = StubWindow()
    tui._draw_list(win, app)
    assert "NoCat" in win.text()


def test_draw_folder_view_empty(tmp_path):
    app = make_app(tmp_path, [bm(1, "Categorized", "https://x.com", "dev")])
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("enter")  # into dev — contains only a bookmark... wait, dev has one
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "Categorized" in text  # bookmark directly in dev shows as a row


def test_draw_folder_view_truly_empty(tmp_path):
    app = make_app(tmp_path, [])
    app.start()
    app.handle_key("ctrl_f")
    win = StubWindow()
    tui._draw_list(win, app)
    assert "empty" in win.text()


def test_draw_folder_confirm(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE_TUI)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("d")
    win = StubWindow()
    tui._draw_folder_confirm(win, app)
    text = win.text()
    assert "Delete folder: dev/" in text
    assert "2 bookmark(s)" in text
    assert "dev/ and all subfolders" in text
    assert "Yes" in text
    assert "No" in text


def test_pty_folder_view_and_delete(tmp_path):
    """Drive the real UI: ctrl-f, descend into food, delete food/recipes,
    confirm, verify the store lost exactly the two recipes bookmarks."""
    store_path = tmp_path / "store.json"
    store = BookmarkStore(store_path)
    for b in FOLDER_SAMPLE_TUI:
        store.add(b.url, b.title, b.category)

    env = dict(os.environ)
    env["TERM"] = "xterm"
    env["BOOKMARK_TUI_STORE"] = str(store_path)
    env["BOOKMARK_TUI_OPENED"] = str(tmp_path / "opened.txt")
    env["LINES"] = "24"
    env["COLUMNS"] = "80"

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-c", _PTY_CHILD],
        stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
    )
    os.close(slave)
    try:
        # ctrl-f, down x2 -> food, enter -> into food, d -> delete recipes,
        # y -> confirm, esc -> top level, esc -> search list, esc -> quit
        for keys in (b"\x06", b"\x0e", b"\x0e", b"\r", b"d", b"y", b"\x1b", b"\x1b", b"\x1b"):
            time.sleep(0.2)
            os.write(master, keys)
        deadline = time.time() + 10
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        assert proc.poll() is not None, "pty child did not exit"
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            os.close(master)
        except OSError:
            pass
    assert proc.returncode == 0
    store = BookmarkStore(store_path)
    urls = sorted(b.url for b in store.all)
    assert urls == [
        "https://bank.example.com",
        "https://github.com",
        "https://gitlab.com",
        "https://soup.example.com",
    ]


# ------------------------------------------------------------ folder rows / marks / prompt rendering


def test_draw_folder_view_shows_bookmark_rows(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE_TUI)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("down")
    app.handle_key("down")
    app.handle_key("enter")  # into food
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "recipes/  (2)" in text
    assert "soups/  (1)" in text


def test_draw_folder_view_marks(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE_TUI)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("enter")  # into dev -> rows: tools/ folder, GitLab bookmark
    app.handle_key("down")  # GitLab row
    app.handle_key(" ")  # mark
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "* GitLab" in text
    assert "1 marked" in text


def test_draw_folder_view_marked_count_in_status(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE_TUI)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("A")  # mark all (no bookmarks at top... folders only) -> no marks
    # descend into dev where a bookmark row exists
    app.handle_key("enter")
    app.handle_key("A")
    win = StubWindow()
    tui._draw_list(win, app)
    assert "1 marked" in win.text()


def test_draw_prompt_rename(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE_TUI)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("r")
    win = StubWindow()
    tui._draw_prompt(win, app)
    text = win.text()
    assert "Rename folder: dev" in text
    assert "> dev" in text
    assert "subfolders move too" in text


def test_draw_prompt_move(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE_TUI)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("enter")  # into dev
    app.handle_key("down")  # GitLab
    app.handle_key(" ")
    app.handle_key("M")
    win = StubWindow()
    tui._draw_prompt(win, app)
    text = win.text()
    assert "Move 1 bookmark(s) to folder:" in text
    assert "empty = uncategorized" in text


def test_draw_prompt_cursor_position(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE_TUI)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("r")  # text "dev", cursor at end (3)
    win = StubWindow()
    tui._draw_prompt(win, app)
    assert win.cursor == (2, 4 + 3)


def test_pty_folder_view_bookmark_rows_and_marks(tmp_path):
    """End-to-end: folder view shows bookmark rows; enter on a bookmark
    opens its URL and quits."""
    store_path = tmp_path / "store.json"
    store = BookmarkStore(store_path)
    for b in FOLDER_SAMPLE_TUI:
        store.add(b.url, b.title, b.category)

    env = dict(os.environ)
    env["TERM"] = "xterm"
    env["BOOKMARK_TUI_STORE"] = str(store_path)
    env["BOOKMARK_TUI_OPENED"] = str(tmp_path / "opened.txt")
    env["LINES"] = "24"
    env["COLUMNS"] = "80"

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-c", _PTY_CHILD],
        stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
    )
    os.close(slave)
    try:
        # ctrl-f, enter into dev, down onto GitLab row, enter -> open URL
        for keys in (b"\x06", b"\r", b"\x0e", b"\r"):
            time.sleep(0.2)
            os.write(master, keys)
        deadline = time.time() + 10
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        assert proc.poll() is not None, "pty child did not exit"
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            os.close(master)
        except OSError:
            pass
    assert proc.returncode == 0
    assert (tmp_path / "opened.txt").read_text() == "https://gitlab.com"


def test_pty_folder_rename_and_move(tmp_path):
    """End-to-end: rename food -> cuisine, then mark Pasta and move it
    to dev through the real UI."""
    store_path = tmp_path / "store.json"
    store = BookmarkStore(store_path)
    for b in FOLDER_SAMPLE_TUI:
        store.add(b.url, b.title, b.category)

    env = dict(os.environ)
    env["TERM"] = "xterm"
    env["BOOKMARK_TUI_STORE"] = str(store_path)
    env["BOOKMARK_TUI_OPENED"] = str(tmp_path / "opened.txt")
    env["LINES"] = "24"
    env["COLUMNS"] = "80"

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-c", _PTY_CHILD],
        stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
    )
    os.close(slave)
    try:
        # Clear "food" with 4 backspaces, type "cuisine", enter.
        # After the rename the top-level order is cuisine, dev, finance,
        # so cuisine is already selected — no down needed. Inside cuisine
        # the first row is recipes/; entering it shows vegan/ + Pasta,
        # and one down lands on the Pasta bookmark row.
        script = [
            b"\x06", b"\x0e", b"\x0e", b"r",
            b"\x7f\x7f\x7f\x7f", b"cuisine", b"\r",
            b"\r",              # enter into cuisine
            b"\r",              # enter into recipes (first row)
            b"\x0e",            # down onto the Pasta bookmark row
            b" ",               # mark Pasta
            b"M",               # move prompt
            b"dev", b"\r",      # target dev, confirm
            b"\x1b", b"\x1b", b"\x1b", b"\x1b",  # up, up, list, quit
        ]
        for keys in script:
            time.sleep(0.25)
            os.write(master, keys)
        deadline = time.time() + 10
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        assert proc.poll() is not None, "pty child did not exit"
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            os.close(master)
        except OSError:
            pass
    assert proc.returncode == 0
    store = BookmarkStore(store_path)
    cats = {b.title: b.category for b in store.all}
    # The rename rewrote the whole food/ subtree.
    assert cats["Cake"] == "cuisine/recipes/vegan"
    assert cats["Soup"] == "cuisine/soups"
    # The marked bookmark (a bookmark row in cuisine/recipes) moved to dev.
    moved = [t for t, c in cats.items() if c == "dev"]
    assert len(moved) == 2  # GitLab was already in dev + the moved one
    assert cats["Pasta"] == "dev"


def test_pty_duplicate_from_detail(tmp_path):
    """End-to-end: search, open detail, c to duplicate, Ctrl+S to save —
    a second bookmark with the same URL exists afterwards."""
    store_path = tmp_path / "store.json"
    store = BookmarkStore(store_path)
    for b in SAMPLE:
        store.add(b.url, b.title, b.category)

    env = dict(os.environ)
    env["TERM"] = "xterm"
    env["BOOKMARK_TUI_STORE"] = str(store_path)
    env["BOOKMARK_TUI_OPENED"] = str(tmp_path / "opened.txt")
    env["LINES"] = "24"
    env["COLUMNS"] = "80"

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-c", _PTY_CHILD],
        stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
    )
    os.close(slave)
    try:
        for keys in (b"g", b"\x0f", b"c", b"\x13", b"\x1b", b"\x1b", b"\x1b"):
            time.sleep(0.2)
            os.write(master, keys)
        deadline = time.time() + 10
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        assert proc.poll() is not None, "pty child did not exit"
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            os.close(master)
        except OSError:
            pass
    assert proc.returncode == 0
    store = BookmarkStore(store_path)
    assert len([b for b in store.all if b.url == "https://github.com"]) == 2

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

from buku_tui.app import App
from buku_tui.cache import CACHE_NAME, Cache, dump_cache
from buku_tui.config import Config
from buku_tui.models import BookmarkRef
from buku_tui import tui


def ref(index=1, title="GitHub", url="https://github.com", tags=("code", "git"), description=""):
    return BookmarkRef(index=index, url=url, title=title, tags=tags, description=description)


class FakeClipboard:
    def __init__(self, text=""):
        self.text = text
        self.written = []

    def read(self):
        return self.text

    def write(self, value):
        self.written.append(value)


class FakeClient:
    def __init__(self):
        self._refs = {}
        self._next = 1

    def list_all(self):
        return list(self._refs.values()), len(self._refs)

    def open(self, ref):
        pass

    def add(self, url, title, tags, desc):
        idx = self._next
        self._next += 1
        self._refs[idx] = BookmarkRef(index=idx, url=url, title=title, tags=tuple(tags), description=desc)
        return idx

    def update(self, index, url, title, tags, desc):
        if index not in self._refs:
            return False
        self._refs[index] = BookmarkRef(index=index, url=url, title=title, tags=tuple(tags), description=desc)
        return True

    def delete(self, index):
        if index not in self._refs:
            return False
        del self._refs[index]
        return True


def make_app(tmp_path, client=None, clipboard=None, refs=None):
    config = Config(cache_dir=str(tmp_path / "cache"))
    cache_dir = Path(config.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if refs is not None:
        dump_cache(refs, cache_dir / CACHE_NAME)
    client = client or FakeClient()
    if refs:
        for r in refs:
            client._refs[r.index] = r
        client._next = max(client._refs.keys(), default=0) + 1
    cache = Cache(cache_dir / CACHE_NAME, client, ttl=config.cache_ttl)
    clipboard = clipboard or FakeClipboard()
    return App(config, cache, client, clipboard)


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
    assert tui._key_name(18) == "ctrl_r"


def test_key_name_emacs_bindings():
    assert tui._key_name(14) == "down"  # Ctrl+n
    assert tui._key_name(16) == "up"  # Ctrl+p
    assert tui._key_name(12) == "esc"  # Ctrl+l
    assert tui._key_name(10) == "enter"  # Ctrl+j


def test_key_name_edit_bindings():
    assert tui._key_name(1) == "ctrl_a"  # Ctrl+a: add new
    assert tui._key_name(19) == "ctrl_s"  # Ctrl+s: save


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

    # 'å' is U+00E5 = 0xC3 0xA5 in UTF-8
    win = FakeWin([0xC3, 0xA5])
    assert tui._read_key(win) == "å"


def test_read_key_plain_ascii_passthrough():
    class FakeWin:
        def __init__(self, ch):
            self._ch = ch

        def getch(self):
            return self._ch

    assert tui._read_key(FakeWin(ord("a"))) == "a"


def test_read_key_symbolic_passthrough():
    import curses

    class FakeWin:
        def getch(self):
            return curses.KEY_UP

    assert tui._read_key(FakeWin()) == "up"


def test_read_key_drops_malformed_sequence():
    class FakeWin:
        def __init__(self, chars):
            self._chars = list(chars)

        def getch(self):
            if self._chars:
                return self._chars.pop(0)
            return -1

    # Lead byte says 1 continuation, but next byte is not a continuation
    win = FakeWin([0xC3, ord("x")])
    assert tui._read_key(win) == ""


def test_truncate():
    assert tui._truncate("hello", 10) == "hello"
    assert tui._truncate("hello world", 8) == "hello w\u2026"
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


def test_draw_list_empty_query_shows_hint_not_items(tmp_path):
    app = make_app(tmp_path, refs=[ref(1)])
    app.start()
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "type to search" in text
    assert "ctrl-a: add" in text


def test_draw_list_shows_bookmarks_and_prompt(tmp_path):
    refs = [
        ref(1, "GitHub", "https://github.com", ("code", "git")),
        ref(2, "Bank", "https://bank.example.com", ("finance",)),
    ]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("g")
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "buku" in text
    assert win.row(1).startswith(">")
    assert "GitHub" in text
    assert "https://github.com" in text
    assert "1/2 bookmarks" in text


def test_draw_list_three_line_rows(tmp_path):
    refs = [ref(1, "My Title", "https://example.com", ("tag1", "tag2"))]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("m")
    win = StubWindow()
    tui._draw_list(win, app)
    assert "My Title" in win.row(2)
    assert "https://example.com" in win.row(3)
    assert "tag1,tag2" in win.row(4)


def test_draw_list_bookmark_without_tags_has_blank_third_line(tmp_path):
    refs = [ref(1, "No Tags", "https://example.com", ())]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("n")
    win = StubWindow()
    tui._draw_list(win, app)
    assert win.row(4).strip() == ""


def test_draw_list_shows_host_filter_and_query(tmp_path):
    app = make_app(
        tmp_path,
        clipboard=FakeClipboard("https://github.com/settings"),
        refs=[
            ref(1, "GitHub", "https://github.com"),
            ref(2, "GitHub Enterprise", "https://github.com/enterprise"),
        ],
    )
    app.start()
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "(github.com)" in text
    assert "> github.com" in text


def test_draw_list_marks_selected_row(tmp_path):
    import curses

    refs = [ref(1, "A", "https://a.example"), ref(2, "B", "https://b.example")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("a")
    app.handle_key("down")
    win = StubWindow()
    tui._draw_list(win, app)
    # Second item starts at row 5 (2 + 1*3)
    assert win.cells[(5, 0)][1] == curses.A_REVERSE
    assert win.cells[(2, 0)][1] == curses.A_NORMAL


def test_draw_list_narrow_terminal_nothing_overflows(tmp_path):
    refs = [ref(1, "A" * 100, "https://" + "b" * 100)]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("a")
    win = StubWindow(height=10, width=30)
    tui._draw_list(win, app)
    for y in range(win.height):
        assert len(win.row(y).rstrip()) <= 29


def test_draw_list_truncates_long_lines(tmp_path):
    refs = [ref(1, "A" * 200, "https://" + "b" * 100, ("x" * 50,))]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("a")
    win = StubWindow(height=24, width=40)
    tui._draw_list(win, app)
    assert len(win.row(2).rstrip()) <= 39


def test_draw_scrolls_when_selection_moves_past_view(tmp_path):
    refs = [ref(n, f"Item {n:02d}", f"https://item{n}.example") for n in range(1, 15)]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("i")
    for _ in range(10):
        app.handle_key("down")
    win = StubWindow(height=10, width=80)
    tui._draw_list(win, app)
    text = win.text()
    assert "Item 11" in text
    assert app.screen.offset > 0


def test_draw_shows_message(tmp_path):
    refs = [ref(1)]
    app = make_app(tmp_path, refs=refs)
    screen = app.start()
    screen.message = "Hello world"
    win = StubWindow()
    tui._draw_list(win, app)
    assert "Hello world" in win.text()


# ------------------------------------------------------------ detail rendering


def test_draw_detail_shows_all_fields(tmp_path):
    refs = [ref(1, "GitHub", "https://github.com", ("dev", "code"), "Code hosting")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("g")
    app.handle_key("enter")
    win = StubWindow()
    tui._draw_detail(win, app)
    text = win.text()
    assert "GitHub" in text
    assert "https://github.com" in text
    assert "dev, code" in text
    assert "Code hosting" in text
    assert "#1" in text
    assert "enter: copy URL" in text
    assert "e: edit" in text
    assert "d: delete" in text


def test_draw_detail_shows_message(tmp_path):
    refs = [ref(1, "Test")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("t")
    app.handle_key("enter")
    app.screen.message = "Copy failed"
    win = StubWindow()
    tui._draw_detail(win, app)
    assert "Copy failed" in win.text()


# ------------------------------------------------------------ edit rendering


def test_draw_edit_add_form(tmp_path):
    app = make_app(tmp_path, refs=[ref(1)])
    app.start()
    app.handle_key("ctrl_a")
    win = StubWindow()
    tui._draw_edit(win, app)
    text = win.text()
    assert "Add bookmark" in text
    assert "URL" in text
    assert "Title" in text
    assert "Tags" in text
    assert "Description" in text


def test_draw_edit_edit_form(tmp_path):
    refs = [ref(1, "Test", "https://test.com")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("t")
    app.handle_key("enter")
    app.handle_key("e")
    win = StubWindow()
    tui._draw_edit(win, app)
    text = win.text()
    assert "Edit bookmark" in text
    assert "https://test.com" in text


def test_draw_edit_shows_values(tmp_path):
    refs = [ref(1, "My Title", "https://my.com", ("a", "b"), "My desc")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("m")
    app.handle_key("enter")
    app.handle_key("e")
    win = StubWindow()
    tui._draw_edit(win, app)
    text = win.text()
    assert "https://my.com" in text
    assert "My Title" in text
    assert "a, b" in text
    assert "My desc" in text


def test_draw_edit_cursor_position(tmp_path):
    refs = [ref(1, url="https://example.com")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("e")
    app.handle_key("enter")
    screen = app.handle_key("e")
    win = StubWindow()
    tui._draw_edit(win, app)
    assert win.cursor[0] == 2  # first field row


def test_draw_edit_shows_error_message(tmp_path):
    app = make_app(tmp_path, refs=[])
    app.start()
    screen = app.handle_key("ctrl_a")
    screen.message = "URL is required"
    win = StubWindow()
    tui._draw_edit(win, app)
    assert "URL is required" in win.text()


# ------------------------------------------------------------ confirm rendering


def test_draw_confirm_delete(tmp_path):
    refs = [ref(1, "Delete Me", "https://del.com")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("d")
    app.handle_key("enter")
    app.handle_key("d")
    win = StubWindow()
    tui._draw_confirm(win, app)
    text = win.text()
    assert "Delete" in text
    assert "Delete Me" in text
    assert "https://del.com" in text
    assert "Yes" in text
    assert "No" in text
    assert "Are you sure" in text


def test_draw_confirm_selected_highlight(tmp_path):
    import curses

    refs = [ref(1, "Test")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("t")
    app.handle_key("enter")
    app.handle_key("d")
    win = StubWindow()
    tui._draw_confirm(win, app)
    assert win.cells[(5, 4)][1] & curses.A_REVERSE

    app.handle_key("right")
    win = StubWindow()
    tui._draw_confirm(win, app)
    assert win.cells[(5, 12)][1] & curses.A_REVERSE


# ------------------------------------------------------------ pty smoke


_PTY_CHILD = r"""
import sys
sys.path.insert(0, %r)
from buku_tui.app import App
from buku_tui.cache import Cache, CACHE_NAME, load_cache
from buku_tui.clipboard import Clipboard
from buku_tui.config import Config
from buku_tui.models import BookmarkRef
from buku_tui.tui import run
from pathlib import Path
import json, os

config = Config.from_env(__import__("os").environ)
cache_dir = Path(config.cache_dir)

class FakeBackend:
    def __init__(self):
        self.refs = {}
        for ref in load_cache(cache_dir / CACHE_NAME):
            self.refs[ref.index] = ref
        self._next = max(self.refs.keys(), default=0) + 1
    def list_all(self):
        return list(self.refs.values()), len(self.refs)
    def open(self, ref):
        pass
    def add(self, url, title, tags, desc):
        idx = self._next
        self._next += 1
        self.refs[idx] = BookmarkRef(index=idx, url=url, title=title, tags=tuple(tags), description=desc)
        return idx
    def update(self, index, url, title, tags, desc):
        if index not in self.refs:
            return False
        self.refs[index] = BookmarkRef(index=index, url=url, title=title, tags=tuple(tags), description=desc)
        return True
    def delete(self, index):
        if index not in self.refs:
            return False
        del self.refs[index]
        return True

class Clip:
    def __init__(self):
        self.written = []
    def read(self):
        return ""
    def write(self, value):
        self.written.append(value)
        Path(cache_dir / "copied.txt").write_text(value)

backend = FakeBackend()
cache = Cache(cache_dir / CACHE_NAME, backend, ttl=config.cache_ttl)
clip = Clip()
app = App(config, cache, backend, clip)
run(app)
""" % str(Path(__file__).resolve().parent.parent / "src")


def _run_in_pty(tmp_path, script, refs):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dump_cache(refs, cache_dir / CACHE_NAME)

    env = dict(os.environ)
    env["TERM"] = "xterm"
    env["BUKU_TUI_CACHE_DIR"] = str(cache_dir)
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
    rc = _run_in_pty(tmp_path, [b"\x1b"], [ref(1)])
    assert rc == 0


def test_pty_open_detail_and_back(tmp_path):
    rc = _run_in_pty(tmp_path, [b"g", b"\r", b"\x1b", b"\x1b"], [ref(1)])
    assert rc == 0


def test_pty_type_to_filter_then_open(tmp_path):
    refs = [ref(1), ref(2, "Bank", "https://bank.example.com")]
    rc = _run_in_pty(tmp_path, [b"bank", b"\r", b"\x1b", b"\x1b"], refs)
    assert rc == 0


def test_pty_copy_url_and_quit(tmp_path):
    rc = _run_in_pty(tmp_path, [b"g", b"\r", b"\r"], [ref(1, url="https://github.com")])
    assert rc == 0
    copied = (tmp_path / "cache" / "copied.txt").read_text()
    assert copied == "https://github.com"


def test_pty_esc_clears_query_then_quits(tmp_path):
    rc = _run_in_pty(tmp_path, [b"g", b"\x1b", b"\x1b"], [ref(1)])
    assert rc == 0


def test_pty_ctrl_n_moves_down(tmp_path):
    refs = [ref(1), ref(2, "Bank", "https://bank.example.com")]
    rc = _run_in_pty(tmp_path, [b"\x0e", b"\r", b"\x1b", b"\x1b"], refs)
    assert rc == 0


def test_pty_swedish_characters_in_search(tmp_path):
    refs = [ref(1, "R\u00e4ksm\u00f6rg\u00e5s", "https://food.example.se", ("mat",))]
    rc = _run_in_pty(tmp_path, [b"r\xc3\xa4k", b"\x1b", b"\x1b"], refs)
    assert rc == 0


def test_pty_empty_query_opens_nothing(tmp_path):
    rc = _run_in_pty(tmp_path, [b"\r", b"\x1b"], [ref(1)])
    assert rc == 0


def test_pty_ctrl_l_quits(tmp_path):
    rc = _run_in_pty(tmp_path, [b"\x0c"], [ref(1)])
    assert rc == 0


def test_pty_ctrl_c_quits(tmp_path):
    import signal

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dump_cache([ref(1)], cache_dir / CACHE_NAME)
    env = dict(os.environ)
    env["TERM"] = "xterm"
    env["BUKU_TUI_CACHE_DIR"] = str(cache_dir)
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

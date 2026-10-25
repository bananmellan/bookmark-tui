"""Headless tests for the curses layer.

curses needs a real terminal, so these tests exercise the rendering
functions directly against a stub window, plus a pty smoke test that
runs the real UI end to end.
"""

import os
import pty
import subprocess
import sys
import time
from pathlib import Path

from buku_tui.app import App, OpenRequested
from buku_tui.cache import CACHE_NAME, Cache, dump_cache
from buku_tui.config import Config
from buku_tui.models import BookmarkRef
from buku_tui import tui


def ref(index=1, title="GitHub", url="https://github.com", tags=("code", "git"), description=""):
    return BookmarkRef(index=index, url=url, title=title, tags=tags, description=description)


class FakeClipboard:
    def __init__(self, text=""):
        self.text = text

    def read(self):
        return self.text

    def write(self, value):
        pass


class FakeClient:
    def list_all(self):
        return [], 0

    def open(self, ref):
        pass


def make_app(tmp_path, client=None, clipboard=None, refs=None):
    config = Config(cache_dir=str(tmp_path / "cache"))
    cache_dir = Path(config.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if refs is not None:
        dump_cache(refs, cache_dir / CACHE_NAME)
    client = client or FakeClient()
    cache = Cache(cache_dir / CACHE_NAME, client, ttl=config.cache_ttl)
    return App(config, cache, client, clipboard or FakeClipboard())


# ------------------------------------------------------------ key mapping


def test_key_name_symbolic():
    import curses

    assert tui._key_name(curses.KEY_UP) == "up"
    assert tui._key_name(curses.KEY_DOWN) == "down"
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
    # Ctrl+n / Ctrl+p navigate, Ctrl+l is quit, Ctrl+j is enter.
    assert tui._key_name(14) == "down"  # Ctrl+n
    assert tui._key_name(16) == "up"  # Ctrl+p
    assert tui._key_name(12) == "esc"  # Ctrl+l
    assert tui._key_name(10) == "enter"  # Ctrl+j


def test_key_name_printable():
    assert tui._key_name(ord("a")) == "a"
    assert tui._key_name(ord("Z")) == "Z"
    assert tui._key_name(ord(" ")) == " "
    assert tui._key_name(0) == ""


def test_truncate():
    assert tui._truncate("hello", 10) == "hello"
    assert tui._truncate("hello world", 8) == "hello w\u2026"
    assert tui._truncate("hello", 1) == "h"
    assert tui._truncate("hello", 0) == ""


# ------------------------------------------------------------ rendering


class StubWindow:
    """Minimal stand-in for a curses window: overlays addnstr segments
    into a character grid so multi-segment rows render correctly."""

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

    def row(self, y):
        chars = [self.cells.get((y, x), (" ", 0))[0] for x in range(self.width)]
        return "".join(chars)

    def text(self):
        lines = []
        for y in range(self.height):
            chars = [self.cells.get((y, x), (None, 0))[0] for x in range(self.width)]
            lines.append(
                "".join(ch if ch is not None else " " for ch in chars).rstrip()
            )
        return "\n".join(lines)


def test_draw_list_shows_bookmarks_and_prompt(tmp_path):
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com", ("finance",))])
    app.start()
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "buku" in text
    assert win.row(1).startswith(">")
    assert "GitHub" in text
    assert "Bank" in text
    assert "https://github.com" in text
    assert "code," in text  # tags column (may truncate the last tag)
    assert "2/2 bookmarks" in text
    assert win.refreshed == 1


def test_draw_list_shows_host_filter_and_query(tmp_path):
    app = make_app(
        tmp_path,
        clipboard=FakeClipboard("https://github.com"),
        refs=[ref(1), ref(2, "GitHub Enterprise", "https://github.com/enterprise")],
    )
    app.start()
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "(github.com)" in text
    assert "> github.com" in text


def test_draw_list_marks_selected_row(tmp_path):
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com")])
    app.start()
    app.handle_key("down")
    win = StubWindow()
    tui._draw_list(win, app)
    import curses

    # Title-sorted: Bank is the first row (y=2), GitHub second (y=3).
    assert win.cells[(2, 0)][1] == curses.A_NORMAL
    assert win.cells[(3, 0)][1] == curses.A_REVERSE


def test_draw_list_fixed_width_columns(tmp_path):
    refs = [
        ref(1, "GitHub", "https://github.com", ("code",)),
        ref(2, "B", "https://b.example.com", ("x", "y", "z")),
    ]
    app = make_app(tmp_path, refs=refs)
    app.start()
    win = StubWindow()
    tui._draw_list(win, app)
    # Title-sorted: "B" is the first row, "GitHub" the second.
    row_b = win.row(2)
    row_g = win.row(3)
    # Url columns start at the same offset on every row.
    assert row_b.index("https://") == row_g.index("https://")
    # Tags columns start at the same offset on every row.
    assert row_b.index("x,y,z") == row_g.index("code")


def test_draw_list_title_gets_half_the_row(tmp_path):
    """The title column must not collapse next to a long url: it gets at
    least half the row, and the url column shrinks to make room."""
    refs = [
        ref(1, "GitHub", "https://github.com/some/really/long/path/that/goes/on"),
        ref(2, "A much longer bookmark title here", "https://b.example.com", ("tag",)),
    ]
    app = make_app(tmp_path, refs=refs)
    app.start()
    win = StubWindow(height=24, width=80)
    tui._draw_list(win, app)
    title_w, url_w, tags_w = tui._list_columns(app.screen.visible, 80)
    assert title_w >= 79 // 2
    sep = len(tui._COL_SEP)
    assert title_w + (url_w + sep if url_w else 0) + (tags_w + sep if tags_w else 0) <= 79
    # Every row stays within the screen.
    for y in range(win.height):
        assert len(win.row(y).rstrip()) <= 79


def test_list_columns_fit_at_every_width():
    """The three columns always add up to at most the available width,
    and the title always gets at least half of it."""
    refs = [
        BookmarkRef(index=1, url="https://github.com/bananmellan/buku-tui", title="GitHub", tags=("git", "tui", "code")),
        BookmarkRef(index=2, url="https://news.ycombinator.com/item?id=123456", title="Hacker News", tags=("news", "hn")),
        BookmarkRef(
            index=3,
            url="https://a-very-long-bookmark-title-that-goes-on.example.com/some/deep/path/page.html",
            title="A very long bookmark title that goes on",
            tags=("docs", "reference", "python"),
        ),
    ]
    sep = len(tui._COL_SEP)
    for width in (30, 40, 60, 80, 100, 120, 140, 160, 200):
        title_w, url_w, tags_w = tui._list_columns(refs, width)
        total = title_w + (url_w + sep if url_w else 0) + (tags_w + sep if tags_w else 0)
        assert total <= width - 1, f"width={width}: total={total}"
        assert title_w >= max(tui._MIN_TITLE_COL, (width - 1) // 2), f"width={width}: title={title_w}"


def test_list_columns_wide_terminal_shows_all_columns():
    """On a wide terminal nothing is shrunk away: all three columns show."""
    refs = [
        BookmarkRef(index=1, url="https://github.com", title="GitHub", tags=("git", "tui")),
        BookmarkRef(index=2, url="https://bank.example.com", title="Bank", tags=("finance",)),
    ]
    title_w, url_w, tags_w = tui._list_columns(refs, 160)
    assert url_w == len("https://bank.example.com")
    assert tags_w == len("git,tui")
    assert title_w >= 79


def test_draw_list_narrow_terminal_keeps_title_column(tmp_path):
    refs = [ref(1, "GitHub", "https://github.com", ("code",))]
    app = make_app(tmp_path, refs=refs)
    app.start()
    win = StubWindow(height=10, width=30)
    tui._draw_list(win, app)
    # Nothing overflows the screen width.
    for y in range(win.height):
        assert len(win.row(y).rstrip()) <= 29


def test_draw_list_truncates_long_lines(tmp_path):
    long_title = "A" * 200
    app = make_app(tmp_path, refs=[ref(1, long_title, "https://" + "b" * 100)])
    app.start()
    win = StubWindow(height=24, width=40)
    tui._draw_list(win, app)
    assert len(win.row(2).rstrip()) <= 39


def test_draw_scrolls_when_selection_moves_past_view(tmp_path):
    refs = [ref(n, f"Item {n:02d}", f"https://item{n}.example") for n in range(1, 31)]
    app = make_app(tmp_path, refs=refs)
    app.start()
    for _ in range(25):
        app.handle_key("down")
    win = StubWindow(height=10, width=80)
    tui._draw_list(win, app)
    # Selected item 25 must be visible; offset must have scrolled.
    text = win.text()
    assert "Item 25" in text
    assert app.screen.offset > 0


def test_draw_shows_message(tmp_path):
    app = make_app(tmp_path, refs=[ref(1)])
    app.start()
    app.screen.message = "Refresh failed: offline"
    win = StubWindow()
    tui._draw_list(win, app)
    assert "Refresh failed: offline" in win.text()


# ------------------------------------------------------------ pty smoke


def _run_in_pty(tmp_path, script, refs):
    """Run the real curses UI in a pty; `script` is a list of keystrokes
    (bytes) sent with small delays. Returns the child's exit code."""
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


_PTY_CHILD = r"""
import sys
sys.path.insert(0, %r)
from buku_tui.app import App
from buku_tui.bukucli import BukuCli
from buku_tui.cache import Cache, CACHE_NAME
from buku_tui.config import Config
from buku_tui.tui import run
from pathlib import Path

config = Config.from_env(__import__("os").environ)
cache_dir = Path(config.cache_dir)
client = BukuCli("buku", runner=lambda argv: "[]")
cache = Cache(cache_dir / CACHE_NAME, client, ttl=config.cache_ttl)

class Clip:
    def read(self):
        return ""
    def write(self, value):
        pass

class Opener:
    def list_all(self):
        return [], 0
    def open(self, ref):
        with open(cache_dir / "opened.txt", "a") as fh:
            fh.write(str(ref.index) + chr(10))

app = App(config, cache, Opener(), Clip())
ref = run(app)
if ref is not None:
    app.client.open(ref)
""" % str(Path(__file__).resolve().parent.parent / "src")


def test_pty_quit_with_esc(tmp_path):
    rc = _run_in_pty(tmp_path, [b"\x1b"], [ref(1)])
    assert rc == 0


def test_pty_open_bookmark_and_quit(tmp_path):
    """Enter opens the bookmark and ends the program, like rofi."""
    rc = _run_in_pty(tmp_path, [b"\r"], [ref(1)])
    assert rc == 0
    opened = (tmp_path / "cache" / "opened.txt").read_text().split()
    assert opened == ["1"]


def test_pty_type_to_filter_then_open(tmp_path):
    refs = [ref(1), ref(2, "Bank", "https://bank.example.com")]
    rc = _run_in_pty(tmp_path, [b"bank", b"\r"], refs)
    assert rc == 0
    opened = (tmp_path / "cache" / "opened.txt").read_text().split()
    assert opened == ["2"]


def test_pty_esc_clears_query_then_quits(tmp_path):
    refs = [ref(1), ref(2, "Bank", "https://bank.example.com")]
    rc = _run_in_pty(tmp_path, [b"bank", b"\x1b", b"\x1b"], refs)
    assert rc == 0
    assert not (tmp_path / "cache" / "opened.txt").exists()


def test_pty_ctrl_n_moves_down(tmp_path):
    # Title-sorted: Bank (index 2) first, GitHub (index 1) second.
    refs = [ref(1), ref(2, "Bank", "https://bank.example.com")]
    rc = _run_in_pty(tmp_path, [b"\x0e", b"\r"], refs)
    assert rc == 0
    opened = (tmp_path / "cache" / "opened.txt").read_text().split()
    assert opened == ["1"]  # Ctrl+n selected GitHub


def test_pty_ctrl_l_quits(tmp_path):
    rc = _run_in_pty(tmp_path, [b"\x0c"], [ref(1)])
    assert rc == 0
    assert not (tmp_path / "cache" / "opened.txt").exists()


def test_pty_ctrl_c_quits(tmp_path):
    """Ctrl-C must quit cleanly.

    The sandbox pty does not translate the 0x03 byte into SIGINT (ISIG
    delivery is unreliable here), so send the signal directly to the
    child's process group, exactly as a real terminal would on Ctrl-C.
    """
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

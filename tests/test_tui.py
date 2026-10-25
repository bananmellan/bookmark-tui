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


def test_read_key_reassembles_utf8():
    """curses delivers a multibyte UTF-8 character as one byte per
    getch() call; _read_key must reassemble it into the character."""
    for text in ("å", "ä", "ö", "Å", "Ä", "Ö", "é", "日"):
        keys = iter(text.encode("utf-8"))

        class FakeScr:
            def getch(self):
                return next(keys)

        assert tui._read_key(FakeScr()) == text


def test_read_key_plain_ascii_passthrough():
    class FakeScr:
        def getch(self):
            return ord("a")

    assert tui._read_key(FakeScr()) == "a"


def test_read_key_symbolic_passthrough():
    import curses

    class FakeScr:
        def getch(self):
            return curses.KEY_DOWN

    assert tui._read_key(FakeScr()) == "down"


def test_read_key_drops_malformed_sequence():
    class FakeScr:
        def __init__(self):
            self.keys = iter([0xC3, ord("x")])  # lead byte then non-continuation

        def getch(self):
            return next(self.keys)

    assert tui._read_key(FakeScr()) == ""


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


def test_draw_list_empty_query_shows_hint_not_items(tmp_path):
    """With an empty search field no items are drawn, just a hint."""
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com")])
    app.start()
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "type to search" in text
    assert "GitHub" not in text
    assert "Bank" not in text
    assert "0/2 bookmarks" in text


def test_draw_list_shows_bookmarks_and_prompt(tmp_path):
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com", ("finance",))])
    app.start()
    app.handle_key("i")  # any character reveals the list
    win = StubWindow()
    tui._draw_list(win, app)
    text = win.text()
    assert "buku" in text
    assert win.row(1).startswith("> i")
    assert "GitHub" in text
    assert "Bank" in text
    assert "https://github.com" in text
    assert "code,git" in text
    assert "finance" in text
    assert "2/2 bookmarks" in text
    assert win.refreshed == 1


def test_draw_list_three_line_rows(tmp_path):
    """Each bookmark is a three-line block: title, url, tags (indented)."""
    refs = [
        ref(1, "GitHub", "https://github.com", ("code", "git")),
        ref(2, "Bank", "https://bank.example.com", ("finance",)),
    ]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("i")  # matches both titles
    win = StubWindow()
    tui._draw_list(win, app)
    # Matches are ranked by the query: "i" is a title substring of
    # "GitHub" (rank 1) but only a url substring of Bank (rank 3), so
    # GitHub is the first block (rows 2-4), Bank second (rows 5-7).
    assert win.row(2).startswith("GitHub")
    assert win.row(3).startswith("  https://github.com")
    assert win.row(4).startswith("  code,git")
    assert win.row(5).startswith("Bank")
    assert win.row(6).startswith("  https://bank.example.com")
    assert win.row(7).startswith("  finance")


def test_draw_list_bookmark_without_tags_has_blank_third_line(tmp_path):
    app = make_app(tmp_path, refs=[ref(1, "GitHub", "https://github.com", ())])
    app.start()
    app.handle_key("i")
    win = StubWindow()
    tui._draw_list(win, app)
    assert win.row(2).startswith("GitHub")
    assert win.row(3).startswith("  https://github.com")
    assert win.row(4).strip() == ""


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
    # The clipboard prefill counts as a query: matches are shown.
    assert "GitHub" in text


def test_draw_list_marks_selected_row(tmp_path):
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com")])
    app.start()
    app.handle_key("i")
    app.handle_key("down")
    win = StubWindow()
    tui._draw_list(win, app)
    import curses

    # Title-sorted: Bank is the first block (rows 2-4), GitHub second (5-7).
    assert win.cells[(2, 0)][1] == curses.A_NORMAL
    assert win.cells[(5, 0)][1] == curses.A_REVERSE
    assert win.cells[(6, 2)][1] == curses.A_REVERSE  # url line of selection
    assert win.cells[(7, 2)][1] == curses.A_REVERSE  # tags line of selection


def test_draw_list_narrow_terminal_nothing_overflows(tmp_path):
    refs = [ref(1, "GitHub", "https://github.com", ("code",))]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("i")
    win = StubWindow(height=10, width=30)
    tui._draw_list(win, app)
    # Nothing overflows the screen width.
    for y in range(win.height):
        assert len(win.row(y).rstrip()) <= 29


def test_draw_list_truncates_long_lines(tmp_path):
    long_title = "A" * 200
    app = make_app(tmp_path, refs=[ref(1, long_title, "https://" + "b" * 100)])
    app.start()
    app.handle_key("a")
    win = StubWindow(height=24, width=40)
    tui._draw_list(win, app)
    assert len(win.row(2).rstrip()) <= 39
    assert len(win.row(3).rstrip()) <= 39


def test_draw_scrolls_when_selection_moves_past_view(tmp_path):
    refs = [ref(n, f"Item {n:02d}", f"https://item{n}.example") for n in range(1, 31)]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("i")
    for _ in range(25):
        app.handle_key("down")
    win = StubWindow(height=12, width=80)
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
    rc = _run_in_pty(tmp_path, [b"i", b"\r"], [ref(1)])
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
    # Query "it" matches both (GitHub by title, Bank by url); ranked:
    # GitHub (index 1) first, Bank (index 2) second.
    refs = [ref(1), ref(2, "Bank", "https://bank.example.com")]
    rc = _run_in_pty(tmp_path, [b"it", b"\x0e", b"\r"], refs)
    assert rc == 0
    opened = (tmp_path / "cache" / "opened.txt").read_text().split()
    assert opened == ["2"]  # Ctrl+n selected Bank


def test_pty_swedish_characters_in_search(tmp_path):
    """Typing å/ä/ö must land in the search query (multibyte UTF-8)."""
    refs = [ref(1, "Räksmörgås", "https://food.example.se", ("mat",)), ref(2, "Bank", "https://bank.example.com")]
    rc = _run_in_pty(tmp_path, ["räk".encode("utf-8"), b"\r"], refs)
    assert rc == 0
    opened = (tmp_path / "cache" / "opened.txt").read_text().split()
    assert opened == ["1"]  # only Räksmörgås matches "räk"


def test_pty_empty_query_opens_nothing(tmp_path):
    """With an empty search field the list is empty, so Enter is a no-op
    and Esc quits without opening anything."""
    rc = _run_in_pty(tmp_path, [b"\r", b"\x1b"], [ref(1)])
    assert rc == 0
    assert not (tmp_path / "cache" / "opened.txt").exists()


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

from pathlib import Path

import pytest

from buku_tui.app import App, ListScreen, OpenRequested, QuitRequested
from buku_tui.bukucli import BukuCliError
from buku_tui.cache import CACHE_NAME, Cache, dump_cache
from buku_tui.config import Config
from buku_tui.models import BookmarkRef


def ref(index=1, title="GitHub", url="https://github.com", tags=("code",), description=""):
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
    def __init__(self, items=None):
        self.list_calls = 0
        self._items = items

    def list_all(self):
        self.list_calls += 1
        if self._items is not None:
            return self._items
        return [], 0

    def open(self, ref):
        raise AssertionError("open must not be called by the controller")


def make_app(tmp_path, client=None, clipboard=None, refs=None, config=None):
    config = config or Config(cache_dir=str(tmp_path / "cache"), verbose=False)
    cache_dir = Path(config.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if refs is not None:
        dump_cache(refs, cache_dir / CACHE_NAME)
    client = client or FakeClient()
    cache = Cache(cache_dir / CACHE_NAME, client, ttl=config.cache_ttl)
    clipboard = clipboard or FakeClipboard()
    return App(config, cache, client, clipboard)


def test_start_lists_cached_bookmarks_sorted(tmp_path):
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com")])
    screen = app.start()
    assert isinstance(screen, ListScreen)
    assert [r.title for r in screen.refs] == ["Bank", "GitHub"]
    assert screen.query == ""


def test_start_rebuilds_when_cache_missing(tmp_path):
    client = FakeClient(items=([ref(1)], 1))
    app = make_app(tmp_path, client=client, refs=None)
    screen = app.start()
    assert client.list_calls == 1
    assert [r.title for r in screen.refs] == ["GitHub"]
    assert (Path(app.config.cache_dir) / CACHE_NAME).exists()


def test_start_rebuild_failure_shows_empty_list(tmp_path):
    client = FakeClient()

    def boom():
        raise BukuCliError("offline")

    client.list_all = boom
    app = make_app(tmp_path, client=client, refs=None)
    screen = app.start()
    assert screen.refs == []


def test_start_with_empty_database(tmp_path):
    app = make_app(tmp_path, refs=[])
    screen = app.start()
    assert screen.refs == []
    assert screen.visible == []


def test_clipboard_url_prefills_query_and_lists_matches(tmp_path):
    app = make_app(
        tmp_path,
        clipboard=FakeClipboard("https://github.com/settings"),
        refs=[
            ref(1, "GitHub", "https://github.com"),
            ref(2, "GitHub Enterprise", "https://github.com/enterprise"),
            ref(3, "Bank", "https://bank.example.com"),
            ref(4, "GitHub user page", "https://github.com/settings"),
        ],
    )
    screen = app.start()
    assert isinstance(screen, ListScreen)
    assert screen.query == "github.com"
    assert screen.host_filter == "github.com"
    # While the host is still in the query, matching is precise:
    # only the three github.com bookmarks are visible.
    visible = screen.visible
    assert [r.title for r in visible] == [
        "GitHub",
        "GitHub Enterprise",
        "GitHub user page",
    ]
    # The full refs list still holds everything (the status bar shows
    # "3/4 bookmarks").
    assert len(screen.refs) == 4


def test_clipboard_url_with_no_match_shows_full_list(tmp_path):
    app = make_app(
        tmp_path,
        clipboard=FakeClipboard("https://nothing.example"),
        refs=[ref(1)],
    )
    screen = app.start()
    assert screen.query == ""
    assert [r.title for r in screen.refs] == ["GitHub"]


def test_clipboard_non_url_is_ignored(tmp_path):
    app = make_app(tmp_path, clipboard=FakeClipboard("just some text"), refs=[ref(1)])
    screen = app.start()
    assert screen.query == ""


def test_enter_raises_open_requested_with_selected_ref(tmp_path):
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com")])
    app.start()
    app.handle_key("down")  # Bank first (title-sorted), GitHub second
    app.handle_key("up")
    with pytest.raises(OpenRequested) as exc_info:
        app.handle_key("enter")
    assert exc_info.value.ref.title == "Bank"


def test_enter_with_no_selection_does_nothing(tmp_path):
    app = make_app(tmp_path, refs=[])
    app.start()
    screen = app.handle_key("enter")
    assert screen.refs == []


def test_esc_clears_query_then_quits(tmp_path):
    app = make_app(tmp_path, refs=[ref(1)])
    app.start()
    app.handle_key("g")
    assert app.screen.query == "g"
    app.handle_key("esc")
    assert app.screen.query == ""
    with pytest.raises(QuitRequested):
        app.handle_key("esc")


def test_ctrl_c_quits(tmp_path):
    app = make_app(tmp_path, refs=[ref(1)])
    app.start()
    with pytest.raises(QuitRequested):
        app.handle_key("ctrl_c")


def test_typing_filters_live(tmp_path):
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com")])
    app.start()
    app.handle_key("b")
    app.handle_key("a")
    app.handle_key("n")
    app.handle_key("k")
    assert app.screen.query == "bank"
    assert [r.title for r in app.screen.visible] == ["Bank"]


def test_backspace_edits_query(tmp_path):
    app = make_app(tmp_path, refs=[ref(1)])
    app.start()
    app.handle_key("g")
    app.handle_key("i")
    app.handle_key("t")
    app.handle_key("backspace")
    assert app.screen.query == "gi"


def test_navigation_keys(tmp_path):
    refs = [ref(n, f"Item {n:02d}", f"https://item{n}.example") for n in range(1, 6)]
    app = make_app(tmp_path, refs=refs)
    app.start()
    assert app.screen.selected == 0
    app.handle_key("down")
    assert app.screen.selected == 1
    app.handle_key("pagedown")
    assert app.screen.selected == 4  # clamped to the last of 5
    app.handle_key("pageup")
    assert app.screen.selected == 0
    app.handle_key("end")
    assert app.screen.selected == 4
    app.handle_key("home")
    assert app.screen.selected == 0
    app.handle_key("up")
    assert app.screen.selected == 0  # clamped


def test_navigation_respects_filter(tmp_path):
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com")])
    app.start()
    app.handle_key("b")
    app.handle_key("a")
    app.handle_key("n")
    app.handle_key("k")
    app.handle_key("down")  # only one match: clamped to 0
    assert app.screen.selected == 0


def test_ctrl_r_refreshes_cache(tmp_path):
    client = FakeClient(items=([ref(1, "Fresh", "https://fresh.example")], 1))
    app = make_app(tmp_path, client=client, refs=[ref(1, "Old", "https://old.example")])
    app.start()
    assert [r.title for r in app.screen.refs] == ["Old"]
    screen = app.handle_key("ctrl_r")
    assert client.list_calls == 1
    assert [r.title for r in screen.refs] == ["Fresh"]


def test_ctrl_r_failure_shows_message(tmp_path):
    client = FakeClient()

    def boom():
        raise BukuCliError("offline")

    client.list_all = boom
    app = make_app(tmp_path, client=client, refs=[ref(1)])
    app.start()
    screen = app.handle_key("ctrl_r")
    assert "Refresh failed" in screen.message
    assert [r.title for r in screen.refs] == ["GitHub"]  # old cache kept


def test_selection_resets_when_query_changes(tmp_path):
    refs = [ref(n, f"Item {n:02d}", f"https://item{n}.example") for n in range(1, 6)]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("end")
    assert app.screen.selected == 4
    app.handle_key("1")
    assert app.screen.selected == 0

from pathlib import Path

import pytest

from buku_tui.app import (
    App,
    ConfirmScreen,
    DetailScreen,
    EditScreen,
    ListScreen,
    OpenRequested,
    QuitRequested,
)
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
        self._refs = {r.index: r for r in (items[0] if items else [])}
        self._next_index = max(self._refs.keys(), default=0) + 1
        self.added = []
        self.updated = []
        self.deleted = []

    def list_all(self):
        self.list_calls += 1
        return list(self._refs.values()), len(self._refs)

    def open(self, ref):
        raise AssertionError("open must not be called by the controller")

    def add(self, url, title, tags, desc):
        idx = self._next_index
        self._next_index += 1
        new_ref = BookmarkRef(index=idx, url=url, title=title, tags=tuple(tags), description=desc)
        self._refs[idx] = new_ref
        self.added.append((url, title, list(tags), desc))
        return idx

    def update(self, index, url, title, tags, desc):
        if index not in self._refs:
            raise BukuCliError(f"no bookmark at index {index}")
        self._refs[index] = BookmarkRef(
            index=index, url=url, title=title, tags=tuple(tags), description=desc
        )
        self.updated.append((index, url, title, list(tags), desc))
        return True

    def delete(self, index):
        if index not in self._refs:
            raise BukuCliError(f"no bookmark at index {index}")
        del self._refs[index]
        self.deleted.append(index)
        return True


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


def test_enter_with_no_selection_does_nothing(tmp_path):
    app = make_app(tmp_path, refs=[])
    app.start()
    screen = app.handle_key("enter")
    assert screen.refs == []


def test_empty_query_shows_no_items(tmp_path):
    """With an empty search field the list is empty; typing reveals items."""
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com")])
    screen = app.start()
    assert screen.query == ""
    assert screen.visible == []
    app.handle_key("b")
    app.handle_key("a")
    app.handle_key("n")
    app.handle_key("k")
    assert [r.title for r in app.screen.visible] == ["Bank"]
    app.handle_key("backspace")
    app.handle_key("backspace")
    app.handle_key("backspace")
    app.handle_key("backspace")
    assert app.screen.visible == []


def test_swedish_characters_are_accepted_in_query(tmp_path):
    app = make_app(tmp_path, refs=[ref(1, "Räksmörgås", "https://food.example.se", ("mat",))])
    app.start()
    for ch in "räk":
        app.handle_key(ch)
    assert app.screen.query == "räk"
    assert [r.title for r in app.screen.visible] == ["Räksmörgås"]


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
    app.handle_key("i")  # one char is enough to show the list
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
    app.handle_key("i")
    app.handle_key("end")
    assert app.screen.selected == 4
    app.handle_key("1")
    assert app.screen.selected == 0


# ============================================================ detail view


def test_enter_in_list_opens_detail_not_browser(tmp_path):
    app = make_app(tmp_path, refs=[ref(1), ref(2, "Bank", "https://bank.example.com")])
    app.start()
    app.handle_key("b")
    app.handle_key("a")
    app.handle_key("n")
    app.handle_key("k")
    screen = app.handle_key("enter")
    assert isinstance(screen, DetailScreen)
    assert screen.ref.title == "Bank"


def test_detail_esc_returns_to_list(tmp_path):
    app = make_app(tmp_path, refs=[ref(1)])
    app.start()
    app.handle_key("g")
    app.handle_key("enter")
    assert isinstance(app.screen, DetailScreen)
    screen = app.handle_key("esc")
    assert isinstance(screen, ListScreen)


def test_detail_enter_copies_url_and_quits(tmp_path):
    clipboard = FakeClipboard()
    app = make_app(tmp_path, clipboard=clipboard, refs=[ref(1, url="https://github.com")])
    app.start()
    app.handle_key("g")
    app.handle_key("enter")
    assert isinstance(app.screen, DetailScreen)
    with pytest.raises(QuitRequested):
        app.handle_key("enter")
    assert clipboard.written == ["https://github.com"]


# ============================================================ add


def test_ctrl_a_opens_add_form(tmp_path):
    app = make_app(tmp_path, refs=[ref(1)])
    app.start()
    screen = app.handle_key("ctrl_a")
    assert isinstance(screen, EditScreen)
    assert screen.is_new
    assert screen.values == {"url": "", "title": "", "tags": "", "desc": ""}


def test_tab_opens_add_form(tmp_path):
    app = make_app(tmp_path, refs=[ref(1)])
    app.start()
    screen = app.handle_key("tab")
    assert isinstance(screen, EditScreen)
    assert screen.is_new


def test_add_bookmark_flow(tmp_path):
    client = FakeClient()
    app = make_app(tmp_path, client=client, refs=[ref(1, "Existing")])
    app.start()
    screen = app.handle_key("ctrl_a")
    assert isinstance(screen, EditScreen)

    for ch in "https://new.example.com":
        screen = app.handle_key(ch)
    assert screen.values["url"] == "https://new.example.com"

    screen = app.handle_key("down")
    assert screen.current_field == "title"
    for ch in "New Site":
        screen = app.handle_key(ch)
    assert screen.values["title"] == "New Site"

    screen = app.handle_key("down")
    assert screen.current_field == "tags"
    for ch in "web, test":
        screen = app.handle_key(ch)
    assert screen.values["tags"] == "web, test"

    screen = app.handle_key("down")
    assert screen.current_field == "desc"
    for ch in "A test site":
        screen = app.handle_key(ch)

    screen = app.handle_key("enter")
    assert isinstance(screen, ListScreen)
    assert "Added" in screen.message
    assert len(client.added) == 1
    url, title, tags, desc = client.added[0]
    assert url == "https://new.example.com"
    assert title == "New Site"
    assert tags == ["web", "test"]
    assert desc == "A test site"


def test_add_with_ctrl_s(tmp_path):
    client = FakeClient()
    app = make_app(tmp_path, client=client, refs=[])
    app.start()
    screen = app.handle_key("ctrl_a")
    for ch in "https://x.com":
        screen = app.handle_key(ch)
    screen = app.handle_key("ctrl_s")
    assert isinstance(screen, ListScreen)
    assert len(client.added) == 1


def test_add_requires_url(tmp_path):
    client = FakeClient()
    app = make_app(tmp_path, client=client, refs=[])
    app.start()
    screen = app.handle_key("ctrl_a")
    for _ in range(4):
        screen = app.handle_key("down")
    screen = app.handle_key("enter")
    assert isinstance(screen, EditScreen)
    assert "URL is required" in screen.message
    assert len(client.added) == 0


def test_add_esc_cancels(tmp_path):
    client = FakeClient()
    app = make_app(tmp_path, client=client, refs=[])
    app.start()
    screen = app.handle_key("ctrl_a")
    screen = app.handle_key("esc")
    assert isinstance(screen, ListScreen)
    assert len(client.added) == 0


# ============================================================ edit


def test_e_opens_edit_form(tmp_path):
    refs = [ref(1, title="GitHub", url="https://github.com", tags=("dev", "code"))]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("g")
    app.handle_key("enter")
    screen = app.handle_key("e")
    assert isinstance(screen, EditScreen)
    assert not screen.is_new
    assert screen.editing_index == 1
    assert screen.values["url"] == "https://github.com"
    assert screen.values["title"] == "GitHub"
    assert screen.values["tags"] == "dev, code"


def test_edit_bookmark_flow(tmp_path):
    refs = [ref(1, title="Old Title", url="https://old.com", tags=("a",), description="old desc")]
    client = FakeClient(items=(refs, len(refs)))
    app = make_app(tmp_path, client=client, refs=refs)
    app.start()
    app.handle_key("o")
    app.handle_key("enter")
    screen = app.handle_key("e")
    assert isinstance(screen, EditScreen)

    screen = app.handle_key("down")  # title
    screen = app.handle_key("end")
    for _ in range(len("Old Title")):
        screen = app.handle_key("backspace")
    for ch in "New Title":
        screen = app.handle_key(ch)
    assert screen.values["title"] == "New Title"

    screen = app.handle_key("down")  # tags
    screen = app.handle_key("down")  # desc
    screen = app.handle_key("enter")  # save
    assert isinstance(screen, ListScreen)
    assert "Updated" in screen.message
    assert len(client.updated) == 1
    idx, url, title, tags, desc = client.updated[0]
    assert idx == 1
    assert title == "New Title"


def test_edit_cursor_movement(tmp_path):
    refs = [ref(1, url="https://example.com")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("e")
    app.handle_key("enter")
    screen = app.handle_key("e")
    assert screen.cursor == len("https://example.com")

    screen = app.handle_key("home")
    assert screen.cursor == 0
    screen = app.handle_key("right")
    assert screen.cursor == 1
    screen = app.handle_key("end")
    assert screen.cursor == len("https://example.com")
    screen = app.handle_key("left")
    assert screen.cursor == len("https://example.com") - 1


def test_edit_backspace(tmp_path):
    refs = [ref(1, url="https://example.com")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("e")
    app.handle_key("enter")
    screen = app.handle_key("e")
    screen = app.handle_key("end")
    screen = app.handle_key("backspace")
    assert screen.values["url"] == "https://example.co"
    assert screen.cursor == len("https://example.co")


def test_edit_insert_in_middle(tmp_path):
    refs = [ref(1, url="https://example.com")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("e")
    app.handle_key("enter")
    screen = app.handle_key("e")
    screen = app.handle_key("home")
    for ch in "XX":
        screen = app.handle_key(ch)
    assert screen.values["url"] == "XXhttps://example.com"


def test_edit_tab_navigates_fields(tmp_path):
    refs = [ref(1)]
    client = FakeClient(items=(refs, 1))
    app = make_app(tmp_path, client=client, refs=refs)
    app.start()
    app.handle_key("e")
    app.handle_key("enter")
    screen = app.handle_key("e")
    assert screen.field_idx == 0
    screen = app.handle_key("tab")
    assert screen.field_idx == 1
    screen = app.handle_key("tab")
    assert screen.field_idx == 2
    screen = app.handle_key("tab")
    assert screen.field_idx == 3
    screen = app.handle_key("tab")
    assert isinstance(screen, ListScreen)


def test_edit_esc_cancels(tmp_path):
    refs = [ref(1, title="Test")]
    client = FakeClient(items=(refs, 1))
    app = make_app(tmp_path, client=client, refs=refs)
    app.start()
    app.handle_key("t")
    app.handle_key("enter")
    screen = app.handle_key("e")
    screen = app.handle_key("esc")
    assert isinstance(screen, ListScreen)
    assert len(client.updated) == 0


# ============================================================ delete


def test_d_opens_confirm(tmp_path):
    refs = [ref(1, title="ToDelete")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("t")
    app.handle_key("enter")
    screen = app.handle_key("d")
    assert isinstance(screen, ConfirmScreen)
    assert screen.action == "delete"
    assert screen.ref.title == "ToDelete"


def test_delete_confirmed_with_y(tmp_path):
    refs = [ref(1, title="ToDelete", url="https://del.com")]
    client = FakeClient(items=(refs, 1))
    app = make_app(tmp_path, client=client, refs=refs)
    app.start()
    app.handle_key("t")
    app.handle_key("enter")
    app.handle_key("d")
    screen = app.handle_key("y")
    assert isinstance(screen, ListScreen)
    assert "Deleted" in screen.message
    assert client.deleted == [1]


def test_delete_confirmed_with_enter(tmp_path):
    refs = [ref(1, title="ToDelete")]
    client = FakeClient(items=(refs, 1))
    app = make_app(tmp_path, client=client, refs=refs)
    app.start()
    app.handle_key("t")
    app.handle_key("enter")
    app.handle_key("d")
    screen = app.handle_key("enter")
    assert isinstance(screen, ListScreen)
    assert client.deleted == [1]


def test_delete_cancelled_with_n(tmp_path):
    refs = [ref(1, title="Keep")]
    client = FakeClient(items=(refs, 1))
    app = make_app(tmp_path, client=client, refs=refs)
    app.start()
    app.handle_key("k")
    app.handle_key("enter")
    app.handle_key("d")
    screen = app.handle_key("n")
    assert isinstance(screen, ListScreen)
    assert client.deleted == []


def test_delete_cancelled_with_esc(tmp_path):
    refs = [ref(1, title="Keep")]
    client = FakeClient(items=(refs, 1))
    app = make_app(tmp_path, client=client, refs=refs)
    app.start()
    app.handle_key("k")
    app.handle_key("enter")
    app.handle_key("d")
    screen = app.handle_key("esc")
    assert isinstance(screen, ListScreen)
    assert client.deleted == []


def test_delete_arrow_toggle(tmp_path):
    refs = [ref(1, title="Test")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("t")
    app.handle_key("enter")
    screen = app.handle_key("d")
    assert screen.selected == 0
    screen = app.handle_key("right")
    assert screen.selected == 1
    screen = app.handle_key("left")
    assert screen.selected == 0


# ============================================================ full CRUD


def test_full_crud_cycle(tmp_path):
    initial_refs = [ref(1, "Existing", "https://existing.com")]
    client = FakeClient(items=(initial_refs, 1))
    app = make_app(tmp_path, client=client, refs=initial_refs)
    app.start()

    # Add
    screen = app.handle_key("ctrl_a")
    for ch in "https://crud.example.com":
        screen = app.handle_key(ch)
    screen = app.handle_key("down")
    for ch in "CRUD Test":
        screen = app.handle_key(ch)
    screen = app.handle_key("down")
    for ch in "test, crud":
        screen = app.handle_key(ch)
    screen = app.handle_key("down")
    for ch in "A CRUD test bookmark":
        screen = app.handle_key(ch)
    screen = app.handle_key("enter")
    assert isinstance(screen, ListScreen)
    assert "Added" in screen.message
    assert len(client._refs) == 2

    # Edit: type to search for the newly added bookmark, then open it
    screen = app.handle_key("c")
    screen = app.handle_key("r")
    screen = app.handle_key("u")
    screen = app.handle_key("d")
    screen = app.handle_key("enter")
    assert isinstance(screen, DetailScreen)
    screen = app.handle_key("e")
    assert isinstance(screen, EditScreen)
    screen = app.handle_key("down")  # title
    screen = app.handle_key("end")
    for _ in range(len("CRUD Test")):
        screen = app.handle_key("backspace")
    for ch in "Updated Title":
        screen = app.handle_key(ch)
    screen = app.handle_key("down")  # tags
    screen = app.handle_key("down")  # desc
    screen = app.handle_key("ctrl_s")
    assert isinstance(screen, ListScreen)
    assert "Updated" in screen.message

    updated = client._refs[2]
    assert updated.title == "Updated Title"

    # Delete: search for the updated bookmark, open it, delete it
    screen = app.handle_key("u")
    screen = app.handle_key("p")
    screen = app.handle_key("d")
    screen = app.handle_key("a")
    screen = app.handle_key("t")
    screen = app.handle_key("e")
    screen = app.handle_key("d")
    screen = app.handle_key("enter")
    assert isinstance(screen, DetailScreen)
    screen = app.handle_key("d")
    assert isinstance(screen, ConfirmScreen)
    screen = app.handle_key("y")
    assert isinstance(screen, ListScreen)
    assert "Deleted" in screen.message
    assert len(client._refs) == 1


def test_add_from_detail_view(tmp_path):
    refs = [ref(1, title="Existing")]
    app = make_app(tmp_path, refs=refs)
    app.start()
    app.handle_key("e")
    app.handle_key("enter")
    screen = app.handle_key("ctrl_a")
    assert isinstance(screen, EditScreen)
    assert screen.is_new


def test_backend_error_on_add(tmp_path):
    class FailingClient(FakeClient):
        def add(self, url, title, tags, desc):
            raise BukuCliError("disk full")

    client = FailingClient()
    app = make_app(tmp_path, client=client, refs=[])
    app.start()
    screen = app.handle_key("ctrl_a")
    for ch in "https://x.com":
        screen = app.handle_key(ch)
    screen = app.handle_key("ctrl_s")
    assert isinstance(screen, EditScreen)
    assert "Error" in screen.message


def test_backend_error_on_delete(tmp_path):
    class FailingDeleteClient(FakeClient):
        def delete(self, index):
            raise BukuCliError("permission denied")

    refs = [ref(1, title="Test")]
    client = FailingDeleteClient(items=(refs, 1))
    app = make_app(tmp_path, client=client, refs=refs)
    app.start()
    app.handle_key("t")
    app.handle_key("enter")
    app.handle_key("d")
    screen = app.handle_key("y")
    assert isinstance(screen, ListScreen)
    assert "Delete failed" in screen.message

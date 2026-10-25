"""Tests for the App controller."""

import pytest

from bookmark_tui.app import (
    App,
    ConfirmScreen,
    DetailScreen,
    EditScreen,
    ListScreen,
    OpenRequested,
    QuitRequested,
)
from bookmark_tui.models import Bookmark
from bookmark_tui.storage import BookmarkStore


def make_store(tmp_path, bookmarks=None):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    if bookmarks:
        for url, title, category in bookmarks:
            store.add(url, title, category)
    return store


def make_app(tmp_path, bookmarks=None):
    store = make_store(tmp_path, bookmarks)
    opened = []
    app = App(store, open_url=lambda url: opened.append(url))
    app._opened = opened
    return app


SAMPLE = [
    ("https://github.com", "GitHub", "dev/tools"),
    ("https://bank.example.com", "Bank", "finance"),
    ("https://recipes.example.com", "Pasta Recipes", "food/recipes"),
]


# ------------------------------------------------------------ list screen


def test_start_returns_list_screen(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    screen = app.start()
    assert isinstance(screen, ListScreen)
    assert len(screen.bookmarks) == 3


def test_empty_query_shows_nothing(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    screen = app.start()
    assert screen.visible == []


def test_typing_filters_list(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    screen = app.screen
    assert isinstance(screen, ListScreen)
    assert len(screen.visible) == 1
    assert screen.visible[0].title == "GitHub"


def test_backspace_clears_query(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("i")
    app.handle_key("backspace")
    screen = app.screen
    assert screen.query == "g"


def test_esc_clears_query_first(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    screen = app.handle_key("esc")
    assert isinstance(screen, ListScreen)
    assert screen.query == ""


def test_esc_quits_when_query_empty(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    with pytest.raises(QuitRequested):
        app.handle_key("esc")


def test_ctrl_c_quits(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    with pytest.raises(QuitRequested):
        app.handle_key("ctrl_c")


def test_enter_opens_url(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    with pytest.raises(OpenRequested) as exc_info:
        app.handle_key("enter")
    assert exc_info.value.bookmark.url == "https://github.com"


def test_enter_with_no_selection_does_nothing(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    screen = app.handle_key("enter")
    assert isinstance(screen, ListScreen)


def test_ctrl_o_opens_detail(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    screen = app.handle_key("ctrl_o")
    assert isinstance(screen, DetailScreen)
    assert screen.bookmark.title == "GitHub"


def test_navigation(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    # Use "o" which matches all three (github.com, bank.example.com, food)
    # Actually let's use a query that matches all: "e" matches all titles/urls
    app.handle_key("e")
    screen = app.screen
    assert len(screen.visible) == 3
    assert screen.selected == 0
    screen = app.handle_key("down")
    assert screen.selected == 1
    screen = app.handle_key("down")
    assert screen.selected == 2
    screen = app.handle_key("down")
    assert screen.selected == 2  # clamped
    screen = app.handle_key("up")
    assert screen.selected == 1


def test_home_end(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("e")
    app.handle_key("end")
    assert app.screen.selected == 2
    app.handle_key("home")
    assert app.screen.selected == 0


# ------------------------------------------------------------ detail screen


def test_detail_enter_opens_url(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    with pytest.raises(OpenRequested) as exc_info:
        app.handle_key("enter")
    assert exc_info.value.bookmark.url == "https://github.com"


def test_detail_esc_returns_to_list(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    screen = app.handle_key("esc")
    assert isinstance(screen, ListScreen)


def test_detail_preserves_query(tmp_path):
    """The search query persists when going to detail and back."""
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("i")
    app.handle_key("t")
    app.handle_key("ctrl_o")
    screen = app.handle_key("esc")
    assert isinstance(screen, ListScreen)
    assert screen.query == "git"


def test_detail_e_opens_edit(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    screen = app.handle_key("e")
    assert isinstance(screen, EditScreen)
    assert not screen.is_new
    assert screen.editing_id is not None


def test_detail_d_opens_confirm(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    screen = app.handle_key("d")
    assert isinstance(screen, ConfirmScreen)


# ------------------------------------------------------------ edit screen


def test_edit_save_updates_bookmark(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("e")
    screen = app.screen
    assert isinstance(screen, EditScreen)
    # Clear URL field and type new URL
    for _ in range(len(screen.values["url"])):
        app.handle_key("backspace")
    for ch in "https://new.com":
        app.handle_key(ch)
    # Move to title field
    app.handle_key("tab")
    for _ in range(len(app.screen.values["title"])):
        app.handle_key("backspace")
    for ch in "New Title":
        app.handle_key(ch)
    # Save (on last field, press enter; or ctrl_s)
    screen = app.handle_key("ctrl_s")
    assert isinstance(screen, ListScreen)
    bm = app.store.get(1)
    assert bm.url == "https://new.com"
    assert bm.title == "New Title"


def test_edit_save_returns_to_list_not_start(tmp_path):
    """After saving an edit, the user should see the list (with query
    preserved), not the start screen."""
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")  # search for "g"
    app.handle_key("ctrl_o")
    app.handle_key("e")
    app.handle_key("ctrl_s")
    screen = app.screen
    assert isinstance(screen, ListScreen)
    assert screen.query == "g"  # query preserved


def test_edit_esc_cancels(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("e")
    screen = app.handle_key("esc")
    assert isinstance(screen, ListScreen)
    assert screen.query == "g"


def test_edit_requires_url(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("ctrl_a")  # add new
    screen = app.screen
    assert isinstance(screen, EditScreen)
    assert screen.is_new
    # Try to save without URL
    screen = app.handle_key("ctrl_s")
    assert isinstance(screen, EditScreen)
    assert "URL is required" in screen.message


def test_edit_field_navigation(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("ctrl_a")
    # Fill in URL first so save succeeds
    for ch in "https://x.com":
        app.handle_key(ch)
    screen = app.screen
    assert screen.field_idx == 0  # url
    app.handle_key("tab")
    assert app.screen.field_idx == 1  # title
    app.handle_key("tab")
    assert app.screen.field_idx == 2  # category
    app.handle_key("tab")
    # On last field, tab saves
    assert isinstance(app.screen, ListScreen)


def test_edit_cursor_movement(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("ctrl_a")
    for ch in "abc":
        app.handle_key(ch)
    screen = app.screen
    assert screen.current_value == "abc"
    assert screen.cursor == 3
    app.handle_key("left")
    assert app.screen.cursor == 2
    app.handle_key("home")
    assert app.screen.cursor == 0
    app.handle_key("end")
    assert app.screen.cursor == 3


def test_edit_backspace(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("ctrl_a")
    for ch in "abc":
        app.handle_key(ch)
    app.handle_key("backspace")
    assert app.screen.current_value == "ab"
    assert app.screen.cursor == 2


def test_edit_backspace_at_start(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("ctrl_a")
    app.handle_key("backspace")
    assert app.screen.current_value == ""


# ------------------------------------------------------------ add


def test_add_bookmark(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("ctrl_a")
    for ch in "https://new.com":
        app.handle_key(ch)
    app.handle_key("tab")
    for ch in "New Site":
        app.handle_key(ch)
    app.handle_key("tab")
    for ch in "dev/new":
        app.handle_key(ch)
    screen = app.handle_key("ctrl_s")
    assert isinstance(screen, ListScreen)
    assert len(app.store.all) == 4
    new_bm = [b for b in app.store.all if b.url == "https://new.com"][0]
    assert new_bm.title == "New Site"
    assert new_bm.category == "dev/new"


def test_add_from_detail(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    screen = app.handle_key("ctrl_a")
    assert isinstance(screen, EditScreen)
    assert screen.is_new


# ------------------------------------------------------------ delete


def test_delete_confirmed(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("d")
    screen = app.handle_key("y")
    assert isinstance(screen, ListScreen)
    assert len(app.store.all) == 2


def test_delete_enter_confirms(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("d")
    screen = app.handle_key("enter")
    assert isinstance(screen, ListScreen)
    assert len(app.store.all) == 2


def test_delete_cancelled(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("d")
    screen = app.handle_key("n")
    assert isinstance(screen, ListScreen)
    assert len(app.store.all) == 3


def test_delete_esc_cancels(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("d")
    screen = app.handle_key("esc")
    assert isinstance(screen, ListScreen)
    assert len(app.store.all) == 3


def test_confirm_toggle_with_arrows(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("d")
    screen = app.screen
    assert screen.selected == 0  # Yes
    app.handle_key("right")
    assert app.screen.selected == 1  # No
    app.handle_key("left")
    assert app.screen.selected == 0  # Yes


# ------------------------------------------------------------ query persistence


def test_query_preserved_across_edit(tmp_path):
    """Search for something, open detail, edit, save — query should persist."""
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("f")  # search "f" (matches food, finance)
    app.handle_key("ctrl_o")
    app.handle_key("e")
    app.handle_key("ctrl_s")  # save
    screen = app.screen
    assert isinstance(screen, ListScreen)
    assert screen.query == "f"


def test_query_preserved_across_delete(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("f")
    app.handle_key("ctrl_o")
    app.handle_key("d")
    app.handle_key("y")
    screen = app.screen
    assert isinstance(screen, ListScreen)
    assert screen.query == "f"


def test_query_preserved_across_add(tmp_path):
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("f")
    app.handle_key("ctrl_a")
    for ch in "https://x.com":
        app.handle_key(ch)
    app.handle_key("ctrl_s")
    screen = app.screen
    assert isinstance(screen, ListScreen)
    assert screen.query == "f"


# ------------------------------------------------------------ full CRUD cycle


def test_full_crud_cycle(tmp_path):
    app = make_app(tmp_path)
    app.start()

    # Add
    app.handle_key("ctrl_a")
    for ch in "https://test.com":
        app.handle_key(ch)
    app.handle_key("tab")
    for ch in "Test Site":
        app.handle_key(ch)
    app.handle_key("tab")
    for ch in "dev/test":
        app.handle_key(ch)
    app.handle_key("ctrl_s")
    assert len(app.store.all) == 1

    # Search and open detail
    app.handle_key("t")
    app.handle_key("ctrl_o")
    assert isinstance(app.screen, DetailScreen)

    # Edit: cursor starts at end of URL field, switch to title field
    app.handle_key("e")
    # Move to title field (field_idx 1)
    app.handle_key("down")
    assert app.screen.field_idx == 1
    # Clear title and type new one
    for _ in range(len(app.screen.values["title"])):
        app.handle_key("backspace")
    for ch in "Updated":
        app.handle_key(ch)
    app.handle_key("ctrl_s")
    assert app.store.get(1).title == "Updated"

    # Delete
    app.handle_key("t")  # search again (query was preserved as "t")
    app.handle_key("ctrl_o")
    app.handle_key("d")
    app.handle_key("y")
    assert len(app.store.all) == 0

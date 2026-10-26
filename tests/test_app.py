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


# ------------------------------------------------------------ open url


@pytest.mark.parametrize(
    "platform,prefix_env,expected_argv,detached",
    [
        ("linux", {}, ["xdg-open", "https://example.com"], True),
        ("darwin", {}, ["open", "https://example.com"], True),
        ("win32", {}, ["cmd", "/c", "start", "https://example.com"], False),
        # Termux reports linux, but must use termux-open-url
        ("linux", {"PREFIX": "/data/data/com.termux/files/usr"}, ["termux-open-url", "https://example.com"], True),
        ("linux", {"TERMUX_VERSION": "0.118"}, ["termux-open-url", "https://example.com"], True),
        # Termux wins even on other platforms
        ("darwin", {"PREFIX": "/data/data/com.termux/files/usr"}, ["termux-open-url", "https://example.com"], True),
    ],
)
def test_default_open_url_detaches_from_terminal(
    monkeypatch, platform, prefix_env, expected_argv, detached
):
    """The browser opener must run in its own session with no stdio
    attached, so it survives bookmark-tui exiting — otherwise launching
    via `ghostty -e bookmark-tui` kills the opener with SIGHUP."""
    import bookmark_tui.app as app_mod

    calls = []

    class FakePopen:
        def __init__(self, argv, **kwargs):
            calls.append((argv, kwargs))

    monkeypatch.setattr(app_mod.subprocess, "Popen", FakePopen)
    monkeypatch.setattr("sys.platform", platform)
    monkeypatch.delenv("PREFIX", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    for key, value in prefix_env.items():
        monkeypatch.setenv(key, value)
    app_mod._default_open_url("https://example.com")

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == expected_argv
    assert bool(kwargs.get("start_new_session")) is detached
    assert kwargs.get("stdin") is app_mod.subprocess.DEVNULL
    assert kwargs.get("stdout") is app_mod.subprocess.DEVNULL
    assert kwargs.get("stderr") is app_mod.subprocess.DEVNULL


# ------------------------------------------------------------ folder view


FOLDER_SAMPLE = [
    ("https://github.com", "GitHub", "dev/tools"),
    ("https://gitlab.com", "GitLab", "dev"),
    ("https://bank.example.com", "Bank", "finance"),
    ("https://pasta.example.com", "Pasta", "food/recipes"),
    ("https://cake.example.com", "Cake", "food/recipes/vegan"),
    ("https://soup.example.com", "Soup", "food/soups"),
    ("https://example.com", "NoCat", ""),
]


def test_folder_tree_top_level(tmp_path):
    from bookmark_tui.app import folder_tree
    store = make_store(tmp_path, FOLDER_SAMPLE)
    assert folder_tree(store.all) == ["dev", "finance", "food"]


def test_folder_tree_second_level(tmp_path):
    from bookmark_tui.app import folder_tree
    store = make_store(tmp_path, FOLDER_SAMPLE)
    assert folder_tree(store.all, "food") == ["food/recipes", "food/soups"]
    assert folder_tree(store.all, "food/recipes") == ["food/recipes/vegan"]
    assert folder_tree(store.all, "dev") == ["dev/tools"]
    assert folder_tree(store.all, "finance") == []


def test_ctrl_f_enters_folder_mode(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    assert isinstance(app.screen, ListScreen)
    assert app.screen.folder_mode is True
    assert app.screen.folders == ["dev", "finance", "food"]


def test_folder_mode_enter_descends(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("down")  # finance
    app.handle_key("down")  # food
    app.handle_key("enter")
    assert app.screen.folder_mode is True
    assert app.screen.folder_path == "food"
    assert app.screen.folders == ["food/recipes", "food/soups"]


def test_folder_mode_esc_goes_up_then_to_list(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("enter")  # into dev
    assert app.screen.folder_path == "dev"
    app.handle_key("esc")  # back to top level
    assert app.screen.folder_mode is True
    assert app.screen.folder_path == ""
    app.handle_key("esc")  # back to search list
    assert app.screen.folder_mode is False


def test_folder_mode_ctrl_f_returns_to_list(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("ctrl_f")
    assert app.screen.folder_mode is False


def test_folder_mode_search_list_unaffected(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    # In folder mode there is no query filtering of bookmarks
    assert app.screen.visible == []


def test_folder_delete_flow(tmp_path):
    from bookmark_tui.app import FolderConfirmScreen
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("down")  # finance
    app.handle_key("down")  # food
    app.handle_key("enter")  # into food
    app.handle_key("d")  # delete food/recipes (first)
    screen = app.screen
    assert isinstance(screen, FolderConfirmScreen)
    assert screen.folder == "food/recipes"
    assert screen.count == 2  # pasta + cake
    app.handle_key("y")
    assert app.screen.folder_mode is True
    assert app.screen.folder_path == "food"
    assert "Deleted folder: food/recipes (2 bookmarks)" in app.screen.message
    urls = sorted(b.url for b in app.store.all)
    assert "https://pasta.example.com" not in urls
    assert "https://cake.example.com" not in urls
    assert "https://soup.example.com" in urls
    assert "https://github.com" in urls


def test_folder_delete_cancel_keeps_bookmarks(tmp_path):
    from bookmark_tui.app import FolderConfirmScreen
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("d")  # delete dev (first)
    assert isinstance(app.screen, FolderConfirmScreen)
    app.handle_key("n")
    assert app.screen.folder_mode is True
    assert len(app.store.all) == 7


def test_folder_confirm_toggle_yes_no(tmp_path):
    from bookmark_tui.app import FolderConfirmScreen
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("d")
    assert app.screen.selected == 0
    app.handle_key("right")
    assert app.screen.selected == 1
    app.handle_key("left")
    assert app.screen.selected == 0


def test_category_count(tmp_path):
    from bookmark_tui.app import category_count
    store = make_store(tmp_path, FOLDER_SAMPLE)
    assert category_count(store.all, "food", store) == 3
    assert category_count(store.all, "food/recipes", store) == 2
    assert category_count(store.all, "dev", store) == 2
    assert category_count(store.all, "finance", store) == 1
    assert category_count(store.all, "nope", store) == 0


# ------------------------------------------------------------ folder rows, marks, rename, move, duplicate


def test_folder_rows_mix_folders_and_bookmarks(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    rows = app.screen.rows
    kinds = [r.kind for r in rows]
    # top level: folders dev, finance, food + uncategorized bookmark
    assert kinds == ["folder", "folder", "folder", "bookmark"]
    assert rows[0].folder == "dev"
    assert rows[-1].bookmark.title == "NoCat"


def test_folder_rows_in_folder_show_direct_bookmarks(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("down")
    app.handle_key("down")
    app.handle_key("enter")  # into food
    rows = app.screen.rows
    assert [r.kind for r in rows] == ["folder", "folder"]
    app.handle_key("enter")  # into food/recipes
    rows = app.screen.rows
    assert [r.kind for r in rows] == ["folder", "bookmark"]
    assert rows[0].folder == "food/recipes/vegan"
    assert rows[1].bookmark.title == "Pasta"


def test_folder_enter_on_bookmark_opens_url(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    # navigate to the uncategorized bookmark (last row)
    for _ in range(3):
        app.handle_key("down")
    with pytest.raises(OpenRequested) as exc:
        app.handle_key("enter")
    assert exc.value.bookmark.url == "https://example.com"


def test_folder_ctrl_o_opens_detail_and_returns(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("down")
    app.handle_key("down")
    app.handle_key("enter")  # into food
    app.handle_key("enter")  # into food/recipes
    app.handle_key("down")  # onto Pasta bookmark row
    app.handle_key("ctrl_o")
    assert isinstance(app.screen, DetailScreen)
    assert app.screen.from_folder is True
    assert app.screen.from_folder_path == "food/recipes"
    app.handle_key("esc")
    assert app.screen.folder_mode is True
    assert app.screen.folder_path == "food/recipes"


def test_folder_edit_and_save_returns_to_folder(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("enter")  # into dev
    app.handle_key("down")  # onto GitLab bookmark row
    app.handle_key("ctrl_o")
    app.handle_key("e")
    assert isinstance(app.screen, EditScreen)
    app.handle_key("ctrl_s")
    assert app.screen.folder_mode is True
    assert app.screen.folder_path == "dev"
    assert "Updated: GitLab" in app.screen.message


def test_folder_delete_bookmark_returns_to_folder(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("enter")  # into dev
    app.handle_key("down")  # GitLab row
    app.handle_key("d")
    assert isinstance(app.screen, ConfirmScreen)
    app.handle_key("y")
    assert app.screen.folder_mode is True
    assert app.screen.folder_path == "dev"
    assert "Deleted: GitLab" in app.screen.message
    assert all(b.title != "GitLab" for b in app.store.all)


def test_folder_mark_toggle_and_move(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("enter")  # into dev
    app.handle_key("down")  # GitLab row
    app.handle_key(" ")  # mark GitLab
    assert app.screen.marks
    gitlab = next(b for b in app.store.all if b.title == "GitLab")
    assert gitlab.id in app.screen.marks
    app.handle_key(" ")  # unmark
    assert not app.screen.marks


def test_folder_mark_all_and_move(tmp_path):
    from bookmark_tui.app import PromptScreen
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("down")
    app.handle_key("down")
    app.handle_key("enter")  # into food
    app.handle_key("enter")  # into food/recipes -> rows: vegan folder, Pasta bookmark
    app.handle_key("down")  # Pasta
    app.handle_key(" ")  # mark Pasta
    app.handle_key("M")
    screen = app.screen
    assert isinstance(screen, PromptScreen)
    assert screen.kind == "move"
    for ch in "dev":
        app.handle_key(ch)
    # text is now "dev" (initial text was empty)
    app.handle_key("enter")
    assert app.screen.folder_mode is True
    pasta = next(b for b in app.store.all if b.title == "Pasta")
    assert pasta.category == "dev"
    assert not app.screen.marks  # marks cleared after move


def test_folder_mark_all_toggle(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("enter")  # into dev -> rows: tools folder, GitLab bookmark
    app.handle_key("A")  # mark all bookmarks in view (GitLab)
    gitlab = next(b for b in app.store.all if b.title == "GitLab")
    assert app.screen.marks == {gitlab.id}
    app.handle_key("A")  # unmark all
    assert app.screen.marks == set()


def test_folder_move_without_marks_shows_message(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("M")
    assert app.screen.folder_mode is True
    assert "No bookmarks marked" in app.screen.message


def test_folder_move_to_empty_uncategorizes(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("enter")  # into dev
    app.handle_key("down")  # GitLab
    app.handle_key(" ")
    app.handle_key("M")
    app.handle_key("enter")  # empty target
    gitlab = next(b for b in app.store.all if b.title == "GitLab")
    assert gitlab.category == ""


def test_folder_rename_flow(tmp_path):
    from bookmark_tui.app import PromptScreen
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("down")
    app.handle_key("down")  # food
    app.handle_key("r")
    screen = app.screen
    assert isinstance(screen, PromptScreen)
    assert screen.kind == "rename"
    assert screen.text == "food"  # pre-filled with current name
    assert screen.folder == "food"
    # clear and type new name
    for _ in range(4):
        app.handle_key("backspace")
    for ch in "cuisine":
        app.handle_key(ch)
    app.handle_key("enter")
    assert app.screen.folder_mode is True
    assert "Renamed food -> cuisine" in app.screen.message
    cats = {b.title: b.category for b in app.store.all}
    assert cats["Pasta"] == "cuisine/recipes"
    assert cats["Cake"] == "cuisine/recipes/vegan"
    assert cats["Soup"] == "cuisine/soups"


def test_folder_rename_to_existing_fails(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("r")  # rename dev
    for _ in range(3):
        app.handle_key("backspace")
    for ch in "food":
        app.handle_key(ch)
    app.handle_key("enter")
    assert "Could not rename" in app.screen.message
    cats = {b.title: b.category for b in app.store.all}
    assert cats["GitHub"] == "dev/tools"  # unchanged


def test_folder_rename_empty_cancels(tmp_path):
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("r")
    for _ in range(3):
        app.handle_key("backspace")
    app.handle_key("enter")
    assert "empty name" in app.screen.message


def test_folder_rename_esc_cancels(tmp_path):
    from bookmark_tui.app import PromptScreen
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("r")
    assert isinstance(app.screen, PromptScreen)
    app.handle_key("esc")
    assert app.screen.folder_mode is True
    assert all(b.category for b in app.store.all if b.title != "NoCat")


def test_duplicate_from_detail_opens_prefilled_add(tmp_path):
    from bookmark_tui.app import EditScreen
    app = make_app(tmp_path, SAMPLE)
    app.start()
    app.handle_key("g")
    app.handle_key("ctrl_o")
    app.handle_key("c")
    screen = app.screen
    assert isinstance(screen, EditScreen)
    assert screen.is_new  # duplicate creates a new bookmark
    assert screen.values["url"] == "https://github.com"
    assert screen.values["title"] == "GitHub"
    assert screen.values["category"] == "dev/tools"
    # save creates a second bookmark
    app.handle_key("ctrl_s")
    urls = [b.url for b in app.store.all]
    assert urls.count("https://github.com") == 2
    assert "Added: GitHub" in app.screen.message


def test_duplicate_from_folder_view(tmp_path):
    from bookmark_tui.app import EditScreen
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("enter")  # into dev
    app.handle_key("down")  # GitLab row
    app.handle_key("c")
    screen = app.screen
    assert isinstance(screen, EditScreen)
    assert screen.is_new
    assert screen.values["url"] == "https://gitlab.com"
    assert screen.from_folder is True
    app.handle_key("ctrl_s")
    assert app.screen.folder_mode is True
    assert app.screen.folder_path == "dev"
    assert len([b for b in app.store.all if b.url == "https://gitlab.com"]) == 2


def test_prompt_editing_keys(tmp_path):
    from bookmark_tui.app import PromptScreen
    app = make_app(tmp_path, FOLDER_SAMPLE)
    app.start()
    app.handle_key("ctrl_f")
    app.handle_key("r")  # rename dev, text prefilled "dev"
    app.handle_key("home")
    app.handle_key("x")
    assert app.screen.text == "xdev"
    app.handle_key("end")
    app.handle_key("backspace")
    assert app.screen.text == "xde"
    app.handle_key("left")
    app.handle_key("y")
    assert app.screen.text == "xdy e".replace(" ", "")

"""UI-agnostic controller for bookmark-tui.

Owns the whole interaction state machine: the bookmark list (with live
filter), the folder/category view, the detail view, the edit/add form,
and the delete confirmations. The controller never touches curses: it
exposes the current screen as a plain dataclass plus a handle_key
method that returns the next screen.

Key bindings:
- Enter opens the selected bookmark's URL in the browser and quits
  (rofi-style: one selection ends the run). In folder view, Enter
  descends into the selected folder.
- Ctrl+o opens the detail view for the selected bookmark.
- Ctrl+a or Tab opens the add form.
- Ctrl+f toggles the folder/category view.
- e (in detail) opens the edit form.
- d (in detail) opens the delete confirmation; d (in folder view)
  opens the delete-folder confirmation.
- Esc goes back (or quits from the list when the query is empty).
- The search query persists across screens within a run.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from .models import Bookmark
from .search import filter_bookmarks
from .storage import BookmarkStore

STAGE_LIST = "list"
STAGE_DETAIL = "detail"
STAGE_EDIT = "edit"
STAGE_CONFIRM = "confirm"
STAGE_FOLDER = "folder"
STAGE_FOLDER_CONFIRM = "folder_confirm"

EDIT_FIELDS = ["url", "title", "category"]


def folder_tree(bookmarks: list[Bookmark], root: str = "") -> list[str]:
    """Distinct immediate child folders under `root`, sorted.

    For root "", returns the top-level categories ("dev", "food").
    For root "food", returns full paths of the next level
    ("food/links", "food/recipes") — the folder view descends one
    level at a time.
    """
    prefix = root.strip("/")
    depth = prefix.count("/") + 1 if prefix else 1
    children: set[str] = set()
    for bm in bookmarks:
        cat = bm.category.strip("/")
        if not cat:
            continue
        if prefix:
            if cat != prefix and not cat.startswith(prefix + "/"):
                continue
            rest = cat[len(prefix):].lstrip("/")
        else:
            rest = cat
        if not rest:
            continue
        parts = rest.split("/")
        child = "/".join(parts[:depth])
        children.add(f"{prefix}/{child}" if prefix else child)
    return sorted(children)


def category_count(bookmarks: list[Bookmark], category: str, store: BookmarkStore) -> int:
    """Number of bookmarks in `category` or any subcategory of it."""
    return sum(1 for bm in bookmarks if store.in_category(bm, category))


@dataclass
class ListScreen:
    stage: str = STAGE_LIST
    bookmarks: list[Bookmark] = field(default_factory=list)
    query: str = ""
    selected: int = 0
    offset: int = 0
    message: str = ""
    folder_mode: bool = False
    folder_path: str = ""

    @property
    def visible(self) -> list[Bookmark]:
        if self.folder_mode:
            return []
        if not self.query.strip():
            return []
        return filter_bookmarks(self.bookmarks, self.query)

    @property
    def folders(self) -> list[str]:
        """Immediate child folders under folder_path (folder mode only)."""
        if not self.folder_mode:
            return []
        return folder_tree(self.bookmarks, self.folder_path)

    @property
    def selected_bookmark(self) -> Bookmark | None:
        visible = self.visible
        if 0 <= self.selected < len(visible):
            return visible[self.selected]
        return None

    @property
    def selected_folder(self) -> str | None:
        folders = self.folders
        if 0 <= self.selected < len(folders):
            return folders[self.selected]
        return None


@dataclass
class DetailScreen:
    stage: str = STAGE_DETAIL
    bookmark: Bookmark | None = None
    list_query: str = ""
    list_selected: int = 0
    message: str = ""


@dataclass
class EditScreen:
    stage: str = STAGE_EDIT
    editing_id: int | None = None
    field_idx: int = 0
    values: dict[str, str] = field(default_factory=dict)
    cursor: int = 0
    list_query: str = ""
    list_selected: int = 0
    message: str = ""

    @property
    def current_field(self) -> str:
        return EDIT_FIELDS[self.field_idx]

    @property
    def current_value(self) -> str:
        return self.values.get(self.current_field, "")

    @property
    def is_new(self) -> bool:
        return self.editing_id is None


@dataclass
class ConfirmScreen:
    stage: str = STAGE_CONFIRM
    bookmark: Bookmark | None = None
    selected: int = 0
    list_query: str = ""
    list_selected: int = 0
    message: str = ""


@dataclass
class FolderConfirmScreen:
    stage: str = STAGE_FOLDER_CONFIRM
    folder: str = ""
    count: int = 0
    selected: int = 0
    folder_path: str = ""
    message: str = ""


Screen = ListScreen | DetailScreen | EditScreen | ConfirmScreen | FolderConfirmScreen


class OpenRequested(Exception):
    """Raised when the user picks a bookmark to open in the browser."""

    def __init__(self, bookmark: Bookmark) -> None:
        super().__init__(bookmark.url)
        self.bookmark = bookmark


class QuitRequested(Exception):
    """Raised by App.handle_key when the user asks to quit."""


class App:
    def __init__(self, store: BookmarkStore, open_url=None) -> None:
        self.store = store
        self._open_url = open_url or _default_open_url
        self.screen: Screen = ListScreen()

    # ------------------------------------------------------------ helpers

    def _list_screen(
        self,
        query: str = "",
        selected: int = 0,
        message: str = "",
        folder_mode: bool = False,
        folder_path: str = "",
    ) -> ListScreen:
        screen = ListScreen(
            bookmarks=self.store.all,
            query=query,
            selected=selected,
            message=message,
            folder_mode=folder_mode,
            folder_path=folder_path,
        )
        self.screen = screen
        return screen

    def _detail_screen(self, bm: Bookmark, list_query: str = "", list_selected: int = 0) -> DetailScreen:
        screen = DetailScreen(bookmark=bm, list_query=list_query, list_selected=list_selected)
        self.screen = screen
        return screen

    def _start_edit(self, bm: Bookmark | None, list_query: str = "", list_selected: int = 0) -> EditScreen:
        if bm is None:
            values = {"url": "", "title": "", "category": ""}
            screen = EditScreen(editing_id=None, values=values, cursor=0,
                                list_query=list_query, list_selected=list_selected)
        else:
            values = {"url": bm.url, "title": bm.title, "category": bm.category}
            screen = EditScreen(editing_id=bm.id, values=values, cursor=len(values["url"]),
                                list_query=list_query, list_selected=list_selected)
        self.screen = screen
        return screen

    def _save_edit(self) -> Screen:
        screen = self.screen
        assert isinstance(screen, EditScreen)
        url = screen.values["url"].strip()
        title = screen.values["title"].strip()
        category = screen.values["category"].strip()
        if not url:
            screen.message = "URL is required"
            return screen
        if screen.is_new:
            bm = self.store.add(url, title, category)
            return self._list_screen(query=screen.list_query, selected=screen.list_selected,
                                     message=f"Added: {title or url}")
        else:
            self.store.update(screen.editing_id, url, title, category)
            return self._list_screen(query=screen.list_query, selected=screen.list_selected,
                                     message=f"Updated: {title or url}")

    def _confirm_delete(self, bm: Bookmark, list_query: str = "", list_selected: int = 0) -> ConfirmScreen:
        screen = ConfirmScreen(bookmark=bm, list_query=list_query, list_selected=list_selected)
        self.screen = screen
        return screen

    def _do_delete(self) -> Screen:
        screen = self.screen
        assert isinstance(screen, ConfirmScreen)
        if screen.bookmark is None:
            return self._list_screen(query=screen.list_query, selected=screen.list_selected)
        bm = screen.bookmark
        self.store.delete(bm.id)
        return self._list_screen(query=screen.list_query, selected=screen.list_selected,
                                 message=f"Deleted: {bm.title or bm.url}")

    def _confirm_delete_folder(self, folder: str, parent_path: str = "") -> FolderConfirmScreen:
        count = category_count(self.store.all, folder, self.store)
        screen = FolderConfirmScreen(folder=folder, count=count, folder_path=parent_path)
        self.screen = screen
        return screen

    def _do_delete_folder(self) -> Screen:
        screen = self.screen
        assert isinstance(screen, FolderConfirmScreen)
        deleted = self.store.delete_category(screen.folder)
        return self._list_screen(folder_mode=True, folder_path=screen.folder_path,
                                 message=f"Deleted folder: {screen.folder} ({deleted} bookmarks)")

    # ------------------------------------------------------------ launch

    def start(self) -> Screen:
        return self._list_screen()

    # ------------------------------------------------------------ keys

    def handle_key(self, key: str) -> Screen:
        if key == "ctrl_c":
            raise QuitRequested
        screen = self.screen
        if isinstance(screen, ListScreen):
            return self._handle_list_key(key)
        if isinstance(screen, DetailScreen):
            return self._handle_detail_key(key)
        if isinstance(screen, EditScreen):
            return self._handle_edit_key(key)
        if isinstance(screen, ConfirmScreen):
            return self._handle_confirm_key(key)
        if isinstance(screen, FolderConfirmScreen):
            return self._handle_folder_confirm_key(key)
        return screen

    def _clamp(self, screen: Screen, height: int) -> None:
        if isinstance(screen, ListScreen):
            items = screen.folders if screen.folder_mode else screen.visible
            if screen.selected >= len(items):
                screen.selected = max(0, len(items) - 1)
            if screen.selected < 0:
                screen.selected = 0
            if height > 0:
                if screen.selected < screen.offset:
                    screen.offset = screen.selected
                elif screen.selected >= screen.offset + height:
                    screen.offset = screen.selected - height + 1
        elif isinstance(screen, EditScreen):
            if screen.field_idx >= len(EDIT_FIELDS):
                screen.field_idx = len(EDIT_FIELDS) - 1
            if screen.field_idx < 0:
                screen.field_idx = 0
            value = screen.current_value
            if screen.cursor > len(value):
                screen.cursor = len(value)
            if screen.cursor < 0:
                screen.cursor = 0

    def _handle_list_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, ListScreen)
        if screen.folder_mode:
            return self._handle_folder_key(key)
        visible = screen.visible
        if key == "enter":
            bm = screen.selected_bookmark
            if bm is None:
                return screen
            raise OpenRequested(bm)
        if key == "ctrl_o":
            bm = screen.selected_bookmark
            if bm is None:
                return screen
            return self._detail_screen(bm, list_query=screen.query, list_selected=screen.selected)
        if key == "esc":
            if screen.query:
                screen.query = ""
                screen.selected = 0
                screen.offset = 0
                return screen
            raise QuitRequested
        if key == "ctrl_f":
            return self._list_screen(folder_mode=True, selected=0)
        if key == "up":
            screen.selected = max(0, screen.selected - 1)
            return screen
        if key == "down":
            screen.selected = min(max(0, len(visible) - 1), screen.selected + 1)
            return screen
        if key == "pageup":
            screen.selected = max(0, screen.selected - 10)
            return screen
        if key == "pagedown":
            screen.selected = min(max(0, len(visible) - 1), screen.selected + 10)
            return screen
        if key == "home":
            screen.selected = 0
            return screen
        if key == "end":
            screen.selected = max(0, len(visible) - 1)
            return screen
        if key == "backspace":
            if screen.query:
                screen.query = screen.query[:-1]
                screen.selected = 0
                screen.offset = 0
            return screen
        if key == "ctrl_a" or key == "tab":
            return self._start_edit(None, list_query=screen.query, list_selected=screen.selected)
        if len(key) == 1 and key.isprintable():
            screen.query += key
            screen.selected = 0
            screen.offset = 0
            return screen
        return screen

    def _handle_folder_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, ListScreen)
        folders = screen.folders
        if key == "enter":
            folder = screen.selected_folder
            if folder is None:
                return screen
            return self._list_screen(folder_mode=True, folder_path=folder, selected=0)
        if key == "esc":
            if screen.folder_path:
                parent = screen.folder_path.rsplit("/", 1)[0] if "/" in screen.folder_path else ""
                return self._list_screen(folder_mode=True, folder_path=parent, selected=0)
            return self._list_screen(query=screen.query, selected=0)
        if key == "ctrl_f":
            return self._list_screen(query=screen.query, selected=0)
        if key == "d":
            folder = screen.selected_folder
            if folder is None:
                return screen
            return self._confirm_delete_folder(folder, parent_path=screen.folder_path)
        if key == "ctrl_a" or key == "tab":
            return self._start_edit(None, list_query=screen.query, list_selected=screen.selected)
        if key == "up":
            screen.selected = max(0, screen.selected - 1)
            return screen
        if key == "down":
            screen.selected = min(max(0, len(folders) - 1), screen.selected + 1)
            return screen
        if key == "pageup":
            screen.selected = max(0, screen.selected - 10)
            return screen
        if key == "pagedown":
            screen.selected = min(max(0, len(folders) - 1), screen.selected + 10)
            return screen
        if key == "home":
            screen.selected = 0
            return screen
        if key == "end":
            screen.selected = max(0, len(folders) - 1)
            return screen
        return screen

    def _handle_folder_confirm_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, FolderConfirmScreen)
        if key in ("y", "enter"):
            return self._do_delete_folder()
        if key in ("n", "esc"):
            return self._list_screen(folder_mode=True, folder_path=screen.folder_path)
        if key == "left":
            screen.selected = 0
            return screen
        if key == "right":
            screen.selected = 1
            return screen
        return screen

    def _handle_detail_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, DetailScreen)
        if key == "esc":
            return self._list_screen(query=screen.list_query, selected=screen.list_selected)
        if key == "enter":
            if screen.bookmark is not None:
                raise OpenRequested(screen.bookmark)
            return screen
        if key == "e":
            if screen.bookmark is not None:
                return self._start_edit(screen.bookmark,
                                        list_query=screen.list_query,
                                        list_selected=screen.list_selected)
            return screen
        if key == "d":
            if screen.bookmark is not None:
                return self._confirm_delete(screen.bookmark,
                                            list_query=screen.list_query,
                                            list_selected=screen.list_selected)
            return screen
        if key == "ctrl_a":
            return self._start_edit(None, list_query=screen.list_query, list_selected=screen.list_selected)
        return screen

    def _handle_edit_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, EditScreen)
        if key == "esc":
            return self._list_screen(query=screen.list_query, selected=screen.list_selected)
        if key == "up":
            if screen.field_idx > 0:
                screen.field_idx -= 1
                screen.cursor = len(screen.current_value)
            return screen
        if key in ("down", "tab", "enter"):
            if screen.field_idx < len(EDIT_FIELDS) - 1:
                screen.field_idx += 1
                screen.cursor = len(screen.current_value)
            else:
                return self._save_edit()
            return screen
        if key == "backspace":
            value = screen.current_value
            if screen.cursor > 0:
                new_value = value[: screen.cursor - 1] + value[screen.cursor:]
                screen.values[screen.current_field] = new_value
                screen.cursor -= 1
            return screen
        if key == "left":
            screen.cursor = max(0, screen.cursor - 1)
            return screen
        if key == "right":
            screen.cursor = min(len(screen.current_value), screen.cursor + 1)
            return screen
        if key == "home":
            screen.cursor = 0
            return screen
        if key == "end":
            screen.cursor = len(screen.current_value)
            return screen
        if key == "ctrl_s":
            return self._save_edit()
        if len(key) == 1 and key.isprintable():
            value = screen.current_value
            screen.values[screen.current_field] = value[:screen.cursor] + key + value[screen.cursor:]
            screen.cursor += 1
            return screen
        return screen

    def _handle_confirm_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, ConfirmScreen)
        if key in ("y", "enter"):
            return self._do_delete()
        if key in ("n", "esc"):
            return self._list_screen(query=screen.list_query, selected=screen.list_selected)
        if key == "left":
            screen.selected = 0
            return screen
        if key == "right":
            screen.selected = 1
            return screen
        return screen


def _is_termux() -> bool:
    """Detect the Termux environment (Android terminal emulator)."""
    import os

    prefix = os.environ.get("PREFIX", "")
    return "com.termux" in prefix or "TERMUX_VERSION" in os.environ


def _default_open_url(url: str) -> None:
    """Open a URL in the default browser.

    The opener is started in a new session with no controlling
    terminal. This runs after the curses UI has exited; when bookmark-tui
    itself is the session leader (e.g. `ghostty -e bookmark-tui`), the
    kernel would otherwise deliver SIGHUP to the foreground process group
    on exit and kill the opener before the browser starts.
    """
    import sys
    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if _is_termux():
        subprocess.Popen(["termux-open-url", url], start_new_session=True, **kwargs)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url], start_new_session=True, **kwargs)
    elif sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", "start", url], **kwargs)
    else:
        subprocess.Popen(["xdg-open", url], start_new_session=True, **kwargs)

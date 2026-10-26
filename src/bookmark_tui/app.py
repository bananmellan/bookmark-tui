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
STAGE_PROMPT = "prompt"

EDIT_FIELDS = ["url", "title", "category"]

PROMPT_RENAME = "rename"
PROMPT_MOVE = "move"


@dataclass(frozen=True)
class FolderRow:
    """One row in the folder view: either a child folder or a bookmark."""

    kind: str  # "folder" or "bookmark"
    name: str  # folder path, or bookmark title/url for display
    folder: str = ""  # set when kind == "folder"
    bookmark: Bookmark | None = None  # set when kind == "bookmark"


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


def folder_rows(bookmarks: list[Bookmark], root: str = "") -> list[FolderRow]:
    """Rows for the folder view at `root`: immediate child folders
    first (sorted), then bookmarks directly in `root` (sorted by title).
    At the root, bookmarks with an empty category are included."""
    prefix = root.strip("/")
    folders = folder_tree(bookmarks, prefix)
    rows = [
        FolderRow(kind="folder", name=f.rsplit("/", 1)[-1] + "/", folder=f)
        for f in folders
    ]
    direct: list[Bookmark] = []
    for bm in bookmarks:
        cat = bm.category.strip("/")
        if prefix:
            if cat == prefix:
                direct.append(bm)
        elif not cat:
            direct.append(bm)
    direct.sort(key=lambda b: (b.title.lower(), b.url.lower()))
    rows.extend(
        FolderRow(kind="bookmark", name=bm.title or bm.url, bookmark=bm) for bm in direct
    )
    return rows


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
    marks: set[int] = field(default_factory=set)  # marked bookmark ids
    # Where to return after detail/edit/confirm when opened from folder view
    from_folder: bool = False
    from_folder_path: str = ""
    from_folder_selected: int = 0

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
    def rows(self) -> list[FolderRow]:
        """Folder-view rows at folder_path: child folders, then bookmarks
        directly in this folder (folder mode only)."""
        if not self.folder_mode:
            return []
        return folder_rows(self.bookmarks, self.folder_path)

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

    @property
    def selected_row(self) -> FolderRow | None:
        rows = self.rows
        if 0 <= self.selected < len(rows):
            return rows[self.selected]
        return None

    @property
    def marked_bookmarks(self) -> list[Bookmark]:
        return [bm for bm in self.bookmarks if bm.id in self.marks]


@dataclass
class DetailScreen:
    stage: str = STAGE_DETAIL
    bookmark: Bookmark | None = None
    list_query: str = ""
    list_selected: int = 0
    message: str = ""
    from_folder: bool = False
    from_folder_path: str = ""
    from_folder_selected: int = 0


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
    from_folder: bool = False
    from_folder_path: str = ""
    from_folder_selected: int = 0

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
    from_folder: bool = False
    from_folder_path: str = ""
    from_folder_selected: int = 0


@dataclass
class FolderConfirmScreen:
    stage: str = STAGE_FOLDER_CONFIRM
    folder: str = ""
    count: int = 0
    selected: int = 0
    folder_path: str = ""
    message: str = ""


@dataclass
class PromptScreen:
    """Free-text prompt: rename a folder, or pick a target folder for
    moving marked bookmarks."""

    stage: str = STAGE_PROMPT
    kind: str = ""  # PROMPT_RENAME or PROMPT_MOVE
    text: str = ""
    cursor: int = 0
    folder: str = ""  # folder being renamed (PROMPT_RENAME)
    folder_path: str = ""  # current folder (return context)
    marks: set[int] = field(default_factory=set)  # bookmarks to move (PROMPT_MOVE)
    selected: int = 0
    message: str = ""


Screen = ListScreen | DetailScreen | EditScreen | ConfirmScreen | FolderConfirmScreen | PromptScreen


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
        marks: set[int] | None = None,
    ) -> ListScreen:
        screen = ListScreen(
            bookmarks=self.store.all,
            query=query,
            selected=selected,
            message=message,
            folder_mode=folder_mode,
            folder_path=folder_path,
            marks=marks if marks is not None else set(),
        )
        self.screen = screen
        return screen

    def _folder_screen(
        self,
        folder_path: str = "",
        selected: int = 0,
        message: str = "",
        marks: set[int] | None = None,
    ) -> ListScreen:
        return self._list_screen(
            folder_mode=True,
            folder_path=folder_path,
            selected=selected,
            message=message,
            marks=marks,
        )

    def _detail_screen(
        self,
        bm: Bookmark,
        list_query: str = "",
        list_selected: int = 0,
        from_folder: bool = False,
        from_folder_path: str = "",
        from_folder_selected: int = 0,
    ) -> DetailScreen:
        screen = DetailScreen(
            bookmark=bm,
            list_query=list_query,
            list_selected=list_selected,
            from_folder=from_folder,
            from_folder_path=from_folder_path,
            from_folder_selected=from_folder_selected,
        )
        self.screen = screen
        return screen

    def _start_edit(
        self,
        bm: Bookmark | None,
        list_query: str = "",
        list_selected: int = 0,
        from_folder: bool = False,
        from_folder_path: str = "",
        from_folder_selected: int = 0,
    ) -> EditScreen:
        if bm is None:
            values = {"url": "", "title": "", "category": ""}
            screen = EditScreen(editing_id=None, values=values, cursor=0,
                                list_query=list_query, list_selected=list_selected,
                                from_folder=from_folder, from_folder_path=from_folder_path,
                                from_folder_selected=from_folder_selected)
        else:
            values = {"url": bm.url, "title": bm.title, "category": bm.category}
            screen = EditScreen(editing_id=bm.id, values=values, cursor=len(values["url"]),
                                list_query=list_query, list_selected=list_selected,
                                from_folder=from_folder, from_folder_path=from_folder_path,
                                from_folder_selected=from_folder_selected)
        self.screen = screen
        return screen

    def _return_screen(
        self,
        query: str = "",
        selected: int = 0,
        message: str = "",
        from_folder: bool = False,
        from_folder_path: str = "",
        from_folder_selected: int = 0,
        marks: set[int] | None = None,
    ) -> ListScreen:
        """Return to wherever the user came from: the search list, or the
        folder view if the action started there."""
        if from_folder:
            return self._folder_screen(
                folder_path=from_folder_path,
                selected=from_folder_selected,
                message=message,
                marks=marks,
            )
        return self._list_screen(query=query, selected=selected, message=message)

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
            return self._return_screen(
                query=screen.list_query,
                selected=screen.list_selected,
                message=f"Added: {title or url}",
                from_folder=screen.from_folder,
                from_folder_path=screen.from_folder_path,
                from_folder_selected=screen.from_folder_selected,
            )
        else:
            self.store.update(screen.editing_id, url, title, category)
            return self._return_screen(
                query=screen.list_query,
                selected=screen.list_selected,
                message=f"Updated: {title or url}",
                from_folder=screen.from_folder,
                from_folder_path=screen.from_folder_path,
                from_folder_selected=screen.from_folder_selected,
            )

    def _confirm_delete(
        self,
        bm: Bookmark,
        list_query: str = "",
        list_selected: int = 0,
        from_folder: bool = False,
        from_folder_path: str = "",
        from_folder_selected: int = 0,
    ) -> ConfirmScreen:
        screen = ConfirmScreen(
            bookmark=bm,
            list_query=list_query,
            list_selected=list_selected,
            from_folder=from_folder,
            from_folder_path=from_folder_path,
            from_folder_selected=from_folder_selected,
        )
        self.screen = screen
        return screen

    def _do_delete(self) -> Screen:
        screen = self.screen
        assert isinstance(screen, ConfirmScreen)
        if screen.bookmark is None:
            return self._return_screen(
                query=screen.list_query,
                selected=screen.list_selected,
                from_folder=screen.from_folder,
                from_folder_path=screen.from_folder_path,
                from_folder_selected=screen.from_folder_selected,
            )
        bm = screen.bookmark
        self.store.delete(bm.id)
        return self._return_screen(
            query=screen.list_query,
            selected=screen.list_selected,
            message=f"Deleted: {bm.title or bm.url}",
            from_folder=screen.from_folder,
            from_folder_path=screen.from_folder_path,
            from_folder_selected=screen.from_folder_selected,
        )

    def _confirm_delete_folder(self, folder: str, parent_path: str = "") -> FolderConfirmScreen:
        count = category_count(self.store.all, folder, self.store)
        screen = FolderConfirmScreen(folder=folder, count=count, folder_path=parent_path)
        self.screen = screen
        return screen

    def _do_delete_folder(self) -> Screen:
        screen = self.screen
        assert isinstance(screen, FolderConfirmScreen)
        deleted = self.store.delete_category(screen.folder)
        return self._folder_screen(
            folder_path=screen.folder_path,
            message=f"Deleted folder: {screen.folder} ({deleted} bookmarks)",
        )

    def _finish_rename(self, old: str, new: str, folder_path: str) -> Screen:
        new = new.strip("/")
        if not new:
            return self._folder_screen(
                folder_path=folder_path, message="Rename cancelled: empty name"
            )
        moved = self.store.rename_category(old, new)
        if moved == 0:
            return self._folder_screen(
                folder_path=folder_path,
                message=f"Could not rename {old}: no such folder or {new} already exists",
            )
        return self._folder_screen(
            folder_path=folder_path,
            message=f"Renamed {old} -> {new} ({moved} bookmarks)",
        )

    def _finish_move(self, ids: list[int], target: str, folder_path: str, marks: set[int]) -> Screen:
        target = target.strip("/")
        moved = self.store.move_to_category(ids, target)
        marks = marks - set(ids)
        return self._folder_screen(
            folder_path=folder_path,
            message=f"Moved {moved} bookmark(s) to {target or '(uncategorized)'}",
            marks=marks,
        )

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
        if isinstance(screen, PromptScreen):
            return self._handle_prompt_key(key)
        return screen

    def _clamp(self, screen: Screen, height: int) -> None:
        if isinstance(screen, ListScreen):
            items = screen.rows if screen.folder_mode else screen.visible
            if screen.selected >= len(items):
                screen.selected = max(0, len(items) - 1)
            if screen.selected < 0:
                screen.selected = 0
            if height > 0:
                if screen.selected < screen.offset:
                    screen.offset = screen.selected
                elif screen.selected >= screen.offset + height:
                    screen.offset = screen.selected - height + 1
        elif isinstance(screen, PromptScreen):
            if screen.cursor > len(screen.text):
                screen.cursor = len(screen.text)
            if screen.cursor < 0:
                screen.cursor = 0
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
        rows = screen.rows
        row = screen.selected_row

        if key == "enter":
            if row is None:
                return screen
            if row.kind == "folder":
                return self._folder_screen(folder_path=row.folder, selected=0)
            if row.bookmark is not None:
                raise OpenRequested(row.bookmark)
            return screen
        if key == "ctrl_o":
            if row is not None and row.kind == "bookmark" and row.bookmark is not None:
                return self._detail_screen(
                    row.bookmark,
                    from_folder=True,
                    from_folder_path=screen.folder_path,
                    from_folder_selected=screen.selected,
                )
            return screen
        if key == "esc":
            if screen.folder_path:
                parent = screen.folder_path.rsplit("/", 1)[0] if "/" in screen.folder_path else ""
                return self._folder_screen(folder_path=parent, selected=0, marks=screen.marks)
            return self._list_screen(query=screen.query, selected=0)
        if key == "ctrl_f":
            return self._list_screen(query=screen.query, selected=0)
        if key == "d":
            if row is None:
                return screen
            if row.kind == "folder":
                return self._confirm_delete_folder(row.folder, parent_path=screen.folder_path)
            if row.bookmark is not None:
                return self._confirm_delete(
                    row.bookmark,
                    from_folder=True,
                    from_folder_path=screen.folder_path,
                    from_folder_selected=screen.selected,
                )
            return screen
        if key == "r":
            if row is not None and row.kind == "folder":
                return self._start_prompt(PROMPT_RENAME, folder=row.folder,
                                          folder_path=screen.folder_path)
            return screen
        if key == " ":
            # toggle mark on a bookmark row
            if row is not None and row.kind == "bookmark" and row.bookmark is not None:
                if row.bookmark.id in screen.marks:
                    screen.marks.discard(row.bookmark.id)
                else:
                    screen.marks.add(row.bookmark.id)
            return screen
        if key == "A":
            # toggle: mark all bookmarks in this folder, or clear all marks
            bm_ids = {r.bookmark.id for r in rows if r.kind == "bookmark" and r.bookmark}
            if bm_ids and bm_ids <= screen.marks:
                screen.marks -= bm_ids
            else:
                screen.marks |= bm_ids
            return screen
        if key == "M":
            if not screen.marks:
                screen.message = "No bookmarks marked (space to mark)"
                return screen
            return self._start_prompt(PROMPT_MOVE, folder_path=screen.folder_path)
        if key == "c":
            # duplicate: open the add form pre-filled with the bookmark's data
            if row is not None and row.kind == "bookmark" and row.bookmark is not None:
                bm = row.bookmark
                values = {"url": bm.url, "title": bm.title, "category": bm.category}
                screen = EditScreen(
                    editing_id=None,  # duplicate => new bookmark
                    values=values,
                    cursor=len(values["url"]),
                    from_folder=True,
                    from_folder_path=screen.folder_path,
                    from_folder_selected=screen.selected,
                )
                self.screen = screen
                return screen
            return screen
        if key == "ctrl_a" or key == "tab":
            return self._start_edit(
                None,
                from_folder=True,
                from_folder_path=screen.folder_path,
                from_folder_selected=screen.selected,
            )
        if key == "up":
            screen.selected = max(0, screen.selected - 1)
            return screen
        if key == "down":
            screen.selected = min(max(0, len(rows) - 1), screen.selected + 1)
            return screen
        if key == "pageup":
            screen.selected = max(0, screen.selected - 10)
            return screen
        if key == "pagedown":
            screen.selected = min(max(0, len(rows) - 1), screen.selected + 10)
            return screen
        if key == "home":
            screen.selected = 0
            return screen
        if key == "end":
            screen.selected = max(0, len(rows) - 1)
            return screen
        return screen

    def _handle_prompt_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, PromptScreen)
        if key == "esc":
            return self._folder_screen(folder_path=screen.folder_path)
        if key == "enter":
            if screen.kind == PROMPT_RENAME:
                return self._finish_rename(screen.folder, screen.text, screen.folder_path)
            if screen.kind == PROMPT_MOVE:
                ids = [bm.id for bm in self.store.all if bm.id in screen.marks]
                return self._finish_move(ids, screen.text, screen.folder_path, screen.marks)
            return self._folder_screen(folder_path=screen.folder_path)
        if key == "backspace":
            if screen.cursor > 0:
                screen.text = screen.text[: screen.cursor - 1] + screen.text[screen.cursor:]
                screen.cursor -= 1
            return screen
        if key == "left":
            screen.cursor = max(0, screen.cursor - 1)
            return screen
        if key == "right":
            screen.cursor = min(len(screen.text), screen.cursor + 1)
            return screen
        if key == "home":
            screen.cursor = 0
            return screen
        if key == "end":
            screen.cursor = len(screen.text)
            return screen
        if len(key) == 1 and key.isprintable():
            screen.text = screen.text[:screen.cursor] + key + screen.text[screen.cursor:]
            screen.cursor += 1
            return screen
        return screen

    def _start_prompt(self, kind: str, folder: str = "", folder_path: str = "") -> PromptScreen:
        marks: set[int] = set()
        if kind == PROMPT_MOVE:
            current = self.screen
            if isinstance(current, ListScreen):
                marks = set(current.marks)
        initial = folder.rsplit("/", 1)[-1] if folder else ""
        screen = PromptScreen(kind=kind, text=initial, cursor=len(initial),
                              folder=folder, folder_path=folder_path, marks=marks)
        self.screen = screen
        return screen

    def _handle_folder_confirm_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, FolderConfirmScreen)
        if key in ("y", "enter"):
            return self._do_delete_folder()
        if key in ("n", "esc"):
            return self._folder_screen(folder_path=screen.folder_path)
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
            return self._return_screen(
                query=screen.list_query,
                selected=screen.list_selected,
                from_folder=screen.from_folder,
                from_folder_path=screen.from_folder_path,
                from_folder_selected=screen.from_folder_selected,
            )
        if key == "enter":
            if screen.bookmark is not None:
                raise OpenRequested(screen.bookmark)
            return screen
        if key == "e":
            if screen.bookmark is not None:
                return self._start_edit(screen.bookmark,
                                        list_query=screen.list_query,
                                        list_selected=screen.list_selected,
                                        from_folder=screen.from_folder,
                                        from_folder_path=screen.from_folder_path,
                                        from_folder_selected=screen.from_folder_selected)
            return screen
        if key == "d":
            if screen.bookmark is not None:
                return self._confirm_delete(screen.bookmark,
                                            list_query=screen.list_query,
                                            list_selected=screen.list_selected,
                                            from_folder=screen.from_folder,
                                            from_folder_path=screen.from_folder_path,
                                            from_folder_selected=screen.from_folder_selected)
            return screen
        if key == "c":
            # duplicate: add form pre-filled with this bookmark's data
            if screen.bookmark is not None:
                bm = screen.bookmark
                values = {"url": bm.url, "title": bm.title, "category": bm.category}
                edit = EditScreen(
                    editing_id=None,
                    values=values,
                    cursor=len(values["url"]),
                    list_query=screen.list_query,
                    list_selected=screen.list_selected,
                    from_folder=screen.from_folder,
                    from_folder_path=screen.from_folder_path,
                    from_folder_selected=screen.from_folder_selected,
                )
                self.screen = edit
                return edit
            return screen
        if key == "ctrl_a":
            return self._start_edit(None, list_query=screen.list_query, list_selected=screen.list_selected)
        return screen

    def _handle_edit_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, EditScreen)
        if key == "esc":
            return self._return_screen(
                query=screen.list_query,
                selected=screen.list_selected,
                from_folder=screen.from_folder,
                from_folder_path=screen.from_folder_path,
                from_folder_selected=screen.from_folder_selected,
            )
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
            return self._return_screen(
                query=screen.list_query,
                selected=screen.list_selected,
                from_folder=screen.from_folder,
                from_folder_path=screen.from_folder_path,
                from_folder_selected=screen.from_folder_selected,
            )
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

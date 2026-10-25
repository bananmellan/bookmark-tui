"""UI-agnostic controller for the buku-tui application.

Owns the whole interaction state machine: the bookmark list (with live
filter and clipboard-driven host matching at launch), the detail view,
the edit/add form, and the delete confirmation. The controller never
touches curses: it exposes the current screen as a plain dataclass plus
a handle_key method that returns the next screen.

Pressing enter on a bookmark in the list opens its detail view. From
the detail view the user can copy the URL (enter, then quit), edit the
bookmark (e), delete it (d), or add a new one (ctrl-a). The edit form
supports full text editing within each field.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .bukucli import BukuCli, BukuCliError
from .cache import Cache, match_host, sort_refs
from .clipboard import Clipboard, ClipboardError, extract_host
from .config import Config
from .models import BookmarkRef
from .search import filter_bookmarks

STAGE_LIST = "list"
STAGE_DETAIL = "detail"
STAGE_EDIT = "edit"
STAGE_CONFIRM = "confirm"

EDIT_FIELDS = ["url", "title", "tags", "desc"]


@dataclass
class ListScreen:
    stage: str = STAGE_LIST
    refs: list[BookmarkRef] = field(default_factory=list)
    query: str = ""
    selected: int = 0
    offset: int = 0
    host_filter: str = ""
    message: str = ""
    matches: list[BookmarkRef] = field(default_factory=list)

    @property
    def visible(self) -> list[BookmarkRef]:
        if not self.query.strip():
            return []
        precise = bool(self.host_filter) and self.host_filter in self.query.lower()
        return filter_bookmarks(self.refs, self.query, host_query=precise)

    @property
    def selected_ref(self) -> BookmarkRef | None:
        visible = self.visible
        if 0 <= self.selected < len(visible):
            return visible[self.selected]
        return None


@dataclass
class DetailScreen:
    stage: str = STAGE_DETAIL
    ref: BookmarkRef | None = None
    message: str = ""


@dataclass
class EditScreen:
    stage: str = STAGE_EDIT
    editing_index: int | None = None
    field_idx: int = 0
    values: dict[str, str] = field(default_factory=dict)
    cursor: int = 0
    message: str = ""

    @property
    def current_field(self) -> str:
        return EDIT_FIELDS[self.field_idx]

    @property
    def current_value(self) -> str:
        return self.values.get(self.current_field, "")

    @property
    def is_new(self) -> bool:
        return self.editing_index is None


@dataclass
class ConfirmScreen:
    stage: str = STAGE_CONFIRM
    action: str = ""
    ref: BookmarkRef | None = None
    selected: int = 0
    message: str = ""


Screen = ListScreen | DetailScreen | EditScreen | ConfirmScreen


class OpenRequested(Exception):
    """Raised when the user picks a bookmark to open in the browser."""

    def __init__(self, ref: BookmarkRef) -> None:
        super().__init__(ref.url)
        self.ref = ref


class QuitRequested(Exception):
    """Raised by App.handle_key when the user asks to quit."""


class App:
    def __init__(
        self,
        config: Config,
        cache: Cache,
        client: BukuCli,
        clipboard: Clipboard,
        now: Callable[[], float] = time.time,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.cache = cache
        self.client = client
        self.clipboard = clipboard
        self._now = now
        self._log = log or (lambda msg: None)
        self.screen: Screen = ListScreen()

    # ------------------------------------------------------------ helpers

    def _refresh_list(
        self,
        host_filter: str = "",
        matches: list[BookmarkRef] | None = None,
        message: str = "",
        keep_query: bool = False,
    ) -> ListScreen:
        refs = self.cache.load()
        if not refs:
            try:
                refs, _raw = self.cache.rebuild()
            except BukuCliError:
                refs = []
        if matches is not None:
            matched_ids = {ref.index for ref in matches}
            rest = [ref for ref in sort_refs(refs) if ref.index not in matched_ids]
            ordered = matches + rest
        else:
            ordered = sort_refs(refs)
        query = ""
        if keep_query and isinstance(self.screen, ListScreen):
            query = self.screen.query
        self._log(f"list: {len(refs)} cached bookmarks, query={query!r}")
        screen = ListScreen(
            refs=ordered,
            query=query if keep_query else host_filter,
            host_filter=host_filter if not keep_query else "",
            message=message,
        )
        self.screen = screen
        return screen

    def _rebuild_and_refresh(self, message: str = "") -> ListScreen:
        try:
            refs, raw_count = self.cache.rebuild()
            self._log(f"rebuild: {len(refs)} bookmarks from {raw_count} raw entries")
        except BukuCliError as exc:
            self._log(f"rebuild failed: {exc}")
            return self._refresh_list(message=f"Refresh failed: {exc}")
        screen = ListScreen(refs=sort_refs(refs), message=message)
        self.screen = screen
        return screen

    def _open_detail(self, ref: BookmarkRef) -> DetailScreen:
        screen = DetailScreen(ref=ref)
        self.screen = screen
        return screen

    def _start_edit(self, ref: BookmarkRef | None) -> EditScreen:
        if ref is None:
            values = {"url": "", "title": "", "tags": "", "desc": ""}
            screen = EditScreen(editing_index=None, values=values, cursor=0)
        else:
            tags_str = ", ".join(ref.tags)
            values = {
                "url": ref.url,
                "title": ref.title,
                "tags": tags_str,
                "desc": ref.description,
            }
            screen = EditScreen(editing_index=ref.index, values=values, cursor=len(values["url"]))
        self.screen = screen
        return screen

    def _save_edit(self) -> Screen:
        screen = self.screen
        assert isinstance(screen, EditScreen)
        url = screen.values["url"].strip()
        title = screen.values["title"].strip()
        tags_str = screen.values["tags"].strip()
        desc = screen.values["desc"]
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        if not url:
            screen.message = "URL is required"
            return screen
        try:
            if screen.is_new:
                new_index = self.client.add(url, title, tags, desc)
                self._log(f"added bookmark #{new_index}: {title or url}")
                try:
                    self.cache.rebuild()
                except BukuCliError:
                    pass  # cache will refresh on next launch
                return self._refresh_list(message=f"Added: {title or url}")
            else:
                self.client.update(screen.editing_index, url, title, tags, desc)
                self._log(f"updated bookmark #{screen.editing_index}: {title or url}")
                try:
                    self.cache.rebuild()
                except BukuCliError:
                    pass
                return self._refresh_list(message=f"Updated: {title or url}")
        except BukuCliError as exc:
            screen.message = f"Error: {exc}"
            return screen

    def _confirm_delete(self, ref: BookmarkRef) -> ConfirmScreen:
        screen = ConfirmScreen(action="delete", ref=ref)
        self.screen = screen
        return screen

    def _do_delete(self) -> Screen:
        screen = self.screen
        assert isinstance(screen, ConfirmScreen)
        if screen.ref is None:
            return self._refresh_list()
        try:
            self.client.delete(screen.ref.index)
            self._log(f"deleted bookmark #{screen.ref.index}: {screen.ref.title}")
            try:
                self.cache.rebuild()
            except BukuCliError:
                pass
            return self._refresh_list(message=f"Deleted: {screen.ref.title or screen.ref.url}")
        except BukuCliError as exc:
            return self._refresh_list(message=f"Delete failed: {exc}")

    def _copy_url(self, ref: BookmarkRef) -> bool:
        try:
            self.clipboard.write(ref.url)
            return True
        except ClipboardError as exc:
            self._log(f"copy failed: {exc}")
            return False

    # ------------------------------------------------------------ launch

    def start(self) -> Screen:
        refs = self.cache.load()
        if not refs:
            try:
                refs, raw_count = self.cache.rebuild()
                self._log(f"initial rebuild: {len(refs)} bookmarks from {raw_count} raw entries")
            except BukuCliError as exc:
                self._log(f"initial rebuild failed: {exc}")
                refs = []

        clip = self.clipboard.read()[:2048]
        self._log(f"clipboard read: {clip[:200]!r}")
        host = extract_host(clip)
        self._log(f"extracted host: {host!r}")
        if host and refs:
            matches = match_host(refs, host)
            self._log(
                f"host {host!r} matched {len(matches)} bookmarks: "
                + ", ".join(f"{m.title} {m.url}" for m in matches[:10])
            )
            if matches:
                return self._refresh_list(host_filter=host, matches=matches)
            self._log("clipboard matching did not handle the launch")

        return self._refresh_list()

    # ------------------------------------------------------------ keys

    def handle_key(self, key: str) -> Screen:
        if key == "ctrl_c":
            raise QuitRequested
        if key == "ctrl_r":
            return self._rebuild_and_refresh()
        screen = self.screen
        if isinstance(screen, ListScreen):
            return self._handle_list_key(key)
        if isinstance(screen, DetailScreen):
            return self._handle_detail_key(key)
        if isinstance(screen, EditScreen):
            return self._handle_edit_key(key)
        if isinstance(screen, ConfirmScreen):
            return self._handle_confirm_key(key)
        return screen

    def _clamp(self, screen: Screen, height: int) -> None:
        if isinstance(screen, ListScreen):
            visible = screen.visible
            if screen.selected >= len(visible):
                screen.selected = max(0, len(visible) - 1)
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
        visible = screen.visible
        if key == "enter":
            ref = screen.selected_ref
            if ref is None:
                return screen
            return self._open_detail(ref)
        if key == "esc":
            if screen.query:
                screen.query = ""
                screen.selected = 0
                screen.offset = 0
                return screen
            raise QuitRequested
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
            return self._start_edit(None)
        if len(key) == 1 and key.isprintable():
            screen.query += key
            screen.selected = 0
            screen.offset = 0
            return screen
        return screen

    def _handle_detail_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, DetailScreen)
        if key == "esc":
            return self._refresh_list(keep_query=True)
        if key == "enter":
            if screen.ref is not None:
                if self._copy_url(screen.ref):
                    raise QuitRequested
                screen.message = "Copy failed"
            return screen
        if key == "e":
            if screen.ref is not None:
                return self._start_edit(screen.ref)
            return screen
        if key == "d":
            if screen.ref is not None:
                return self._confirm_delete(screen.ref)
            return screen
        if key == "ctrl_a":
            return self._start_edit(None)
        return screen

    def _handle_edit_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, EditScreen)
        if key == "esc":
            return self._refresh_list(keep_query=True)
        if key == "up":
            if screen.field_idx > 0:
                screen.field_idx -= 1
                screen.cursor = len(screen.current_value)
            return screen
        if key == "down":
            if screen.field_idx < len(EDIT_FIELDS) - 1:
                screen.field_idx += 1
                screen.cursor = len(screen.current_value)
            else:
                return self._save_edit()
            return screen
        if key == "tab":
            if screen.field_idx < len(EDIT_FIELDS) - 1:
                screen.field_idx += 1
                screen.cursor = len(screen.current_value)
            else:
                return self._save_edit()
            return screen
        if key == "enter":
            if screen.field_idx < len(EDIT_FIELDS) - 1:
                screen.field_idx += 1
                screen.cursor = len(screen.current_value)
            else:
                return self._save_edit()
            return screen
        if key == "backspace":
            value = screen.current_value
            if screen.cursor > 0:
                new_value = value[: screen.cursor - 1] + value[screen.cursor :]
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
            new_value = value[: screen.cursor] + key + value[screen.cursor :]
            screen.values[screen.current_field] = new_value
            screen.cursor += 1
            return screen
        return screen

    def _handle_confirm_key(self, key: str) -> Screen:
        screen = self.screen
        assert isinstance(screen, ConfirmScreen)
        if key == "esc":
            return self._refresh_list(keep_query=True)
        if key == "enter" or key == "y":
            return self._do_delete()
        if key == "n":
            return self._refresh_list(keep_query=True)
        if key == "left":
            screen.selected = 0
            return screen
        if key == "right":
            screen.selected = 1
            return screen
        return screen

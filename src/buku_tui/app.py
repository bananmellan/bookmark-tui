"""UI-agnostic controller for the buku-tui application.

Owns the whole interaction state machine: the bookmark list (with live
filter), clipboard-driven host matching at launch, and the
open-and-quit action. The controller never touches curses: it exposes
the current screen as a plain :class:`ListScreen` value plus a
:meth:`App.handle_key` method. The curses layer (tui.py) renders the
screen and feeds keystrokes; tests drive the controller directly.

Pressing enter on a bookmark raises :class:`OpenRequested` carrying the
selected ref; the entry point catches it, ends curses, and opens the
URL in the browser — like rofi, the program exits after one selection.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .bukucli import BukuCliError
from .cache import Cache, match_host, sort_refs
from .clipboard import Clipboard, extract_host
from .config import Config
from .bukucli import BukuCli
from .models import BookmarkRef
from .search import filter_bookmarks


@dataclass
class ListScreen:
    refs: list[BookmarkRef] = field(default_factory=list)
    query: str = ""
    selected: int = 0
    offset: int = 0
    host_filter: str = ""
    message: str = ""
    matches: list[BookmarkRef] = field(default_factory=list)

    @property
    def visible(self) -> list[BookmarkRef]:
        # An empty query shows nothing: the list only appears once the
        # user has typed at least one character (or a clipboard URL was
        # prefilled at launch).
        if not self.query.strip():
            return []
        # While the clipboard-prefilled host is still in the query,
        # filter precisely (substring only) so unrelated bookmarks never
        # appear; once the user edits the query past the host, normal
        # fuzzy matching resumes.
        precise = bool(self.host_filter) and self.host_filter in self.query.lower()
        return filter_bookmarks(self.refs, self.query, host_query=precise)

    @property
    def selected_ref(self) -> BookmarkRef | None:
        visible = self.visible
        if 0 <= self.selected < len(visible):
            return visible[self.selected]
        return None


class OpenRequested(Exception):
    """Raised by App.handle_key when the user picks a bookmark to open."""

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
        self.screen: ListScreen = ListScreen()

    # ------------------------------------------------------------ helpers

    def _refresh_list(
        self,
        host_filter: str = "",
        matches: list[BookmarkRef] | None = None,
        message: str = "",
    ) -> ListScreen:
        refs = self.cache.load()
        if matches is not None:
            matched_ids = {ref.index for ref in matches}
            rest = [ref for ref in sort_refs(refs) if ref.index not in matched_ids]
            ordered = matches + rest
        else:
            ordered = sort_refs(refs)
        self._log(f"list: {len(refs)} cached bookmarks, query={self.screen.query!r}")
        screen = ListScreen(
            refs=ordered,
            query=host_filter,
            host_filter=host_filter,
            message=message,
        )
        self.screen = screen
        return screen

    # ------------------------------------------------------------ launch

    def start(self) -> ListScreen:
        """Initial launch flow.

        1. Load the cache; rebuild synchronously when it is missing so
           the first run shows something.
        2. If the clipboard holds a URL, match bookmarks from the cache
           by host and list them best-first with the host prefilled as
           the query.
        3. Otherwise show the full list.
        """
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

    def handle_key(self, key: str) -> ListScreen:
        """Handle one key and return the (possibly new) screen.

        Keys are single characters (printable input) or one of the
        symbolic names: "up", "down", "pageup", "pagedown", "home",
        "end", "enter", "esc", "backspace", "tab", "ctrl_r", "ctrl_c".
        """
        if key == "ctrl_c":
            raise QuitRequested
        if key == "ctrl_r":
            return self._refresh_action()
        return self._handle_list_key(key)

    def _clamp(self, screen: ListScreen, height: int) -> None:
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

    def _handle_list_key(self, key: str) -> ListScreen:
        screen = self.screen
        visible = screen.visible
        if key == "enter":
            ref = screen.selected_ref
            if ref is None:
                return screen
            raise OpenRequested(ref)
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
        if len(key) == 1 and key.isprintable():
            screen.query += key
            screen.selected = 0
            screen.offset = 0
            return screen
        return screen

    def _refresh_action(self) -> ListScreen:
        try:
            refs, raw_count = self.cache.rebuild()
            self._log(f"refresh: {len(refs)} bookmarks from {raw_count} raw entries")
            return self._refresh_list()
        except BukuCliError as exc:
            self._log(f"refresh failed: {exc}")
            return self._refresh_list(message=f"Refresh failed: {exc}")

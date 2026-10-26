"""JSON file storage for bookmarks.

Bookmarks are stored as a flat JSON array in a single file. The store
keeps an in-memory list and writes atomically on every mutation, so a
crash never corrupts the file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import Bookmark

STORE_VERSION = 1


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class BookmarkStore:
    """In-memory bookmark list backed by a JSON file.

    If the path is a symbolic link (e.g. managed by GNU stow), it is
    resolved once at open: reads and writes go to the real file, and
    the atomic write replaces the real file instead of clobbering the
    link with a regular file.
    """

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self._bookmarks: list[Bookmark] = []
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        try:
            raw = self.path.read_bytes()
        except OSError:
            return
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(data, dict) or data.get("version") != STORE_VERSION:
            return
        items = data.get("items")
        if not isinstance(items, list):
            return
        seen: set[int] = set()
        for entry in items:
            try:
                bm = Bookmark.from_dict(entry)
            except (ValueError, KeyError):
                continue
            if bm.id in seen or not bm.url:
                continue
            seen.add(bm.id)
            self._bookmarks.append(bm)
        if self._bookmarks:
            self._next_id = max(bm.id for bm in self._bookmarks) + 1

    def _save(self) -> None:
        payload = {
            "version": STORE_VERSION,
            "items": [bm.to_dict() for bm in self._bookmarks],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.path, json.dumps(payload, indent=2).encode("utf-8"))

    @property
    def all(self) -> list[Bookmark]:
        """All bookmarks, sorted by title (case-insensitive), url as tiebreak."""
        return sorted(self._bookmarks, key=lambda b: (b.title.lower(), b.url.lower()))

    def get(self, bm_id: int) -> Bookmark | None:
        for bm in self._bookmarks:
            if bm.id == bm_id:
                return bm
        return None

    def add(self, url: str, title: str = "", category: str = "") -> Bookmark:
        bm = Bookmark(id=self._next_id, url=url, title=title, category=category)
        self._next_id += 1
        self._bookmarks.append(bm)
        self._save()
        return bm

    def update(self, bm_id: int, url: str, title: str = "", category: str = "") -> Bookmark | None:
        for i, bm in enumerate(self._bookmarks):
            if bm.id == bm_id:
                updated = Bookmark(id=bm_id, url=url, title=title, category=category)
                self._bookmarks[i] = updated
                self._save()
                return updated
        return None

    def delete(self, bm_id: int) -> bool:
        for i, bm in enumerate(self._bookmarks):
            if bm.id == bm_id:
                del self._bookmarks[i]
                self._save()
                return True
        return False

    def replace_all(self, bookmarks: list[Bookmark]) -> None:
        """Replace the entire bookmark list. Used by import."""
        self._bookmarks = list(bookmarks)
        self._next_id = (max((bm.id for bm in bookmarks), default=0)) + 1
        self._save()

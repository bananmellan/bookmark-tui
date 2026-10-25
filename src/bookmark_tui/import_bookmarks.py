"""Import bookmarks from buku, Firefox, and Chrome bookmark files.

Supported formats (auto-detected by extension and content):
- buku SQLite database (.db) — reads the bookmarks table directly
- buku JSON export (.json with "uri" keys)
- Firefox bookmarks backup (.json with "type": "text/x-moz-place" nodes)
- Chrome/Chromium/Edge bookmarks (.json with "type": "url" nodes)

Browser bookmark files are hierarchical: folders become categories.
A bookmark under Bookmarks Bar > Food > Recipes gets the category
"food/recipes" (folder names joined with "/", lowercased).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterator

from .models import Bookmark


class ImportError_(Exception):
    pass


def import_file(path: Path) -> list[Bookmark]:
    """Import bookmarks from a file. Returns a flat list of Bookmark
    objects with sequential IDs starting at 1."""
    suffix = path.suffix.lower()
    if suffix == ".db":
        raw = _import_buku_db(path)
    elif suffix == ".json":
        raw = _import_json(path)
    else:
        raise ImportError_(f"unsupported file type: {suffix or '(none)'}")

    bookmarks = []
    for i, (title, url, category) in enumerate(raw, start=1):
        if not url:
            continue
        bookmarks.append(Bookmark(id=i, url=url, title=title or "", category=category or ""))
    return bookmarks


def _import_buku_db(path: Path) -> Iterator[tuple[str, str, str]]:
    """Read a buku SQLite database. Yields (title, url, category) tuples.

    buku stores tags as a comma-delimited string wrapped in commas
    (e.g. ",tag1,tag2,"). We join tags with "/" as the category.
    """
    conn = sqlite3.connect(str(path))
    try:
        cur = conn.execute("SELECT URL, metadata, tags FROM bookmarks ORDER BY id")
        for url, title, tags_raw in cur:
            category = ""
            if tags_raw:
                tags = [t.strip() for t in tags_raw.strip(",").split(",") if t.strip()]
                category = "/".join(tags)
            yield (title or "", url or "", category)
    finally:
        conn.close()


def _import_json(path: Path) -> Iterator[tuple[str, str, str]]:
    """Import a JSON bookmark file. Auto-detects buku, Firefox, or Chrome."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list) and data and "uri" in data[0]:
        yield from _import_buku_json(data)
    elif isinstance(data, dict) and "roots" in data:
        yield from _import_browser_json(data)
    elif isinstance(data, list):
        yield from _import_plain_json_list(data)
    else:
        raise ImportError_("unrecognized JSON bookmark format")


def _import_buku_json(data: list) -> Iterator[tuple[str, str, str]]:
    """buku JSON export: list of {uri, title, tags, description}."""
    for entry in data:
        if not isinstance(entry, dict):
            continue
        url = entry.get("uri") or ""
        title = entry.get("title") or ""
        tags_raw = entry.get("tags") or ""
        category = ""
        if isinstance(tags_raw, str) and tags_raw:
            tags = [t.strip() for t in tags_raw.strip(",").split(",") if t.strip()]
            category = "/".join(tags)
        yield (title, url, category)


def _import_plain_json_list(data: list) -> Iterator[tuple[str, str, str]]:
    """Plain JSON list of {url, title, category} objects."""
    for entry in data:
        if not isinstance(entry, dict):
            continue
        yield (
            str(entry.get("title") or ""),
            str(entry.get("url") or ""),
            str(entry.get("category") or ""),
        )


def _import_browser_json(data: dict) -> Iterator[tuple[str, str, str]]:
    """Firefox/Chrome bookmark tree. Walks the folder hierarchy and
    yields (title, url, category) for every bookmark found."""
    roots = data.get("roots", {})
    for root_name, root in roots.items():
        if not isinstance(root, dict):
            continue
        if root.get("type") == "text/x-moz-place-container":
            yield from _walk_folder(root, [])
        elif root.get("type") == "folder" or "children" in root:
            yield from _walk_chrome_folder(root, [])


def _walk_folder(node: dict, path: list[str]) -> Iterator[tuple[str, str, str]]:
    """Walk a Firefox bookmark tree node."""
    node_type = node.get("type", "")
    if node_type == "text/x-moz-place":
        yield (node.get("title") or "", node.get("uri") or "", "/".join(path))
        return
    if node_type == "text/x-moz-place-container":
        title = node.get("title") or ""
        if title and title not in ("menu", "toolbar", "unfiled", "mobile"):
            path = path + [title.lower()]
        for child in node.get("children", []):
            if isinstance(child, dict):
                yield from _walk_folder(child, path)


def _walk_chrome_folder(node: dict, path: list[str]) -> Iterator[tuple[str, str, str]]:
    """Walk a Chrome bookmark tree node."""
    node_type = node.get("type", "")
    if node_type == "url":
        yield (node.get("name") or "", node.get("url") or "", "/".join(path))
        return
    name = node.get("name") or ""
    if name and name.lower() not in ("bookmarks bar", "bookmarks_bar", "other bookmarks", "other"):
        path = path + [name.lower()]
    for child in node.get("children", []):
        if isinstance(child, dict):
            yield from _walk_chrome_folder(child, path)

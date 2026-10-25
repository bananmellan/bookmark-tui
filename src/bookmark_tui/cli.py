"""Entry point for bookmark-tui.

Usage:
  bookmark-tui                  Launch the TUI
  bookmark-tui --import FILE    Import bookmarks from a file and launch
  bookmark-tui --import FILE --no-tui   Import only, don't launch TUI
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .app import App
from .import_bookmarks import import_file, ImportError_
from .storage import BookmarkStore


def default_store_path() -> Path:
    """Default bookmark store location."""
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return Path(xdg) / "bookmark-tui" / "bookmarks.json"


def build_app(store: BookmarkStore) -> App:
    return App(store)


def run_tui(store: BookmarkStore) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "bookmark-tui: interactive terminal required (run it from a terminal)",
            file=sys.stderr,
        )
        return 2
    from .tui import run

    app = build_app(store)
    try:
        bm = run(app)
    except KeyboardInterrupt:
        return 0
    if bm is None:
        return 0
    try:
        app._open_url(bm.url)
    except Exception as exc:
        print(f"bookmark-tui: could not open {bm.url!r}: {exc}", file=sys.stderr)
        return 1
    return 0


def run_import(path: Path, store: BookmarkStore, launch_tui: bool = True) -> int:
    try:
        bookmarks = import_file(path)
    except (ImportError_, OSError, ValueError) as exc:
        print(f"bookmark-tui: import failed: {exc}", file=sys.stderr)
        return 1
    if not bookmarks:
        print(f"bookmark-tui: no bookmarks found in {path}", file=sys.stderr)
        return 1
    store.replace_all(bookmarks)
    print(f"bookmark-tui: imported {len(bookmarks)} bookmarks from {path}")
    if launch_tui:
        return run_tui(store)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bookmark-tui",
        description="Fast, rofi-like terminal UI for managing bookmarks.",
    )
    parser.add_argument(
        "--import-file",
        dest="import_file",
        metavar="FILE",
        help="import bookmarks from FILE (buku .db, Firefox/Chrome .json)",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="with --import: import only, don't launch the TUI",
    )
    parser.add_argument(
        "--store",
        metavar="PATH",
        help="path to the bookmark store (default: $XDG_DATA_HOME/bookmark-tui/bookmarks.json)",
    )
    args = parser.parse_args(argv)

    store_path = Path(args.store) if args.store else default_store_path()
    store = BookmarkStore(store_path)

    if args.import_file is not None:
        return run_import(Path(args.import_file), store, launch_tui=not args.no_tui)

    return run_tui(store)

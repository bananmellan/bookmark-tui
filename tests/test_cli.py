"""Tests for the CLI entry point."""

import json
import sqlite3
from pathlib import Path

from bookmark_tui.cli import main, default_store_path
from bookmark_tui.storage import BookmarkStore


def test_import_buku_db(tmp_path, capsys):
    db = tmp_path / "buku.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE bookmarks (id INTEGER PRIMARY KEY, URL TEXT, metadata TEXT, tags TEXT, desc TEXT, flags INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO bookmarks (URL, metadata, tags, desc) VALUES ('https://example.com', 'Example', ',dev,', '')")
    conn.commit()
    conn.close()

    store_path = tmp_path / "store.json"
    rc = main(["--import-file", str(db), "--no-tui", "--store", str(store_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "imported 1 bookmarks" in captured.out

    store = BookmarkStore(store_path)
    assert len(store.all) == 1
    assert store.all[0].url == "https://example.com"


def test_import_firefox_json(tmp_path, capsys):
    ff = tmp_path / "firefox.json"
    ff.write_text(json.dumps({
        "roots": {
            "menu": {
                "type": "text/x-moz-place-container",
                "title": "menu",
                "children": [
                    {"type": "text/x-moz-place", "title": "GitHub", "uri": "https://github.com"},
                ],
            }
        }
    }))

    store_path = tmp_path / "store.json"
    rc = main(["--import-file", str(ff), "--no-tui", "--store", str(store_path)])
    assert rc == 0
    store = BookmarkStore(store_path)
    assert len(store.all) == 1
    assert store.all[0].title == "GitHub"


def test_import_chrome_json(tmp_path, capsys):
    chrome = tmp_path / "chrome.json"
    chrome.write_text(json.dumps({
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "Bookmarks bar",
                "children": [
                    {
                        "type": "folder",
                        "name": "Dev",
                        "children": [
                            {"type": "url", "name": "SO", "url": "https://stackoverflow.com"},
                        ],
                    },
                ],
            }
        }
    }))

    store_path = tmp_path / "store.json"
    rc = main(["--import-file", str(chrome), "--no-tui", "--store", str(store_path)])
    assert rc == 0
    store = BookmarkStore(store_path)
    assert store.all[0].category == "dev"


def test_import_bad_file(tmp_path, capsys):
    bad = tmp_path / "bad.txt"
    bad.write_text("hello")
    store_path = tmp_path / "store.json"
    rc = main(["--import-file", str(bad), "--no-tui", "--store", str(store_path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "import failed" in captured.err


def test_import_empty_file(tmp_path, capsys):
    empty = tmp_path / "empty.json"
    empty.write_text("[]")
    store_path = tmp_path / "store.json"
    rc = main(["--import-file", str(empty), "--no-tui", "--store", str(store_path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "no bookmarks found" in captured.err


def test_default_store_path():
    path = default_store_path()
    assert path.name == "bookmarks.json"
    assert "bookmark-tui" in str(path)

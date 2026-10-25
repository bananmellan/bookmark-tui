"""Tests for bookmark import."""

import json
import sqlite3

import pytest

from bookmark_tui.import_bookmarks import import_file, ImportError_


# ------------------------------------------------------------ buku .db


def test_import_buku_db(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE bookmarks (id INTEGER PRIMARY KEY, URL TEXT, metadata TEXT, tags TEXT, desc TEXT, flags INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO bookmarks (URL, metadata, tags, desc) VALUES (?, ?, ?, ?)",
                 ("https://example.com", "Example", ",dev,tools,", "A site"))
    conn.execute("INSERT INTO bookmarks (URL, metadata, tags, desc) VALUES (?, ?, ?, ?)",
                 ("https://bank.com", "Bank", ",", ""))
    conn.commit()
    conn.close()

    bookmarks = import_file(db)
    assert len(bookmarks) == 2
    assert bookmarks[0].url == "https://example.com"
    assert bookmarks[0].title == "Example"
    assert bookmarks[0].category == "dev/tools"
    assert bookmarks[1].url == "https://bank.com"
    assert bookmarks[1].category == ""


def test_import_buku_db_sequential_ids(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE bookmarks (id INTEGER PRIMARY KEY, URL TEXT, metadata TEXT, tags TEXT, desc TEXT, flags INTEGER DEFAULT 0)")
    conn.execute("INSERT INTO bookmarks (URL, metadata, tags, desc) VALUES ('https://a.com', 'A', ',', '')")
    conn.execute("INSERT INTO bookmarks (URL, metadata, tags, desc) VALUES ('https://b.com', 'B', ',', '')")
    conn.commit()
    conn.close()

    bookmarks = import_file(db)
    assert [b.id for b in bookmarks] == [1, 2]


# ------------------------------------------------------------ buku JSON


def test_import_buku_json(tmp_path):
    path = tmp_path / "buku.json"
    path.write_text(json.dumps([
        {"uri": "https://example.com", "title": "Example", "tags": "dev,tools", "description": ""},
        {"uri": "https://bank.com", "title": "Bank", "tags": "", "description": ""},
    ]))
    bookmarks = import_file(path)
    assert len(bookmarks) == 2
    assert bookmarks[0].url == "https://example.com"
    assert bookmarks[0].category == "dev/tools"


# ------------------------------------------------------------ Firefox JSON


def test_import_firefox_json(tmp_path):
    path = tmp_path / "firefox.json"
    data = {
        "roots": {
            "menu": {
                "type": "text/x-moz-place-container",
                "title": "menu",
                "children": [
                    {
                        "type": "text/x-moz-place-container",
                        "title": "Food",
                        "children": [
                            {
                                "type": "text/x-moz-place-container",
                                "title": "Recipes",
                                "children": [
                                    {
                                        "type": "text/x-moz-place",
                                        "title": "Pasta Carbonara",
                                        "uri": "https://pasta.example.com",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "type": "text/x-moz-place",
                        "title": "GitHub",
                        "uri": "https://github.com",
                    },
                ],
            }
        }
    }
    path.write_text(json.dumps(data))
    bookmarks = import_file(path)
    assert len(bookmarks) == 2
    pasta = [b for b in bookmarks if b.title == "Pasta Carbonara"][0]
    assert pasta.category == "food/recipes"
    github = [b for b in bookmarks if b.title == "GitHub"][0]
    assert github.category == ""


def test_import_firefox_skips_root_folders(tmp_path):
    """Root folders like 'menu', 'toolbar', 'unfiled' should not appear
    in the category path."""
    path = tmp_path / "firefox.json"
    data = {
        "roots": {
            "toolbar": {
                "type": "text/x-moz-place-container",
                "title": "toolbar",
                "children": [
                    {"type": "text/x-moz-place", "title": "A", "uri": "https://a.com"},
                ],
            }
        }
    }
    path.write_text(json.dumps(data))
    bookmarks = import_file(path)
    assert bookmarks[0].category == ""


# ------------------------------------------------------------ Chrome JSON


def test_import_chrome_json(tmp_path):
    path = tmp_path / "chrome.json"
    data = {
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "Bookmarks bar",
                "children": [
                    {
                        "type": "folder",
                        "name": "Dev",
                        "children": [
                            {"type": "url", "name": "Stack Overflow", "url": "https://stackoverflow.com"},
                        ],
                    },
                    {"type": "url", "name": "Reddit", "url": "https://reddit.com"},
                ],
            }
        }
    }
    path.write_text(json.dumps(data))
    bookmarks = import_file(path)
    assert len(bookmarks) == 2
    so = [b for b in bookmarks if b.title == "Stack Overflow"][0]
    assert so.category == "dev"
    reddit = [b for b in bookmarks if b.title == "Reddit"][0]
    assert reddit.category == ""


# ------------------------------------------------------------ plain JSON list


def test_import_plain_json_list(tmp_path):
    path = tmp_path / "bookmarks.json"
    path.write_text(json.dumps([
        {"url": "https://a.com", "title": "A", "category": "x/y"},
        {"url": "https://b.com", "title": "B"},
    ]))
    bookmarks = import_file(path)
    assert len(bookmarks) == 2
    assert bookmarks[0].category == "x/y"
    assert bookmarks[1].category == ""


# ------------------------------------------------------------ errors


def test_import_unsupported_extension(tmp_path):
    path = tmp_path / "bookmarks.txt"
    path.write_text("hello")
    with pytest.raises(ImportError_):
        import_file(path)


def test_import_empty_file(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("[]")
    bookmarks = import_file(path)
    assert bookmarks == []


def test_import_skips_entries_without_url(tmp_path):
    path = tmp_path / "bookmarks.json"
    path.write_text(json.dumps([
        {"url": "", "title": "No URL"},
        {"url": "https://valid.com", "title": "Valid"},
    ]))
    bookmarks = import_file(path)
    assert len(bookmarks) == 1
    assert bookmarks[0].url == "https://valid.com"

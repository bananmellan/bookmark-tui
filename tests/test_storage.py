"""Tests for the BookmarkStore."""

import json

from bookmark_tui.models import Bookmark
from bookmark_tui.storage import BookmarkStore


def test_empty_store(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    assert store.all == []


def test_add_and_get(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    bm = store.add("https://example.com", "Example", "dev")
    assert bm.id == 1
    assert bm.url == "https://example.com"
    assert bm.title == "Example"
    assert bm.category == "dev"
    assert store.get(1) == bm
    assert store.get(999) is None


def test_add_increments_id(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    bm1 = store.add("https://a.com")
    bm2 = store.add("https://b.com")
    assert bm1.id == 1
    assert bm2.id == 2


def test_update(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    bm = store.add("https://example.com", "Old", "cat1")
    updated = store.update(bm.id, "https://new.com", "New", "cat2")
    assert updated is not None
    assert updated.url == "https://new.com"
    assert updated.title == "New"
    assert updated.category == "cat2"
    assert updated.id == bm.id
    assert store.get(bm.id) == updated


def test_update_nonexistent(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    assert store.update(999, "https://x.com") is None


def test_delete(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    bm = store.add("https://example.com", "Example")
    assert store.delete(bm.id) is True
    assert store.get(bm.id) is None
    assert store.delete(999) is False


def test_persistence(tmp_path):
    path = tmp_path / "bookmarks.json"
    store = BookmarkStore(path)
    store.add("https://a.com", "A", "cat")
    store.add("https://b.com", "B")

    store2 = BookmarkStore(path)
    assert len(store2.all) == 2
    urls = {bm.url for bm in store2.all}
    assert urls == {"https://a.com", "https://b.com"}


def test_next_id_preserved_after_reload(tmp_path):
    path = tmp_path / "bookmarks.json"
    store = BookmarkStore(path)
    store.add("https://a.com")
    store.add("https://b.com")

    store2 = BookmarkStore(path)
    bm = store2.add("https://c.com")
    assert bm.id == 3


def test_all_sorted_by_title(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    store.add("https://z.com", "Zebra")
    store.add("https://a.com", "Apple")
    store.add("https://m.com", "Mango")
    titles = [bm.title for bm in store.all]
    assert titles == ["Apple", "Mango", "Zebra"]


def test_all_sorted_case_insensitive(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    store.add("https://b.com", "banana")
    store.add("https://a.com", "Apple")
    titles = [bm.title for bm in store.all]
    assert titles == ["Apple", "banana"]


def test_replace_all(tmp_path):
    store = BookmarkStore(tmp_path / "bookmarks.json")
    store.add("https://old.com", "Old")
    new_bookmarks = [
        Bookmark(id=1, url="https://new1.com", title="New 1", category="a"),
        Bookmark(id=2, url="https://new2.com", title="New 2", category="b"),
    ]
    store.replace_all(new_bookmarks)
    assert len(store.all) == 2
    assert store.all[0].url == "https://new1.com"
    # Next add should get id 3
    bm = store.add("https://new3.com")
    assert bm.id == 3


def test_corrupted_file_starts_empty(tmp_path):
    path = tmp_path / "bookmarks.json"
    path.write_text("not json")
    store = BookmarkStore(path)
    assert store.all == []


def test_wrong_version_starts_empty(tmp_path):
    path = tmp_path / "bookmarks.json"
    path.write_text(json.dumps({"version": 999, "items": []}))
    store = BookmarkStore(path)
    assert store.all == []


def test_atomic_write_permissions(tmp_path):
    import os
    path = tmp_path / "bookmarks.json"
    store = BookmarkStore(path)
    store.add("https://a.com")
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600


def test_symlinked_store_is_followed_not_replaced(tmp_path):
    """A symlinked bookmarks.json (e.g. GNU stow) must survive writes:
    the write lands in the real file and the link stays a link."""
    import os
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = real_dir / "bookmarks.json"
    real.write_text(json.dumps({"version": 1, "items": []}))
    link = tmp_path / "bookmarks.json"
    os.symlink(real, link)

    store = BookmarkStore(link)
    store.add("https://a.com", "A", "dev")

    assert link.is_symlink(), "symlink was replaced by a regular file"
    assert os.readlink(link) == str(real)
    # The write went through the link into the real file.
    reloaded = BookmarkStore(link)
    assert [b.url for b in reloaded.all] == ["https://a.com"]
    data = json.loads(real.read_text())
    assert data["items"] == [
        {"id": 1, "url": "https://a.com", "title": "A", "category": "dev"}
    ]


def test_symlinked_store_update_and_delete_keep_link(tmp_path):
    import os
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = real_dir / "bookmarks.json"
    real.write_text(json.dumps({"version": 1, "items": []}))
    link = tmp_path / "bookmarks.json"
    os.symlink(real, link)

    store = BookmarkStore(link)
    bm = store.add("https://a.com", "A", "dev")
    store.update(bm.id, "https://b.com", "B", "dev")
    assert link.is_symlink()
    assert [b.url for b in BookmarkStore(link).all] == ["https://b.com"]
    store.delete(bm.id)
    assert link.is_symlink()
    assert BookmarkStore(link).all == []


def test_dangling_symlink_creates_target(tmp_path):
    """A symlink whose target doesn't exist yet (stow not linked into
    place) is resolved and the target file is created on first save."""
    import os
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    real = real_dir / "bookmarks.json"
    link = tmp_path / "bookmarks.json"
    os.symlink(real, link)

    store = BookmarkStore(link)
    store.add("https://a.com")

    assert link.is_symlink()
    assert real.exists()
    assert [b.url for b in BookmarkStore(link).all] == ["https://a.com"]

"""Tests for the Bookmark model."""

from bookmark_tui.models import Bookmark


def test_to_dict_roundtrip():
    bm = Bookmark(id=1, url="https://example.com", title="Example", category="dev/tools")
    d = bm.to_dict()
    assert d == {"id": 1, "url": "https://example.com", "title": "Example", "category": "dev/tools"}
    bm2 = Bookmark.from_dict(d)
    assert bm2 == bm


def test_from_dict_defaults():
    bm = Bookmark.from_dict({"id": 5, "url": "https://x.com"})
    assert bm.id == 5
    assert bm.url == "https://x.com"
    assert bm.title == ""
    assert bm.category == ""


def test_from_dict_rejects_non_dict():
    import pytest
    with pytest.raises(ValueError):
        Bookmark.from_dict("not a dict")


def test_bookmark_is_frozen():
    import pytest
    bm = Bookmark(id=1, url="https://x.com")
    with pytest.raises(AttributeError):
        bm.title = "new"

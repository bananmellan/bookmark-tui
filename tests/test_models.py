import pytest

from buku_tui.models import BookmarkRef


def test_roundtrip():
    ref = BookmarkRef(
        index=3,
        url="https://example.com/x",
        title="Example",
        tags=("a", "b"),
        description="notes",
    )
    assert BookmarkRef.from_dict(ref.to_dict()) == ref


def test_from_dict_requires_positive_int_index():
    with pytest.raises(ValueError):
        BookmarkRef.from_dict({"index": 0, "url": "https://x.example"})
    with pytest.raises(ValueError):
        BookmarkRef.from_dict({"index": "1", "url": "https://x.example"})
    with pytest.raises(ValueError):
        BookmarkRef.from_dict({"index": True, "url": "https://x.example"})
    with pytest.raises(ValueError):
        BookmarkRef.from_dict({"url": "https://x.example"})


def test_from_dict_requires_url():
    with pytest.raises(ValueError):
        BookmarkRef.from_dict({"index": 1, "url": ""})
    with pytest.raises(ValueError):
        BookmarkRef.from_dict({"index": 1})


def test_from_dict_defaults():
    ref = BookmarkRef.from_dict({"index": 1, "url": "https://x.example"})
    assert ref.title == ""
    assert ref.tags == ()
    assert ref.description == ""


def test_from_dict_rejects_non_dict():
    with pytest.raises(ValueError):
        BookmarkRef.from_dict(["not", "a", "dict"])

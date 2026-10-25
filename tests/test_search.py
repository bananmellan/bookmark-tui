"""Tests for the search module."""

from bookmark_tui.models import Bookmark
from bookmark_tui.search import filter_bookmarks, search_text


def bm(id=1, title="", url="", category=""):
    return Bookmark(id=id, url=url, title=title, category=category)


def test_empty_query_returns_all():
    bookmarks = [bm(1, "A", "https://a.com"), bm(2, "B", "https://b.com")]
    assert filter_bookmarks(bookmarks, "") == bookmarks
    assert filter_bookmarks(bookmarks, "  ") == bookmarks


def test_title_substring_match():
    bookmarks = [
        bm(1, "GitHub", "https://github.com"),
        bm(2, "Bank", "https://bank.com"),
    ]
    result = filter_bookmarks(bookmarks, "git")
    assert len(result) == 1
    assert result[0].title == "GitHub"


def test_case_insensitive():
    bookmarks = [bm(1, "GitHub", "https://github.com")]
    assert len(filter_bookmarks(bookmarks, "GITHUB")) == 1
    assert len(filter_bookmarks(bookmarks, "github")) == 1


def test_url_match():
    bookmarks = [
        bm(1, "Code", "https://github.com"),
        bm(2, "Bank", "https://bank.com"),
    ]
    result = filter_bookmarks(bookmarks, "github.com")
    assert len(result) == 1
    assert result[0].title == "Code"


def test_category_match():
    bookmarks = [
        bm(1, "Pasta", "https://pasta.com", "food/recipes"),
        bm(2, "Bank", "https://bank.com", "finance"),
    ]
    result = filter_bookmarks(bookmarks, "food")
    assert len(result) == 1
    assert result[0].title == "Pasta"


def test_subsequence_match():
    bookmarks = [bm(1, "GitHub", "https://github.com")]
    assert len(filter_bookmarks(bookmarks, "ghub")) == 1


def test_subsequence_needs_three_chars():
    bookmarks = [bm(1, "GitHub", "https://github.com")]
    assert len(filter_bookmarks(bookmarks, "gh")) == 0


def test_all_tokens_must_match():
    bookmarks = [
        bm(1, "GitHub", "https://github.com", "dev"),
        bm(2, "GitLab", "https://gitlab.com", "dev"),
    ]
    result = filter_bookmarks(bookmarks, "git dev")
    assert len(result) == 2


def test_no_match():
    bookmarks = [bm(1, "A", "https://a.com")]
    assert filter_bookmarks(bookmarks, "zzz") == []


def test_title_match_ranks_before_url_match():
    bookmarks = [
        bm(1, "Other", "https://github.com"),
        bm(2, "GitHub", "https://example.com"),
    ]
    result = filter_bookmarks(bookmarks, "github")
    assert result[0].title == "GitHub"


def test_search_text_includes_all_fields():
    b = bm(1, "My Title", "https://my.com", "food/recipes")
    text = search_text(b)
    assert "My Title" in text
    assert "https://my.com" in text
    assert "food/recipes" in text


def test_search_text_empty_fields_skipped():
    b = bm(1, "Title", "https://x.com")
    text = search_text(b)
    assert text == "Title https://x.com"

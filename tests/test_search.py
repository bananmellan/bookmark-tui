from buku_tui.models import BookmarkRef
from buku_tui.search import filter_bookmarks, search_text


def ref(index=1, title="GitHub", url="https://github.com", tags=(), description=""):
    return BookmarkRef(index=index, url=url, title=title, tags=tags, description=description)


def test_empty_query_returns_everything_in_order():
    refs = [ref(2, "Bank"), ref(1, "GitHub")]
    assert filter_bookmarks(refs, "") == refs
    assert filter_bookmarks(refs, "   ") == refs


def test_title_substring_matches():
    refs = [
        ref(1, "GitHub", "https://github.com"),
        ref(2, "GitLab", "https://gitlab.com"),
        ref(3, "Bank", "https://bank.example.com"),
    ]
    assert [r.title for r in filter_bookmarks(refs, "git")] == ["GitHub", "GitLab"]


def test_match_is_case_insensitive():
    refs = [ref(1, "GitHub")]
    assert len(filter_bookmarks(refs, "GITHUB")) == 1
    assert len(filter_bookmarks(refs, "github")) == 1


def test_subsequence_match_for_long_tokens():
    refs = [
        ref(1, "GitHub", "https://a.example"),
        ref(2, "Bank", "https://b.example"),
    ]
    assert [r.title for r in filter_bookmarks(refs, "ghub")] == ["GitHub"]


def test_subsequence_needs_three_chars():
    refs = [
        ref(1, "GitHub", "https://a.example"),
        ref(2, "Gutter Hub", "https://b.example"),
    ]
    # "gh" is a substring of "GitHub" but only a subsequence of
    # "Gutter Hub"; two-letter tokens stay substring-only.
    assert [r.title for r in filter_bookmarks(refs, "githu")] == ["GitHub"]
    assert [r.title for r in filter_bookmarks(refs, "gith")] == ["GitHub"]
    # 3+ char tokens may subsequence-match.
    assert [r.title for r in filter_bookmarks(refs, "gthb")] == ["GitHub", "Gutter Hub"]


def test_url_and_tags_and_description_match():
    refs = [
        ref(1, "A", "https://news.ycombinator.com", ("hn", "news")),
        ref(2, "B", "https://example.com", ("coding",), "a python doc page"),
    ]
    assert [r.index for r in filter_bookmarks(refs, "ycombinator")] == [1]
    assert [r.index for r in filter_bookmarks(refs, "coding")] == [2]
    assert [r.index for r in filter_bookmarks(refs, "python doc")] == [2]


def test_title_match_ranks_before_url_match():
    refs = [
        ref(1, "Docs", "https://python.org"),
        ref(2, "python docs", "https://example.com"),
    ]
    result = filter_bookmarks(refs, "python")
    assert result[0].index == 2  # title substring beats url substring


def test_all_tokens_must_match():
    refs = [ref(1, "GitHub", "https://github.com", ("code",)), ref(2, "GitLab")]
    assert [r.index for r in filter_bookmarks(refs, "git code")] == [1]


def test_stable_order_within_rank():
    refs = [ref(3, "Beta"), ref(1, "Alpha"), ref(2, "Alpine")]
    result = filter_bookmarks(refs, "al")
    assert [r.title for r in result] == ["Alpha", "Alpine"]


def test_host_query_is_substring_only():
    """A host-like query must not fuzzy-subsequence-match unrelated
    bookmarks (an alias at bi.honung.org contains the characters of
    nc.honung.org in order)."""
    refs = [
        ref(1, "NextCloud", "https://nc.honung.org"),
        ref(2, "blog", "https://bi.honung.org"),
        ref(3, "mail", "https://gmail.com"),
    ]
    result = filter_bookmarks(refs, "nc.honung.org")
    assert [r.index for r in result] == [1]


def test_host_query_flag_forces_precise_matching():
    refs = [
        ref(1, "NextCloud", "https://nc.honung.org"),
        ref(2, "blog", "https://bi.honung.org"),
    ]
    assert [r.index for r in filter_bookmarks(refs, "nc.honung.org", host_query=True)] == [1]


def test_search_text_includes_all_fields():
    r = ref(1, "T", "https://u.example", ("tag1",), "some description")
    text = search_text(r)
    assert "T" in text
    assert "https://u.example" in text
    assert "tag1" in text
    assert "some description" in text

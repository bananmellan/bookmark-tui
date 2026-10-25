"""Live filtering for the bookmark list.

Pure functions, no I/O: given the full bookmark list and the current
query string, produce the filtered, ordered list. Matching is
token-based and case-insensitive; a token matches when it is a
substring of the search text, or when all of the query's characters
appear in order (subsequence) in the search text.

Searchable fields: title, url, category.

Ranking: title-substring matches first, then subsequence matches, then
url/category-only matches. Within a rank, the original title-sorted
order is kept.
"""

from __future__ import annotations

from .models import Bookmark


def _is_subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(ch in it for ch in needle)


def search_text(bm: Bookmark) -> str:
    """All searchable text for a bookmark: title, url, category."""
    parts = [bm.title, bm.url, bm.category]
    return " ".join(p for p in parts if p)


def _score(bm: Bookmark, query: str) -> int | None:
    """Lower is better; None means no match.

    Tokens are whitespace-separated. A token matches the title by
    substring (best) or subsequence; otherwise it matches the combined
    title+url+category text by substring, then subsequence. A
    subsequence match only counts for tokens of at least 3 characters.
    Every token must match somewhere; the bookmark's score is the worst
    token rank.
    """
    title = bm.title.lower()
    haystack = search_text(bm).lower()
    worst = -1
    for token in query.split():
        if not token:
            continue
        if token in title:
            rank = 1
        elif len(token) >= 3 and _is_subsequence(token, title):
            rank = 2
        elif token in haystack:
            rank = 3
        elif len(token) >= 3 and _is_subsequence(token, haystack):
            rank = 4
        else:
            return None
        worst = max(worst, rank)
    if worst < 0:
        return None
    return worst


def filter_bookmarks(bookmarks: list[Bookmark], query: str) -> list[Bookmark]:
    """Bookmarks matching the query, best matches first, stable within a rank.

    An empty query returns everything in the input order.
    """
    query = query.strip().lower()
    if not query:
        return list(bookmarks)
    scored = []
    for bm in bookmarks:
        value = _score(bm, query)
        if value is not None:
            scored.append((value, bm))
    scored.sort(key=lambda entry: entry[0])
    return [bm for _score_value, bm in scored]

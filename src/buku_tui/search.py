"""Live filtering for the bookmark list.

Pure functions, no I/O: given the full bookmark list and the current
query string, produce the filtered, ordered list. Matching is
token-based and case-insensitive; a token matches when it is a substring
of the search text, or when all of the query's characters appear in
order (subsequence) in the search text, so `ghub` finds "GitHub".

Ranking: title-substring matches first, then subsequence matches, then
url/tags/description-only matches. Within a rank, the original
title-sorted order is kept, so the list is stable while typing.
"""

from __future__ import annotations

from .models import BookmarkRef


def _is_subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(ch in it for ch in needle)


def search_text(ref: BookmarkRef) -> str:
    """All searchable text for a ref: title, then url, then tags, then
    description."""
    parts = [ref.title, ref.url, *ref.tags]
    if ref.description:
        parts.append(ref.description)
    return " ".join(parts)


def _score(ref: BookmarkRef, query: str) -> int | None:
    """Lower is better; None means no match.

    Tokens are whitespace-separated. A token matches the title by
    substring (best) or subsequence; otherwise it matches the combined
    title+url+tags+description text by substring, then subsequence. A
    subsequence match only counts for tokens of at least 3 characters,
    so two-letter queries stay precise. Every token must match
    somewhere; the ref's score is the worst token rank, so multi-token
    queries rank by their least specific token.
    """
    title = ref.title.lower()
    haystack = search_text(ref).lower()
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


def _is_host_query(query: str) -> bool:
    """True when the query looks like a host: dot-separated labels of
    letters/digits/hyphens, e.g. "nc.honung.org" or "example.com:8080".

    Host queries come from the clipboard prefill and must stay precise:
    the fuzzy subsequence rank would otherwise match unrelated bookmarks
    (a bookmark at bi.honung.org contains the characters of nc.honung.org
    in order, and titles contain scattered letters of it).
    """
    token = query.split()[0] if query.split() else ""
    if "." not in token:
        return False
    if "://" in token or "/" in token:
        return False  # a full URL, not a bare host
    token = token.rsplit(":", 1)[0]  # strip a port
    return bool(token) and all(
        part and all(ch.isalnum() or ch == "-" for ch in part)
        for part in token.split(".")
    )


def _host_score(ref: BookmarkRef, query: str) -> int | None:
    """Precise scoring for host-like queries. Lower is better; None
    means no match.

    A token matches only by substring against the bookmark's search text
    (title, url, tags, description). No subsequence matching: host
    queries are prefilled from the clipboard and must not pull in
    bookmarks that merely share scattered characters.
    """
    haystack = search_text(ref).lower()
    title = ref.title.lower()
    worst = -1
    for token in query.split():
        if not token:
            continue
        if token in title:
            rank = 1
        elif token in haystack:
            rank = 3
        else:
            return None
        worst = max(worst, rank)
    if worst < 0:
        return None
    return worst


def filter_bookmarks(
    refs: list[BookmarkRef], query: str, host_query: bool = False
) -> list[BookmarkRef]:
    """Bookmarks matching the query, best matches first, stable within a rank.

    The input list is expected to be in display order (title-sorted);
    the output preserves that order within each rank. An empty query
    returns everything, so the unfiltered list is the sorted full list.

    `host_query` selects precise host-style matching (substring only, no
    subsequence) for clipboard-prefilled queries.
    """
    query = query.strip().lower()
    if not query:
        return list(refs)
    score = _host_score if host_query or _is_host_query(query) else _score
    scored = []
    for ref in refs:
        value = score(ref, query)
        if value is not None:
            scored.append((value, ref))
    scored.sort(key=lambda entry: entry[0])
    return [ref for _score_value, ref in scored]

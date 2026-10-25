import json
import os
import time

import pytest

from buku_tui.bukucli import BukuCli, BukuCliError
from buku_tui.cache import CACHE_NAME, Cache, cache_age, dump_cache, load_cache, match_host, sort_refs
from buku_tui.models import BookmarkRef


def ref(index=1, title="GitHub", url="https://github.com", tags=("code",), description=""):
    return BookmarkRef(index=index, url=url, title=title, tags=tags, description=description)


def make_client(payload=None, fail=False):
    def runner(argv):
        if fail:
            raise BukuCliError("offline")
        return json.dumps(payload if payload is not None else [])

    return BukuCli("buku", runner=runner)


def test_roundtrip(tmp_path):
    path = tmp_path / CACHE_NAME
    refs = [ref(1), ref(2, "Bank", "https://bank.example.com", ("finance",))]
    dump_cache(refs, path)
    assert load_cache(path) == sort_refs(refs)


def test_dump_cache_stores_items_title_sorted(tmp_path):
    """The cache is written title-sorted so display order matches the file."""
    path = tmp_path / CACHE_NAME
    dump_cache([ref(1), ref(2, "Bank", "https://bank.example.com")], path)
    titles = [item["title"] for item in json.loads(path.read_text())["items"]]
    assert titles == ["Bank", "GitHub"]


def test_dump_cache_is_0600(tmp_path):
    path = tmp_path / CACHE_NAME
    dump_cache([ref(1)], path)
    assert (path.stat().st_mode & 0o777) == 0o600


def test_load_cache_rejects_foreign_keys(tmp_path):
    path = tmp_path / CACHE_NAME
    payload = {
        "version": 1,
        "items": [{"index": 1, "url": "https://x.example", "title": "X", "secret": "nope"}],
    }
    path.write_text(json.dumps(payload))
    assert load_cache(path) == []


def test_load_cache_rejects_wrong_version(tmp_path):
    path = tmp_path / CACHE_NAME
    path.write_text(json.dumps({"version": 999, "items": []}))
    assert load_cache(path) == []


def test_load_cache_missing_file(tmp_path):
    assert load_cache(tmp_path / "nope.json") == []


def test_load_cache_dedups_by_index(tmp_path):
    path = tmp_path / CACHE_NAME
    payload = {
        "version": 1,
        "items": [
            {"index": 1, "url": "https://a.example", "title": "A", "tags": [], "description": ""},
            {"index": 1, "url": "https://b.example", "title": "B", "tags": [], "description": ""},
        ],
    }
    path.write_text(json.dumps(payload))
    refs = load_cache(path)
    assert len(refs) == 1
    assert refs[0].url == "https://a.example"


def test_sort_refs_title_then_url():
    refs = [
        ref(1, "beta", "https://z.example"),
        ref(2, "Alpha", "https://b.example"),
        ref(3, "alpha", "https://a.example"),
    ]
    assert [r.index for r in sort_refs(refs)] == [3, 2, 1]


def test_cache_get_loads_and_rebuilds_when_empty(tmp_path):
    path = tmp_path / CACHE_NAME
    client = make_client([{"index": 1, "uri": "https://x.example", "title": "X", "tags": "", "description": ""}])
    cache = Cache(path, client, ttl=600)
    refs = cache.get()
    assert [r.url for r in refs] == ["https://x.example"]
    assert path.exists()


def test_cache_get_rebuilds_when_stale(tmp_path):
    path = tmp_path / CACHE_NAME
    dump_cache([ref(1, "Old", "https://old.example")], path)
    os.utime(path, (time.time() - 3600, time.time() - 3600))
    client = make_client([{"index": 2, "uri": "https://new.example", "title": "New", "tags": "", "description": ""}])
    cache = Cache(path, client, ttl=600)
    refs = cache.get()
    assert [r.title for r in refs] == ["New"]


def test_cache_get_keeps_stale_cache_on_rebuild_failure(tmp_path):
    path = tmp_path / CACHE_NAME
    dump_cache([ref(1, "Old", "https://old.example")], path)
    os.utime(path, (time.time() - 3600, time.time() - 3600))
    cache = Cache(path, make_client(fail=True), ttl=600)
    refs = cache.get()
    assert [r.title for r in refs] == ["Old"]


def test_cache_age(tmp_path):
    path = tmp_path / CACHE_NAME
    assert cache_age(path) is None
    path.write_text("x")
    assert cache_age(path, now=time.time() + 5) == pytest.approx(5, abs=1)


def test_ensure_fresh_async_spawns_once(tmp_path):
    path = tmp_path / CACHE_NAME
    dump_cache([ref(1)], path)
    os.utime(path, (time.time() - 3600, time.time() - 3600))
    cache = Cache(path, make_client(), ttl=600)
    spawned = []
    assert cache.ensure_fresh_async(lambda c: spawned.append(c)) is True
    assert len(spawned) == 1
    # Lock file is fresh: a second call does not spawn again.
    assert cache.ensure_fresh_async(lambda c: spawned.append(c)) is False


def test_ensure_fresh_async_skips_fresh_cache(tmp_path):
    path = tmp_path / CACHE_NAME
    dump_cache([ref(1)], path)
    cache = Cache(path, make_client(), ttl=600)
    assert cache.ensure_fresh_async(lambda c: None) is False


# ------------------------------------------------------------ match_host


def test_match_host_exact_host_first():
    refs = [
        ref(1, "Sub", "https://nc.honung.org/apps/dashboard/"),
        ref(2, "Exact", "https://honung.org"),
        ref(3, "Other", "https://honung.org.evil.example"),
    ]
    matches = match_host(refs, "honung.org")
    assert matches[0].index == 2  # exact host equality beats subdomain/path


def test_match_host_subdomain_beats_contains():
    refs = [
        ref(1, "Deep", "https://a.b.honung.org/x"),
        ref(2, "Sub", "https://sub.honung.org"),
    ]
    matches = match_host(refs, "honung.org")
    # Both are subdomains (rank 80); the tie breaks alphabetically by
    # title, so "Deep" comes first. Both outrank a mere host-contains.
    assert {r.index for r in matches} == {1, 2}
    assert matches[0].title == "Deep"


def test_match_host_subdomain_beats_host_contains():
    refs = [
        ref(1, "Sub", "https://sub.honung.org"),
        ref(2, "Contains", "https://honung.org.evil.example"),
    ]
    matches = match_host(refs, "honung.org")
    assert matches[0].index == 1


def test_match_host_case_and_path_insensitive():
    refs = [ref(1, "NC", "https://NC.Honung.ORG/Apps/Dashboard/")]
    assert [r.index for r in match_host(refs, "nc.honung.org")] == [1]


def test_match_host_with_port():
    refs = [ref(1, "Local", "http://nc.honung.org:8080/x")]
    assert [r.index for r in match_host(refs, "nc.honung.org:8080")] == [1]
    # A bare host still matches a url with a port (host-contains rank).
    assert [r.index for r in match_host(refs, "nc.honung.org")] == [1]


def test_match_host_title_bonus():
    """'NextCloud' ranks above an unrelated title for nc.honung.org."""
    refs = [
        ref(1, "Random notes", "https://nc.honung.org"),
        ref(2, "NextCloud", "https://nc.honung.org"),
    ]
    matches = match_host(refs, "nc.honung.org")
    assert matches[0].title == "NextCloud"


def test_match_host_no_match():
    refs = [ref(1, "GitHub", "https://github.com")]
    assert match_host(refs, "gitlab.com") == []
    assert match_host(refs, "") == []

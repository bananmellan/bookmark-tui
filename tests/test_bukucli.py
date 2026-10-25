import json

import pytest

from buku_tui.bukucli import BukuCli, BukuCliError, parse_bookmarks
from buku_tui.models import BookmarkRef


SAMPLE_JSON = json.dumps(
    [
        {
            "description": "Contribute to bananmellan/buku-tui development.",
            "index": 1,
            "tags": "code,git,tui",
            "title": "GitHub - bananmellan/buku-tui",
            "uri": "https://github.com/bananmellan/buku-tui",
        },
        {
            "description": "",
            "index": 2,
            "tags": "hn,news",
            "title": "Hacker News",
            "uri": "https://news.ycombinator.com",
        },
        {
            "description": "",
            "index": 3,
            "tags": "",
            "title": "",
            "uri": "https://docs.python.org/3/",
        },
    ]
)


def test_parse_bookmarks_basic():
    refs = parse_bookmarks(json.loads(SAMPLE_JSON))
    assert len(refs) == 3
    assert refs[0] == BookmarkRef(
        index=1,
        url="https://github.com/bananmellan/buku-tui",
        title="GitHub - bananmellan/buku-tui",
        tags=("code", "git", "tui"),
        description="Contribute to bananmellan/buku-tui development.",
    )
    assert refs[2].title == ""
    assert refs[2].tags == ()


def test_parse_bookmarks_strips_internal_tag_commas():
    """buku's internal tagset has leading/trailing commas; the JSON form
    may carry them too — empty components must be dropped."""
    data = [{"index": 1, "uri": "https://x.example", "title": "", "tags": ",a,b,", "description": ""}]
    refs = parse_bookmarks(data)
    assert refs[0].tags == ("a", "b")


def test_parse_bookmarks_dedups_by_index():
    data = [
        {"index": 1, "uri": "https://a.example", "title": "", "tags": "", "description": ""},
        {"index": 1, "uri": "https://b.example", "title": "", "tags": "", "description": ""},
    ]
    refs = parse_bookmarks(data)
    assert len(refs) == 1
    assert refs[0].url == "https://a.example"


def test_parse_bookmarks_skips_entries_without_url_or_index():
    data = [
        {"index": 0, "uri": "https://a.example", "title": "", "tags": "", "description": ""},
        {"uri": "https://b.example", "title": "", "tags": "", "description": ""},
        {"index": 2, "title": "", "tags": "", "description": ""},
        "not a dict",
    ]
    assert parse_bookmarks(data) == []


def test_parse_bookmarks_rejects_non_list():
    with pytest.raises(BukuCliError):
        parse_bookmarks({"items": []})


def test_list_all_uses_nostdin_json_print():
    calls = []

    def runner(argv):
        calls.append(argv)
        return SAMPLE_JSON

    client = BukuCli("buku", runner=runner)
    refs, raw_count = client.list_all()
    assert calls == [["buku", "--nostdin", "-j", "-p"]]
    assert len(refs) == 3
    assert raw_count == 3


def test_list_all_tolerates_db_created_notice():
    """On a brand-new database buku prints a notice on stdout before the
    JSON array; parsing must skip ahead to the first '['."""

    def runner(argv):
        return "DB file is being created at /tmp/x/bookmarks.db.\nYou should encrypt it.\n" + SAMPLE_JSON

    refs, _ = BukuCli("buku", runner=runner).list_all()
    assert len(refs) == 3


def test_list_all_empty_database():
    def runner(argv):
        return ""

    refs, raw_count = BukuCli("buku", runner=runner).list_all()
    assert refs == []
    assert raw_count == 0


def test_list_all_invalid_json():
    def runner(argv):
        return "[not json"

    with pytest.raises(BukuCliError):
        BukuCli("buku", runner=runner).list_all()


def test_open_invokes_buku_with_index():
    calls = []

    def runner(argv):
        calls.append(argv)
        return ""

    client = BukuCli("buku", runner=runner)
    client.open(BookmarkRef(index=7, url="https://example.com"))
    assert calls == [["buku", "--nostdin", "-o", "7"]]


def test_open_raises_on_error_stderr(monkeypatch):
    """buku exits 0 even for a bad index; the [ERROR] marker on stderr is
    what signals failure."""
    import buku_tui.bukucli as mod

    def fake_run(argv, **kwargs):
        class Proc:
            returncode = 0
            stdout = b""
            stderr = b"\x1b[31m[ERROR]\x1b[0m No matching index 99\n"

        return Proc()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    with pytest.raises(BukuCliError, match="No matching index 99"):
        BukuCli("buku").open(BookmarkRef(index=99, url="https://example.com"))


def test_open_raises_on_nonzero_exit(monkeypatch):
    import buku_tui.bukucli as mod

    def fake_run(argv, **kwargs):
        class Proc:
            returncode = 1
            stdout = b""
            stderr = b"buku: error: DB is locked\n"

        return Proc()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    with pytest.raises(BukuCliError):
        BukuCli("buku").open(BookmarkRef(index=1, url="https://example.com"))


def test_run_missing_binary():
    with pytest.raises(BukuCliError, match="executable not found"):
        BukuCli("/nonexistent/buku").list_all()

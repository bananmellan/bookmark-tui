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


# ============================================================ add/update/delete


def test_add_invokes_buku_with_correct_args():
    calls = []

    def runner(argv):
        calls.append(argv)
        if "-a" in argv:
            return ""  # --tacit: no output on add
        # list_all call to find the index
        return json.dumps([{"index": 3, "uri": "https://example.com", "title": "My Title", "tags": "tag1,tag2", "description": "A desc"}])

    client = BukuCli("buku", runner=runner)
    idx = client.add("https://example.com", "My Title", ["tag1", "tag2"], "A desc")
    assert idx == 3
    argv = calls[0]
    assert argv[:4] == ["buku", "--nostdin", "-a", "https://example.com"]
    assert "tag1,tag2" in argv
    assert "--title" in argv
    assert "My Title" in argv
    assert "-c" in argv
    assert "A desc" in argv
    assert "--tacit" in argv


def test_add_with_empty_title_uses_flag_form():
    calls = []

    def runner(argv):
        calls.append(argv)
        if "-a" in argv:
            return ""
        return json.dumps([{"index": 1, "uri": "https://example.com", "title": "", "tags": "", "description": ""}])

    client = BukuCli("buku", runner=runner)
    client.add("https://example.com", "", [], "")
    argv = calls[0]
    # --title with no value follows
    title_idx = argv.index("--title")
    assert title_idx == len(argv) - 1 or argv[title_idx + 1] == "--tacit"


def test_add_with_no_tags_omits_positional():
    calls = []

    def runner(argv):
        calls.append(argv)
        if "-a" in argv:
            return ""
        return json.dumps([{"index": 1, "uri": "https://example.com", "title": "Title", "tags": "", "description": ""}])

    client = BukuCli("buku", runner=runner)
    client.add("https://example.com", "Title", [], "")
    argv = calls[0]
    assert "--title" in argv
    # No comma-separated tags positional between URL and --title
    url_idx = argv.index("https://example.com")
    title_idx = argv.index("--title")
    assert title_idx == url_idx + 1


def test_add_resolves_index_by_listing():
    """--tacit suppresses output; the index is found by listing."""
    def runner(argv):
        if "-a" in argv:
            return ""
        return json.dumps([
            {"index": 1, "uri": "https://other.com", "title": "Other", "tags": "", "description": ""},
            {"index": 5, "uri": "https://x.com", "title": "My Site", "tags": "", "description": ""},
        ])

    client = BukuCli("buku", runner=runner)
    idx = client.add("https://x.com", "My Site", [], "")
    assert idx == 5


def test_add_raises_when_url_not_found():
    def runner(argv):
        if "-a" in argv:
            return ""
        return json.dumps([{"index": 1, "uri": "https://other.com", "title": "", "tags": "", "description": ""}])

    client = BukuCli("buku", runner=runner)
    with pytest.raises(BukuCliError, match="not in listing"):
        client.add("https://x.com", "Title", [], "")


def test_update_invokes_buku_with_correct_args():
    calls = []

    def runner(argv):
        calls.append(argv)
        return ""

    client = BukuCli("buku", runner=runner)
    client.update(3, "https://new.com", "New Title", ["a", "b"], "New desc")
    # First call: update url, title, desc (no --tag in the first call)
    argv = calls[0]
    assert argv[:4] == ["buku", "--nostdin", "-u", "3"]
    assert "--url" in argv
    assert "https://new.com" in argv
    assert "--title" in argv
    assert "New Title" in argv
    assert "-c" in argv
    assert "New desc" in argv
    # Second call: set tags
    tag_call = calls[1]
    assert "--tag" in tag_call
    assert "a,b" in tag_call


def test_update_with_empty_fields_clears_them():
    calls = []

    def runner(argv):
        calls.append(argv)
        if "-j" in argv:
            # Listing to find existing tags for removal
            return json.dumps([{"index": 1, "uri": "https://x.com", "title": "T", "tags": "old1,old2", "description": "d"}])
        return ""

    client = BukuCli("buku", runner=runner)
    client.update(1, "https://x.com", "", [], "")
    # First call: update url, clear title, clear desc
    argv = calls[0]
    assert argv[:4] == ["buku", "--nostdin", "-u", "1"]
    assert "--url" in argv
    # --title with no value (clears title)
    title_idx = argv.index("--title")
    assert argv[title_idx + 1] == "-c"
    # -c with no value (clears desc)
    c_idx = argv.index("-c")
    assert c_idx == len(argv) - 1
    # Then: list to find tags, then remove each tag
    tag_removals = [c for c in calls if "-" in c and "--tag" in c]
    assert len(tag_removals) == 2
    assert "old1" in tag_removals[0]
    assert "old2" in tag_removals[1]


def test_update_with_tags_replaces_tagset():
    calls = []

    def runner(argv):
        calls.append(argv)
        return ""

    client = BukuCli("buku", runner=runner)
    client.update(1, "https://x.com", "T", ["new1", "new2"], "d")
    # First call: update url, title, desc
    argv = calls[0]
    assert "--title" in argv
    assert "T" in argv
    # Second call: set tags
    tag_call = calls[1]
    assert "--tag" in tag_call
    assert "new1,new2" in tag_call
    # No tag removal calls
    assert len(calls) == 2


def test_delete_invokes_buku_with_tacit():
    calls = []

    def runner(argv):
        calls.append(argv)
        return ""

    client = BukuCli("buku", runner=runner)
    client.delete(7)
    assert calls == [["buku", "--nostdin", "-d", "7", "--tacit"]]


def test_add_propagates_error():
    def runner(argv):
        raise BukuCliError("DB locked")

    client = BukuCli("buku", runner=runner)
    with pytest.raises(BukuCliError, match="DB locked"):
        client.add("https://x.com", "T", [], "")


def test_update_propagates_error():
    def runner(argv):
        raise BukuCliError("no such index")

    client = BukuCli("buku", runner=runner)
    with pytest.raises(BukuCliError):
        client.update(99, "https://x.com", "T", [], "")


def test_delete_propagates_error():
    def runner(argv):
        raise BukuCliError("DB locked")

    client = BukuCli("buku", runner=runner)
    with pytest.raises(BukuCliError):
        client.delete(1)

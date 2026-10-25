"""End-to-end tests against the real `buku` binary.

Skipped when buku is not installed. Uses a throwaway XDG_DATA_HOME so
the user's real bookmark database is never touched, and a fake BROWSER
script that records what buku would have launched.
"""

import os
import shutil
import subprocess
import time

import pytest

from buku_tui.bukucli import BukuCli, BukuCliError
from buku_tui.models import BookmarkRef

buku = shutil.which("buku")
pytestmark = pytest.mark.skipif(buku is None, reason="buku not installed")


@pytest.fixture()
def buku_env(tmp_path, monkeypatch):
    """A sandboxed buku environment plus a BukuCli bound to it."""
    import buku_tui.bukucli as mod

    data_home = tmp_path / "data"
    data_home.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    browser_log = tmp_path / "browser.log"
    browser = fakebin / "fakebrowser"
    browser.write_text(f'#!/bin/sh\necho "$1" >> "{browser_log}"\n')
    browser.chmod(0o755)
    env = {
        **os.environ,
        "XDG_DATA_HOME": str(data_home),
        "BROWSER": str(browser),
        "PATH": f"{fakebin}:{os.environ.get('PATH', '')}",
    }

    real_run = subprocess.run

    def run_with_env(argv, **kwargs):
        kwargs["env"] = env
        return real_run(argv, **kwargs)

    monkeypatch.setattr(mod.subprocess, "run", run_with_env)

    def cli(*args):
        return subprocess.run(
            [buku, "--nostdin", *args],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    return {"cli": cli, "client": BukuCli(buku), "browser_log": browser_log}


def test_list_all_against_real_buku(buku_env):
    buku_env["cli"]("-a", "https://github.com/bananmellan/buku-tui", "git,tui")
    buku_env["cli"]("-a", "https://news.ycombinator.com", "news,hn")

    refs, raw_count = buku_env["client"].list_all()
    assert raw_count == 2
    by_url = {r.url: r for r in refs}
    gh = by_url["https://github.com/bananmellan/buku-tui"]
    assert gh.title  # buku fetches a title
    assert set(gh.tags) == {"git", "tui"}
    assert gh.index >= 1


def test_list_all_empty_database(buku_env):
    refs, raw_count = buku_env["client"].list_all()
    assert refs == []
    assert raw_count == 0


def test_open_launches_browser_with_url(buku_env):
    buku_env["cli"]("-a", "https://example.com/some/page", "test")
    refs, _ = buku_env["client"].list_all()
    assert len(refs) == 1

    buku_env["client"].open(refs[0])

    deadline = time.time() + 5
    while time.time() < deadline and not buku_env["browser_log"].exists():
        time.sleep(0.1)
    assert buku_env["browser_log"].read_text().strip() == "https://example.com/some/page"


def test_open_bad_index_raises(buku_env):
    buku_env["cli"]("-a", "https://example.com", "test")
    with pytest.raises(BukuCliError):
        buku_env["client"].open(BookmarkRef(index=99, url="https://nope.example"))


# ============================================================ CRUD integration


def test_add_bookmark_against_real_buku(buku_env):
    from buku_tui.bukucli import BukuCli

    client = buku_env["client"]
    idx = client.add("https://integration-test.example.com", "Integration Test", ["test", "integration"], "A test bookmark")
    assert idx >= 1

    refs, _ = client.list_all()
    by_url = {r.url: r for r in refs}
    assert "https://integration-test.example.com" in by_url
    bm = by_url["https://integration-test.example.com"]
    assert bm.title == "Integration Test"
    assert set(bm.tags) == {"test", "integration"}
    assert bm.description == "A test bookmark"


def test_update_bookmark_against_real_buku(buku_env):
    buku_env["cli"]("-a", "https://update-test.example.com", "oldtag", "--title", "Old Title")
    refs, _ = buku_env["client"].list_all()
    assert len(refs) == 1
    idx = refs[0].index

    buku_env["client"].update(idx, "https://updated.example.com", "New Title", ["newtag"], "New desc")

    refs, _ = buku_env["client"].list_all()
    assert len(refs) == 1
    bm = refs[0]
    assert bm.url == "https://updated.example.com"
    assert bm.title == "New Title"
    assert set(bm.tags) == {"newtag"}
    assert bm.description == "New desc"


def test_update_clear_fields_against_real_buku(buku_env):
    buku_env["cli"]("-a", "https://clear-test.example.com", "tag1,tag2", "--title", "Has Title", "-c", "Has desc")
    refs, _ = buku_env["client"].list_all()
    idx = refs[0].index

    # Clear title, tags, and description
    buku_env["client"].update(idx, "https://clear-test.example.com", "", [], "")

    refs, _ = buku_env["client"].list_all()
    bm = refs[0]
    assert bm.title == ""
    assert bm.tags == ()
    assert bm.description == ""


def test_delete_bookmark_against_real_buku(buku_env):
    buku_env["cli"]("-a", "https://delete-test.example.com", "--title", "To Delete")
    refs, _ = buku_env["client"].list_all()
    assert len(refs) == 1
    idx = refs[0].index

    buku_env["client"].delete(idx)

    refs, _ = buku_env["client"].list_all()
    assert len(refs) == 0


def test_full_crud_against_real_buku(buku_env):
    client = buku_env["client"]

    # Add
    idx = client.add("https://crud.example.com", "CRUD", ["test"], "desc")
    refs, _ = client.list_all()
    assert len(refs) == 1
    assert refs[0].index == idx

    # Update
    client.update(idx, "https://crud2.example.com", "CRUD2", ["test2"], "desc2")
    refs, _ = client.list_all()
    assert refs[0].url == "https://crud2.example.com"
    assert refs[0].title == "CRUD2"

    # Delete
    client.delete(idx)
    refs, _ = client.list_all()
    assert len(refs) == 0

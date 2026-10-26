"""Tests for clipboard reading and URL extraction."""

import bookmark_tui.clipboard as clip
from bookmark_tui.clipboard import extract_url, read_clipboard


# ------------------------------------------------------------ extract_url


def test_extract_url_http():
    assert extract_url("https://example.com/page?q=1") == "https://example.com/page?q=1"
    assert extract_url("http://example.com") == "http://example.com"


def test_extract_url_schemeless():
    assert extract_url("example.com") == "https://example.com"
    assert extract_url("example.com/some/page") == "https://example.com/some/page"
    assert extract_url("sub.example.co.uk") == "https://sub.example.co.uk"


def test_extract_url_rejects_non_urls():
    assert extract_url("") == ""
    assert extract_url("   ") == ""
    assert extract_url("just some words") == ""
    assert extract_url("not a url .com") == ""
    assert extract_url("/local/file/path") == ""
    assert extract_url("file:///etc/passwd") == ""
    assert extract_url("ftp://example.com") == ""
    assert extract_url("localhost") == ""  # no dot -> not a host


def test_extract_url_uses_first_line_only():
    assert extract_url("https://example.com\nhttps://other.com") == "https://example.com"
    assert extract_url("some prose\nhttps://example.com") == ""


def test_extract_url_trims_whitespace():
    assert extract_url("  https://example.com  \n") == "https://example.com"


# ------------------------------------------------------------ read_clipboard


def test_read_clipboard_env_override(monkeypatch):
    monkeypatch.setenv("BOOKMARK_TUI_CLIPBOARD_CMD", "echo https://from-env.example.com")
    assert read_clipboard() == "https://from-env.example.com\n"


def test_read_clipboard_no_tool_returns_empty(monkeypatch):
    monkeypatch.delenv("BOOKMARK_TUI_CLIPBOARD_CMD", raising=False)
    monkeypatch.setattr(clip.shutil, "which", lambda _: None)
    monkeypatch.setattr(clip.sys, "platform", "linux")
    monkeypatch.delenv("PREFIX", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    assert read_clipboard() == ""


def test_read_clipboard_termux(monkeypatch):
    monkeypatch.delenv("BOOKMARK_TUI_CLIPBOARD_CMD", raising=False)
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    calls = []

    def fake_run(argv, shell=False, **kwargs):
        calls.append((argv, shell))
        class P:
            returncode = 0
            stdout = b"https://termux.example.com\n"
        return P()

    monkeypatch.setattr(clip.subprocess, "run", fake_run)
    assert read_clipboard() == "https://termux.example.com\n"
    assert calls and "termux-clipboard-get" in calls[0][0]


def test_read_clipboard_tool_failure_returns_empty(monkeypatch):
    monkeypatch.delenv("BOOKMARK_TUI_CLIPBOARD_CMD", raising=False)
    monkeypatch.setattr(clip.sys, "platform", "linux")
    monkeypatch.delenv("PREFIX", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setattr(clip.shutil, "which", lambda name: "/usr/bin/" + name)

    def fake_run(argv, shell=False, **kwargs):
        raise OSError("no clipboard")

    monkeypatch.setattr(clip.subprocess, "run", fake_run)
    assert read_clipboard() == ""

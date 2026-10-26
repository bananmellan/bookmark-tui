"""Tests for the web title fetcher (no real network: urlopen is faked)."""

import gzip
import io

import bookmark_tui.webfetch as wf
from bookmark_tui.webfetch import fetch_title


class FakeHeaders:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class FakeResponse:
    def __init__(self, body, headers=None):
        self._body = body
        self.headers = FakeHeaders(headers or {})

    def read(self, n=-1):
        return self._body[:n] if n and n > 0 else self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def patch_urlopen(monkeypatch, body, headers=None, exc=None):
    def fake_urlopen(req, timeout=None):
        if exc:
            raise exc
        return FakeResponse(body, headers)
    monkeypatch.setattr(wf, "urlopen", fake_urlopen)


def test_fetch_title_simple(monkeypatch):
    patch_urlopen(monkeypatch, b"<html><head><title>My Page</title></head></html>",
                  {"Content-Type": "text/html; charset=utf-8"})
    assert fetch_title("https://example.com") == "My Page"


def test_fetch_title_strips_whitespace(monkeypatch):
    patch_urlopen(monkeypatch, b"<title>\n  Spaced   Out\nTitle\t</title>")
    assert fetch_title("https://example.com") == "Spaced Out Title"


def test_fetch_title_case_insensitive_tag(monkeypatch):
    patch_urlopen(monkeypatch, b"<TITLE>Upper</TITLE>")
    assert fetch_title("https://example.com") == "Upper"


def test_fetch_title_no_title(monkeypatch):
    patch_urlopen(monkeypatch, b"<html><body>no title here</body></html>")
    assert fetch_title("https://example.com") is None


def test_fetch_title_empty_title(monkeypatch):
    patch_urlopen(monkeypatch, b"<title>   </title>")
    assert fetch_title("https://example.com") is None


def test_fetch_title_non_html_rejected(monkeypatch):
    patch_urlopen(monkeypatch, b"<title>x</title>", {"Content-Type": "image/png"})
    assert fetch_title("https://example.com") is None


def test_fetch_title_gzip(monkeypatch):
    body = gzip.compress(b"<title>Gzipped</title>")
    patch_urlopen(monkeypatch, body, {"Content-Type": "text/html", "Content-Encoding": "gzip"})
    assert fetch_title("https://example.com") == "Gzipped"


def test_fetch_title_network_error(monkeypatch):
    patch_urlopen(monkeypatch, b"", exc=OSError("connection refused"))
    assert fetch_title("https://example.com") is None


def test_fetch_title_timeout(monkeypatch):
    patch_urlopen(monkeypatch, b"", exc=TimeoutError("timed out"))
    assert fetch_title("https://example.com") is None


def test_fetch_title_rejects_non_http(monkeypatch):
    called = []

    def fake_urlopen(req, timeout=None):
        called.append(req)
        return FakeResponse(b"<title>x</title>")

    monkeypatch.setattr(wf, "urlopen", fake_urlopen)
    assert fetch_title("ftp://example.com") is None
    assert fetch_title("file:///etc/passwd") is None
    assert not called


def test_fetch_title_latin1_charset_from_header(monkeypatch):
    body = "<title>Caf\xe9</title>".encode("latin-1")
    patch_urlopen(monkeypatch, body, {"Content-Type": "text/html; charset=iso-8859-1"})
    assert fetch_title("https://example.com") == "Caf\u00e9"


def test_fetch_title_latin1_charset_from_meta(monkeypatch):
    body = (
        '<html><head><meta charset="iso-8859-1"><title>Caf\xe9</title></head></html>'
    ).encode("latin-1")
    patch_urlopen(monkeypatch, body, {"Content-Type": "text/html"})
    assert fetch_title("https://example.com") == "Caf\u00e9"

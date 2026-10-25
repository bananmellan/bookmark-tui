import os

from buku_tui.config import Config


def test_defaults():
    config = Config.from_env({"XDG_CACHE_HOME": "/xdg/cache"})
    assert config.buku_bin == "buku"
    assert config.cache_dir == "/xdg/cache/buku-tui"
    assert config.cache_ttl == 600
    assert config.debug is False
    assert config.verbose is False


def test_env_overrides():
    env = {
        "BUKU_TUI_BUKU": "/opt/buku",
        "BUKU_TUI_CACHE_DIR": "/tmp/my-cache",
        "BUKU_TUI_CACHE_TTL": "30",
        "BUKU_TUI_DEBUG": "1",
        "BUKU_TUI_VERBOSE": "1",
    }
    config = Config.from_env(env)
    assert config.buku_bin == "/opt/buku"
    assert config.cache_dir == "/tmp/my-cache"
    assert config.cache_ttl == 30
    assert config.debug is True
    assert config.verbose is True


def test_cache_dir_default_uses_xdg_cache_home(monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", "/xdg")
    assert Config.from_env().cache_dir == "/xdg/buku-tui"
    monkeypatch.delenv("XDG_CACHE_HOME")
    home = os.path.expanduser("~")
    assert Config.from_env().cache_dir == os.path.join(home, ".cache", "buku-tui")

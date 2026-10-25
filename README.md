# buku-tui

A fast, rofi-like **terminal UI** for [buku](https://github.com/jarun/buku)
bookmarks with full editing. No GUI toolkit — just run it from a terminal.

## Features

- Launching `buku-tui` opens a full-screen terminal search over **all
  bookmarks**. **No items are shown until you type at least one
  character** in the search field — the list appears as you type.
  **Search is live**: the list filters as you type, matching on title,
  url, tags and description (substring first, then fuzzy subsequence
  for tokens of 3+ characters). Non-ASCII input (å, ä, ö, …) works.
- Each bookmark renders as a **three-line block** so everything fits:
  the **title** on the first line, the **url** on the second, and the
  **tags** on the third (url and tags indented). Lines are colored
  when the terminal supports colors.
- **Enter** opens the selected bookmark's URL in the browser and quits
  (rofi-style: one selection ends the run). **Ctrl+o** opens the
  **detail view** showing all fields: URL, title, tags, description
  and index.
- **Full editing** within the interface:
  - **Add**: `Ctrl+a` or `Tab` opens a blank edit form. Fill in URL,
    title, tags and description. Save with `Enter` on the last field
    or `Ctrl+s`.
  - **Edit**: press `e` in the detail view to edit any bookmark's
    fields. Navigate between fields with `↑`/`↓` or `Tab`/`Enter`.
    Move the cursor with `←`/`→`, `Home`/`End`. Delete with
    `Backspace`. Save with `Enter` on the last field or `Ctrl+s`.
    Cancel with `Esc`.
  - **Delete**: press `d` in the detail view, then confirm with `y` or
    `Enter`.
- **Open URL**: press `Enter` in the list or detail view to open the
  bookmark's URL in the browser and quit (like rofi, one selection ends
  the run).
- Bookmarks are listed from a local cache
  (`$XDG_CACHE_HOME/buku-tui/bookmarks.v1.json`) containing only
  **index, title, url, tags and description**. Startup is fast: the
  list renders straight from the cache; when the cache is older than
  `BUKU_TUI_CACHE_TTL` seconds (default 600) a background rebuild is
  spawned without blocking the UI. The cache is invalidated after
  every add/edit/delete so the list is always current.
- If the clipboard contains an `http(s)://` URL or a bare hostname
  (`wl-paste`, `xclip` or `xsel`), bookmarks whose url contains the
  clipboard hostname (fuzzy: path, query, trailing slashes and case are
  ignored) are surfaced: matches are listed best-first with the hostname
  prefilled as the search query, the rest of the list below them. URL
  matching only ever reads the cache, and runs on every launch while the
  clipboard holds a URL. Match ranking: exact host equality first, then
  subdomain, then host-contains; ties break toward titles that name the
  host (including camelCase initials, so "NextCloud" ranks for
  `nc.honung.org`).
- `buku` is always invoked with `--nostdin`, so a locked (encrypted)
  database or an interrupted edit fails fast with a message instead of
  blocking the TUI on a prompt.

## Requirements

- Python >= 3.10 (standard library only — curses ships with CPython)
- `buku`
- `wl-copy`/`wl-paste`, `xclip` or `xsel` for clipboard integration
  (optional — without one, the clipboard URL matching at launch is
  skipped)
- A terminal with curses support

## Install

```sh
git clone https://github.com/bananmellan/buku-tui
cd buku-tui
pip install .            # or: pipx install .
```

Or run from the checkout:

```sh
./bin/buku-tui
```

Bind `buku-tui` (or `bin/buku-tui`) to a key in your window manager or
shell.

## Usage

### List view

- Type to search bookmarks (matches on title, url, tags and description;
  substring first, then fuzzy subsequence for tokens of 3+ characters).
  The list only appears once the search field has at least one
  character. Bookmarks show as three-line blocks: title, url, tags.
- `↑`/`↓` (or `PgUp`/`PgDn`, `Home`/`End`) move the selection.
  Emacs-style binds also work: `Ctrl+n`/`Ctrl+p` move down/up.
- `Enter` opens the selected bookmark's URL in the browser and quits
  (rofi-style: one selection ends the run).
- `Ctrl+o` opens the selected bookmark's **detail view**.
- `Ctrl+a` or `Tab` opens the **add** form.
- `Esc` (or `Ctrl+l`) first clears the search query, then quits.
- `Ctrl+r` forces a synchronous cache rebuild. `Ctrl-c` quits immediately.
- When the clipboard holds a URL, the matching bookmarks are listed with
  the host prefilled as the query (the prefilled host counts as search
  input, so matches show immediately). Host-like queries match precisely
  (substring only — no fuzzy subsequence), so unrelated bookmarks never
  appear; once you edit the query past the host, normal fuzzy matching
  resumes.

### Detail view

- `Enter` opens the URL in the browser and quits.
- `e` opens the **edit** form for this bookmark.
- `d` opens the **delete** confirmation.
- `Ctrl+a` opens the **add** form.
- `Esc` (or `Ctrl+l`) goes back to the list.

### Edit / Add form

- `↑`/`↓` or `Tab` moves between fields (URL → Title → Tags →
  Description).
- `Enter` on the last field (Description) saves. `Ctrl+s` saves from
  any field.
- `←`/`→`, `Home`/`End` move the cursor within a field.
- `Backspace` deletes the character before the cursor.
- `Esc` cancels and returns to the list.
- Tags are comma-separated (e.g. `python, tutorial, cli`).

### Delete confirmation

- `y` or `Enter` confirms deletion.
- `n` or `Esc` cancels.
- `←`/`→` toggles between Yes and No.

### Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `BUKU_TUI_BUKU` | `buku` | buku executable |
| `BUKU_TUI_CACHE_DIR` | `$XDG_CACHE_HOME/buku-tui` | cache/state directory |
| `BUKU_TUI_CACHE_TTL` | `600` | cache freshness in seconds |
| `BUKU_TUI_DEBUG` | unset | set to `1` to log to `debug.log` |
| `BUKU_TUI_VERBOSE` | unset | set to `1` (or pass `--verbose`) to log decision points (clipboard content, extracted host, cache stats, match count) to stderr and `debug.log` |

Debugging: run `buku-tui --verbose` (or `BUKU_TUI_VERBOSE=1 buku-tui`)
with a URL in the clipboard and watch stderr — or `tail -f
$XDG_CACHE_HOME/buku-tui/debug.log` — to see the clipboard text, the
extracted host, how many cached bookmarks there are, and how many
matched.

## Development

```sh
python3 -m pytest
```

Layout:

```
bin/buku-tui             launcher for running from a checkout
src/buku_tui/
  cli.py                 entry point: arg parsing, --rebuild, tty check
  app.py                 UI-agnostic controller (list/detail/edit/confirm screens + key handling)
  tui.py                 curses rendering (list, detail, edit, confirm) and key translation
  search.py              live filtering (token substring/subsequence ranking)
  bukucli.py             buku subprocess wrapper: list, open, add, update, delete
  cache.py               metadata cache (atomic, 0600, TTL, background refresh)
  clipboard.py           wl-clipboard/xclip/xsel abstraction, URL host extraction
  config.py              environment-based configuration
  models.py              BookmarkRef dataclass
tests/                   pytest suite (app controller, bukucli, search, tui, pty smoke, integration)
```

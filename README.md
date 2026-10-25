# bookmark-tui

A fast, rofi-like **terminal UI** for managing bookmarks. No external
dependencies — just Python 3.10+ and curses. Import from buku, Firefox,
or Chrome, then search, edit, and open bookmarks from your terminal.

## Features

- **Centered search bar**: the prompt stays centered as you type.
  Search is live — the list filters as you type, matching on title,
  url, and category (substring first, then fuzzy subsequence for
  tokens of 3+ characters). Non-ASCII input (å, ä, ö, …) works.
- **Enter opens the URL** in your browser and quits (rofi-style: one
  selection ends the run). **Ctrl+o** opens the detail view.
- **Full editing** within the interface:
  - **Add**: `Ctrl+a` or `Tab` opens a blank form. Fill in URL, title,
    and category. Save with `Ctrl+s` or `Tab` on the last field.
  - **Edit**: press `e` in the detail view to edit any bookmark.
    Navigate fields with `↑`/`↓`/`Tab`. Move the cursor with
    `←`/`→`, `Home`/`End`. Delete with `Backspace`. Save with `Ctrl+s`
    or `Tab` on the last field. Cancel with `Esc`.
  - **Delete**: press `d` in the detail view, then confirm with `y`
    or `Enter`.
- **Search persists**: if you search, open a detail, edit, or delete,
  going back returns to the list with your search term intact.
- After saving an edit or add, you return to the **item overview**
  (the filtered list), not the start screen.
- **Import** from buku (SQLite `.db` or JSON export), Firefox
  (bookmarks JSON backup), or Chrome/Chromium/Edge (bookmarks JSON).
  Browser folder hierarchies become categories:
  `Bookmarks Bar > Food > Recipes` → category `food/recipes`.
- Data is stored as a simple JSON file
  (`$XDG_DATA_HOME/bookmark-tui/bookmarks.json`) with only **id, url,
  title, and category**. Writes are atomic (temp file + rename).

## Requirements

- Python >= 3.10 (standard library only — curses ships with CPython)
- A terminal with curses support
- `xdg-open` (Linux), `open` (macOS), or `start` (Windows) for opening URLs

## Install

```sh
git clone https://github.com/bananmellan/bookmark-tui
cd bookmark-tui
pip install .            # or: pipx install .
```

Or run from the checkout:

```sh
./bin/bookmark-tui
```

Bind `bookmark-tui` to a key in your window manager or shell.

## Usage

### Importing bookmarks

```sh
# Import from a buku database
bookmark-tui --import-file ~/.local/share/buku/bookmarks.db

# Import from a Firefox bookmarks backup
bookmark-tui --import-file ~/bookmarks.json

# Import from Chrome/Chromium/Edge
bookmark-tui --import-file ~/.config/google-chrome/Default/Bookmarks

# Import only, don't launch the TUI
bookmark-tui --import-file bookmarks.db --no-tui
```

Import **replaces** all existing bookmarks. The TUI launches
automatically after import (unless `--no-tui` is given).

### List view

- Type to search (matches on title, url, and category). The list only
  appears once the search field has at least one character.
- The search bar is **centered** — it stays in the middle as you type.
- `↑`/`↓` (or `PgUp`/`PgDn`, `Home`/`End`) move the selection.
  Emacs-style: `Ctrl+n`/`Ctrl+p` move down/up.
- `Enter` opens the selected bookmark's URL in the browser and quits.
- `Ctrl+o` opens the **detail view**.
- `Ctrl+a` or `Tab` opens the **add** form.
- `Esc` first clears the search query, then quits.
- `Ctrl+c` quits immediately.

### Detail view

- `Enter` opens the URL in the browser and quits.
- `e` opens the **edit** form.
- `d` opens the **delete** confirmation.
- `Ctrl+a` opens the **add** form.
- `Esc` goes back to the list (search term preserved).

### Edit / Add form

- `↑`/`↓` or `Tab` moves between fields (URL → Title → Category).
- `Ctrl+s` or `Tab` on the last field saves.
- `←`/`→`, `Home`/`End` move the cursor within a field.
- `Backspace` deletes the character before the cursor.
- `Esc` cancels and returns to the list.

### Delete confirmation

- `y` or `Enter` confirms deletion.
- `n` or `Esc` cancels.
- `←`/`→` toggles between Yes and No.

### Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `XDG_DATA_HOME` | `~/.local/share` | Base directory for the bookmark store |
| `--store PATH` | `$XDG_DATA_HOME/bookmark-tui/bookmarks.json` | Custom store file path |

## Data model

Each bookmark has four fields:

| Field | Description |
| --- | --- |
| `id` | Stable integer identity |
| `url` | The bookmark URL (required) |
| `title` | Display title (optional) |
| `category` | Folder path, e.g. `food/recipes/vegetarian` (optional) |

## Development

```sh
python3 -m pytest
```

Layout:

```
bin/bookmark-tui           launcher for running from a checkout
src/bookmark_tui/
  cli.py                   entry point: arg parsing, --import, TUI launch
  app.py                   UI-agnostic controller (list/detail/edit/confirm + key handling)
  tui.py                   curses rendering (centered search bar) and key translation
  search.py                live filtering (token substring/subsequence ranking)
  storage.py               JSON file storage (atomic writes, CRUD)
  import_bookmarks.py      import from buku .db, Firefox/Chrome .json
  models.py                Bookmark dataclass
tests/                     pytest suite (models, storage, search, import, app, tui, cli, pty)
```

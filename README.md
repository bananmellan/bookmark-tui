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
    If the clipboard holds a URL, the add form first asks whether to
    prefill it and fetch the page title — **Yes** fills in the URL and
    the fetched `<title>`, **No**/**Esc** fills in just the URL.
  - **Edit**: press `e` in the detail view to edit any bookmark.
    Navigate fields with `↑`/`↓`/`Tab`. Move the cursor with
    `←`/`→`, `Home`/`End`. Delete with `Backspace`. Save with `Ctrl+s`
    or `Tab` on the last field. Cancel with `Esc`.
  - **Delete**: press `d` in the detail view, then confirm with `y`
    or `Enter`.
- **Folder view**: press `Ctrl+f` in the list to browse categories as
  folders. Each folder row shows its bookmark count (including
  subfolders); bookmarks directly in the current folder are listed
  below the folders. `Enter` descends into a folder (or opens a
  bookmark), `Esc` goes up one level (or back to the list), `Ctrl+f`
  toggles back to the search list. Press `d` on a folder to delete it —
  this deletes **all bookmarks in that folder and every subfolder**
  (e.g. deleting `food/recipes` also deletes `food/recipes/vegetarian`),
  after a confirmation that shows how many bookmarks will be removed.
  Press `r` on a folder to **rename** it (subfolders move with it).
  Mark bookmarks with `Space` (or `A` to mark/unmark all in view), then
  `M` to **move** the marked bookmarks to another folder (empty target
  = uncategorized). Press `c` on a bookmark to **duplicate** it.
- **Duplicate**: press `c` in the detail view (or on a bookmark row in
  the folder view) to open the add form pre-filled with that
  bookmark's URL, title, and category. Saving creates a new bookmark.
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
- `xdg-open` (Linux), `open` (macOS), `start` (Windows), or
  `termux-open-url` (Termux/Android) for opening URLs

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
- `Ctrl+f` switches to the **folder view**.
- `Ctrl+a` or `Tab` opens the **add** form.
- `Esc` first clears the search query, then quits.
- `Ctrl+c` quits immediately.

### Folder view

Categories are browsed as folders, one level at a time. Each folder row
shows the folder name and how many bookmarks it contains (including
subfolders). Bookmarks directly in the current folder are listed below
the folders (at the root, uncategorized bookmarks show up too).

- `↑`/`↓` (or `PgUp`/`PgDn`, `Home`/`End`, `Ctrl+n`/`Ctrl+p`) move the
  selection.
- `Enter` descends into the selected folder, or opens the selected
  bookmark's URL and quits.
- `Ctrl+o` opens the **detail view** for the selected bookmark.
- `d` on a folder deletes it: **all bookmarks in it and in every
  subfolder** are deleted, after a confirmation showing the count.
  `d` on a bookmark deletes just that bookmark.
- `r` on a folder **renames** it — the folder and all its subfolders
  move to the new name (refused if the target already exists).
- `Space` marks/unmarks the selected bookmark; `A` marks or unmarks
  all bookmarks in the current view. `M` **moves** the marked
  bookmarks to a folder you type (empty target = uncategorized).
- `c` on a bookmark **duplicates** it: the add form opens pre-filled
  with its URL, title, and category.
- `Ctrl+a` or `Tab` opens the **add** form.
- `Ctrl+f` switches back to the search list.
- `Esc` goes up one level (or back to the search list at the top).

### Detail view

- `Enter` opens the URL in the browser and quits.
- `e` opens the **edit** form.
- `d` opens the **delete** confirmation.
- `c` **duplicates** the bookmark: the add form opens pre-filled with
  its URL, title, and category; saving creates a new bookmark.
- `Ctrl+a` opens the **add** form.
- `Esc` goes back to the list (search term preserved).

### Clipboard autofill prompt (add only)

When you open the add form (`Ctrl+a`/`Tab`) and the clipboard contains
a URL, a prompt asks whether to prefill it and fetch the page title:

- `y` or `Enter` — prefill the URL and fetch the page's `<title>`
  (fetched with a short timeout; on failure the title is left empty).
- `n` or `Esc` — prefill just the URL, no fetch.
- `←`/`→` toggles between Yes and No.

Scheme-less clipboard content like `example.com/page` is normalized to
`https://example.com/page`. Editing or duplicating a bookmark never
triggers this prompt.

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
| `BOOKMARK_TUI_CLIPBOARD_CMD` | _(auto-detect)_ | Shell command whose stdout is used as the clipboard content (overrides `termux-clipboard-get` / `pbpaste` / `wl-paste` / `xclip` / `xsel`) |

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

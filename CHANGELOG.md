# Changelog

## 0.2.0

- Hovering a result row shows its full path, in the GTK window and on the browser page.
- Settings in the window and on the page (the gear button beside the search box, Ctrl+, in the window): add or remove indexed folders and exclusions (a chosen folder or a name rule), index hidden entries, restore defaults. Problems (a folder that does not exist, one on a network mount, one inside another, an exclusion outside every indexed folder) are listed before saving, with Save anyway; an empty folder list cannot be saved. Saving updates the index at once: added exclusions are dropped from the index without a rescan, other changes rescan in the background.
- Similar versions in a result are marked: files whose names differ only by copy marks, a leading number, a date, a version number or a draft word (and by case, full- or half-width forms, spaces and brackets) form a group; the newest by modification time is tagged Newest and the others Newer exists. Hovering adds the group size and the newest path; the context menu offers Go to the newest version. Results above 100,000 are not grouped (the status bar says so); large ones are grouped in the background.
- Open containing folder is now called Locate (Ctrl+Enter); every result row ends with a locate button. When the file manager cannot select the item, the folder is opened and the status bar says so.
- Copy file (window only): the file or folder itself goes on the clipboard (x-special/gnome-copied-files, text/uri-list and the path as text), so a file manager pastes the item. Ctrl+C now copies the file and Ctrl+Shift+C the path; the browser page keeps Ctrl+C for the path.
- The context menu reads: locate, open, copy file, copy path, then go to the newest version, exclude, rescan.
- Window: rows and margins are more compact (fonts and colours still follow the system); while another program has the focus the window is 70 % opaque, given a desktop compositor (the context menu and the window's own dialogs do not count). Column widths, window size, maximised state, position (not under Wayland, and only when still on a monitor) and the sort are remembered in `~/.config/find-fast/ui-state.json` (mode 600); bad values fall back to defaults. The browser page is unchanged.
- Window: with an empty search box only the search row shows; typing unfolds the result list to the remembered height (also with no match, which says No matches), and clearing it folds the list again. A maximised window does not fold. While folded, the right end of the search box shows the index state (entries or indexing progress) and, for a few seconds, messages; the full state with the version is its tooltip. Esc clears and folds, a second Esc closes.
- Right-click a result: Exclude this folder (folder rows) or Exclude the containing folder (file rows), after a confirmation naming the folder.

## 0.1.0

First version.

- Whole-disk file-name index of the home folder and local disks under `/media` and `/mnt`, skipping network mounts, pseudo file systems, hidden names and configurable exclusions (`~/.config/find-fast/config.json`). Kept in a compact cache (`~/.cache/find-fast/index.bin`, mode 600); later starts relist only changed folders.
- Query language: several words, `a|b`, `!a`, wildcards on the whole name, `ext:`, `path:` (or any word with `/`), `regex:`.
- GTK3 window through the system's python3-gi: a virtual result list without a row limit, four sortable columns, keyboard control, context menu, drag and drop, one window per user session, inotify live updates with periodic rescans when the watch limit is reached.
- Browser page when python3-gi is missing (or with `--web`): a local server on a random port of 127.0.0.1 with a per-run token, search, sort, open, open containing folder, copy path; exits a few seconds after its last page closes.
- Command line: `find_fast.py QUERY` with `--sort`, `--asc`, `--limit`, `--count`, `-0`, `--update`, `--rebuild`, `--status`.
- `install.sh` installs into `~/.local` with a `find-fast` command and a menu entry; `--uninstall` removes them.
- Interface in English and Chinese, following `LANG`.

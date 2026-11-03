# Changelog

## 0.4.0

- The launcher is renamed from `双击运行.desktop` to `秒搜文件.desktop`, matching its Name, so it can be sent to the desktop next to other tools' launchers without a name clash. Its content and the `%k` + `readlink -f` lookup are unchanged; the not-found message and the page's closing notice name the new file. A link placed on the desktop earlier stops working and has to be sent to the desktop again from the tool folder. The release zip carries the new file. walkwithedi/find-fast#18.

## 0.3.1

- The READMEs end with a Feedback section giving the maintainer's feedback address. The sensitive-data scanner allows that one full address (PUBLIC_ADDRESSES) and still reports every other e-mail address. walkwithedi/edi-lab#206.

## 0.3.0

- Plain search words match the whole path: each word may be in the name or in the name of any folder above it, so `atlas 28` finds `~/Documents/Atlas/report 28.pdf`. `!word` leaves out entries with the word anywhere in their path; in `a|b` each alternative follows its own kind. Wildcards, `ext:`, `regex:` and the regular-expression mode still look at names only; `path:` and words with `/` are unchanged. Words found in no folder path keep the name-only search, and the folder matches of recent words are kept while typing.
- Settings: Search words also match the path (`match_path` in `config.json`, on by default) turns this off; changing it searches again without a rescan. In the window, on the browser page and on the command line.
- Result columns can be reordered: drag a header (window and browser page; the locate column stays last), or use Move up, Move down and Default order under Column order in Settings. The window keeps the order in `ui-state.json` (`order`), the page in that browser; a bad order falls back to name, path, size, modified.
- Default global show-or-hide shortcut Ctrl+Alt+Space. `install.sh` writes it (new `--default-hotkey`), so it works before the tool was ever started; a tool run from an unpacked folder writes it on its first start. It is written once, only when no shortcut was ever set (`toggle_default_done` in `config.json`), and never over a desktop shortcut on the same keys; otherwise the installer output and the status bar or status line say why. `install.sh` also points a shortcut set earlier at the installed command. Restore defaults in Settings sets Ctrl+Alt+Space again.
- A start-up notice stays in the window's status bar until typing or 30 seconds.

## 0.2.0

- Hovering a result row shows its full path, in the GTK window and on the browser page.
- Settings in the window and on the page (the gear button beside the search box, Ctrl+, in the window): add or remove indexed folders and exclusions (a chosen folder or a name rule), index hidden entries, restore defaults. Problems (a folder that does not exist, one on a network mount, one inside another, an exclusion outside every indexed folder) are listed before saving, with Save anyway; an empty folder list cannot be saved. Saving updates the index at once: added exclusions are dropped from the index without a rescan, other changes rescan in the background.
- Similar versions in a result are marked: files whose names differ only by copy marks, a leading number, a date, a version number or a draft word (and by case, full- or half-width forms, spaces and brackets) form a group; the newest by modification time is tagged Newest and the others Newer exists. Hovering adds the group size and the newest path; the context menu offers Go to the newest version. Results above 100,000 are not grouped (the status bar says so); large ones are grouped in the background.
- Open containing folder is now called Locate (Ctrl+Enter); every result row ends with a locate button. When the file manager cannot select the item, the folder is opened and the status bar says so.
- Copy file (window only): the file or folder itself goes on the clipboard (x-special/gnome-copied-files, text/uri-list and the path as text), so a file manager pastes the item. Ctrl+C now copies the file and Ctrl+Shift+C the path; the browser page keeps Ctrl+C for the path.
- The context menu reads: locate, open, copy file, copy path, then go to the newest version, exclude, rescan.
- Window: rows and margins are more compact (fonts and colours still follow the system); while another program has the focus the window is 70 % opaque, given a desktop compositor (the context menu and the window's own dialogs do not count). Column widths, window size, maximised state, position (not under Wayland, and only when still on a monitor) and the sort are remembered in `~/.config/find-fast/ui-state.json` (mode 600); bad values fall back to defaults. The browser page is unchanged.
- Window: with an empty search box only the search row shows; typing unfolds the result list to the remembered height (also with no match, which says No matches), and clearing it folds the list again. A maximised window does not fold. While folded, the right end of the search box shows the index state (entries or indexing progress) and, for a few seconds, messages; the full state with the version is its tooltip. Esc clears and folds, a second Esc closes.
- Shortcuts in Settings: the window's shortcuts (locate, open the selected item, copy file, copy path, open settings, rescan, go to the search box) can be recorded, cleared and restored to defaults; arrows, Enter and Esc stay fixed, a shortcut needs Ctrl, Alt or Super or is a function key, and two actions on the same keys cannot be saved. They are kept in `config.json` under `keys` and apply at once. Rescan now has one key, F5 (Ctrl+R is no longer bound).
- Global show-or-hide shortcut: set in Settings, written into the desktop's custom shortcuts (UKUI or GNOME, through gsettings; only this tool's own entry is ever changed), with a warning when the desktop already uses the keys. It runs the new `--toggle`, which hides the window when it is in front and otherwise brings it forward with the search text selected. Elsewhere the command to bind by hand is shown. `--remove-hotkey`, also run by `install.sh --uninstall`, removes the entry.
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

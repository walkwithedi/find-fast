# Changelog

## 0.8.0

- Local data disks are indexed by default besides the folders in the settings: Settings → Indexed folders has Include all local data disks automatically (on by default, also for settings saved by earlier versions; `auto_mounts` in the settings file) and lists the disks found below it. A data disk is a mounted local disk file system (ext4, xfs, btrfs, ntfs, exfat, vfat and the like, and local FUSE ones) that is not the root partition, not a system folder (`/boot`, `/usr`, `/var`, `/opt`, `/snap`, `/tmp` and others; `/run/media` is allowed), not the home folder or a folder holding it, and not a second view of a disk already included. When the home folder lives on a data disk and is bound elsewhere (such as a data partition bound to `/home`), its copy on the disk is skipped so that files are not found twice. The mount table is watched while the tool runs: a disk mounted later is scanned, a removed one leaves the index. An exclusion inside a data disk is no longer reported as outside every indexed folder. Hidden entries stay off by default.
- Window: fading while another program has the focus is off by default; More → Translucent when not focused turns it on (remembered in the interface state as `fade`).

## 0.7.0

- Results: a row is the name over its folder (the home folder as `~`, a deep folder as `…/` and its last two levels), with the size over a short time at the right (just now, N min ago, N h ago, N days ago within a week, then the date; the full time is in the tooltip). Matches of the search words are marked in names and folders (`highlight`, `highlight_row`), worked out only for the rows shown; a word marked in the name is not marked again in the folder. Both the window and the browser page.
- A details panel beside the list shows the selected row (name, type, full path with a copy button, size, time, where it matched) with Open, Locate, Copy path and, in the window, Copy file; without a row it shows the index. It hides below 960 pixels in the window and 1080 on the page. The button row above the list and the locate button on every row are removed.
- A filter bar narrows a result by type (folders, documents, images, archives, code, audio/video, other) with counts over the whole result, and above 400 results by one of two suggested folders; neither searches again, so similar-version tags stay. Sorting moves into a menu at its right end. Column headers, column widths and the Column order setting are removed; widths and order remembered by earlier versions are ignored. The page's `/api/search` takes `type`, `scope` and `sid` and returns `facets`, `scope_suggest` and, per row, `name_html`, `dir_html`, `dir_display`, `time_full` and `cat`; `/api/facets` is new.
- The status bar is the one place that counts results; a scan shows as a 2-pixel line under the search row. Empty states: a start hint with examples, no match (with Clear search, Show syntax, Clear the filter), and loading. A bad regular expression is explained under the search box and the last results stay.
- ? in an empty search box opens Shortcuts and syntax; clicking an example searches it. The context menu is grouped (open and copy; exclude and versions; rescan) and shows the keys; Exclude is unavailable, with the reason, on an indexed folder itself. In the search box the arrow and page keys move the selection, and the first result is selected.
- Settings come in four parts: Indexed folders, Exclusions, Search (default order, syntax, the window's shortcuts) and Upgrade; the page's Upgrade moved there and to the More menu.
- Window: the folded window is 90 pixels high instead of as short as the desktop allows, and More → Fold to a search box folds it by hand; Switch appearance picks the theme's dark or light variant. The page has its own light and dark colours, kept in the browser, and does not scroll sideways at any width.
- Counting types and building a filtered view use the index arrays: about 30 ms for a million results.

## 0.6.0

- Window: Enter, Locate, Copy file and Copy path pressed right after typing first finish the search the box was waiting to run, so they act on the new results and not the previous ones.
- Window: the list shortcuts (Locate, Open, Copy file, Copy path) also work in the search box, on the selected row or the first one; with text selected in the box, the copy keys copy that text.
- Window: Esc in an empty search box hides the window when a global show-or-hide shortcut is set (the index keeps updating) and closes it otherwise; the close button always quits.
- Window: the Menu key and Shift+F10 open the context menu below the selected row. F5 and Rescan say Rescan started, or A scan is running; try again later.
- Settings: problems found on saving or recording a shortcut show right above the buttons, outside the scrolled part. A long upgrade report scrolls inside its question. Before an upgrade or roll-back, unsaved changes in the dialog are asked about first (Continue anyway).
- A bad regular expression is explained in words with the character it was found at (an unbalanced parenthesis or bracket, a repeat with nothing before it, repeats one after another, a bad escape); other errors keep Python's text. Also on the command line and the browser page.
- Window: when no program is set to open a kind of file, the message says so and points to Open With in a file manager; other open failures no longer suggest checking the file still exists.
- Window: the Exclude question gives the number of entries that leave the index (`Index.count_under`).
- Similar versions with the same modification time: the later draft word is the newest (终稿, 定稿, 最终版, 最终稿, final; then 修订版, 修改版; then 三稿, 二稿, 初稿, draft; `DRAFT_RANKS`), then the shorter path. Also on the command line and the browser page.
- Window: the Newest and Newer exists tags are drawn in a faded text colour instead of an insensitive cell, so screen readers do not call them unavailable. When the window is too narrow for the search hint beside the folded state text, the box shows a short hint and the full one moves into the tooltip.
- walkwithedi/find-fast#23.

## 0.5.1

- The upgrade module copy is version 1.1: files unpacked or copied by an upgrade get 755 or 644 by whether the owner may run them, less the bits the process umask clears (as unzip and cp do), instead of those modes unchanged; with the usual umask 022 nothing differs. TOOL_UPGRADE_VERSION names 1.1 and the new SHA-256.

## 0.5.0

- Upgrade in place: Settings in the window has an Upgrade section (Upgrade from a zip…, Upgrade from an unpacked folder…, Roll back to previous version), and the browser page has Upgrade beside Quit. The check shows current version → new version, the CHANGELOG entries between the two, the files kept and any extra files, and calls out a downgrade or reinstall; the confirm button reads Upgrade to vX.Y.Z. While it runs the status bar (or the page) shows the stage and the search box stays usable; afterwards the window opens again on the new version, and the page reconnects to the service restarted on the same port and token. The old folder is kept as the hidden `.find-fast.上一版` next to it; Roll back swaps the two. The path does not change, so desktop links, the menu entry written by `install.sh` and the show-or-hide shortcut keep working without reinstalling.
- Command line: `find_fast.py --upgrade ZIP|DIR` (shows the check and asks; `--yes` skips the question) and `--rollback`.
- A release is refused, with the reason and the folder unchanged, when its top folder is not `find-fast`, its version cannot be read, a program is missing, an entry has `..`, an absolute path, a symbolic link or a device file, it unpacks to more than 200 MB or 5000 entries, or the folder above the tool folder is not writable; a failure part-way restores the folder. An uploaded zip is written only to the system temporary folder and removed afterwards; new endpoints check the token, Host and Origin.
- New files: `tool_upgrade.py`, an unchanged copy of the upgrade module (the version it came from is in `TOOL_UPGRADE_VERSION`; `scripts/check_repo.py` compares the copy with it and CI with the master copy), and `upgrade-keep.txt`, the files an upgrade carries over (empty: settings and the index live outside the folder). Both are in the release zip and copied by `install.sh`. walkwithedi/find-fast#19.

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

# find-fast: instant file-name search for the Linux desktop

[中文](README.zh-CN.md)

Type part of a name and every matching file under your home folder and local disks shows up as you type. It needs only Python 3 and the GTK3 bindings most Linux desktops already ship (python3-gi); without them it opens the same search in the browser.

- Nothing to install: the Python 3.8+ standard library plus the system's PyGObject. No pip, nothing to compile, no network access at run time.
- Fast: the index is kept on disk in a compact form, so the window is searchable about a second after it opens, and a background pass picks up what changed while it was closed. While the window is open, inotify keeps it current.
- No limit on results: the list draws only the rows on screen, so a million results scroll and sort.
- Searches names and paths only, never file contents.
- Interface in English or Chinese, following `LANG`.

## Files

| File | Role |
| --- | --- |
| `秒搜文件.desktop` | Double-click launcher, shown as 秒搜文件 ("find-fast"). |
| `install.sh` | Optional install into `~/.local`: a `find-fast` command and a menu entry. |
| `find_fast.py` | Entry point: without arguments it opens the window; with a query it prints matches. |
| `find_fast_core.py` | Index and search: scanning, cache, query language, inotify. |
| `find_fast_gtk.py` | The GTK3 window. |
| `find_fast_web.py`, `find_fast.html` | The browser page, used when python3-gi is missing. |
| `tool_upgrade.py`, `TOOL_UPGRADE_VERSION` | The upgrade module (in-place upgrade and roll-back), an unchanged copy of a shared master; `TOOL_UPGRADE_VERSION` names its version. |
| `upgrade-keep.txt` | Files an upgrade carries over, one relative path a line (empty: settings and the index live outside the folder). |
| `tests/`, `scripts/`, `docs/` | Development only: tests, checks, benchmark, specification (not in the release zip). |

## Requirements

- A Linux desktop (Ubuntu, Kylin and others), x86_64 or arm64.
- Python 3.8 or later.
- For the window: python3-gi and the GTK 3 runtime (`import gi` works; usually preinstalled on desktop systems). Without them the browser page is used and a notice says so.
- Optional: `xdg-open` (opening files), `gdbus` (the browser page selecting a file in the file manager), `zenity` or `notify-send` (notices when started without a terminal).

## Use

Download `find-fast-v<version>.zip` from Releases, unpack it and double-click `秒搜文件.desktop`, or run `python3 find_fast.py`. A link to the launcher can go on the desktop (right-click it in the file manager and send it to the desktop); a copy cannot, since it must find the program next to it. Since 0.4.0 the launcher is called `秒搜文件.desktop` instead of `双击运行.desktop`, so it no longer clashes with other tools' launchers on the desktop; a link placed on the desktop earlier stops working and has to be sent to the desktop again from the tool folder.

For a menu entry, run `bash install.sh` once. It copies the tool to `~/.local/share/find-fast`, creates the command `~/.local/bin/find-fast` and a menu entry, and writes the default show-or-hide shortcut Ctrl+Alt+Space (see Global hotkey); no root needed. `bash install.sh --uninstall` removes them and keeps the settings and the index.

The first start builds the index, with progress in the status bar; what has been scanned can be searched meanwhile. Later starts load the previous index and relist only folders that changed.

### Global hotkey

The default is Ctrl+Alt+Space. `install.sh` writes it, so it opens the window before the tool was ever started; when the tool runs from an unpacked folder without installing, the first start writes it. It is written only when no shortcut was ever set: one changed or cleared later is left alone. When the desktop already uses Ctrl+Alt+Space, the desktop is not recognised, or writing fails, nothing is written, and the installer output and the status bar (the status line on the browser page) say why; set one in Settings then.

Change it in the window under Settings → Shortcuts → Show or hide the window: click the button and press the keys. On saving it is written into the desktop's own custom shortcuts (Kylin UKUI or GNOME, through gsettings) and shows in the system settings; it runs `find-fast --toggle`, which hides the window when it is in front and otherwise brings it forward with the search text selected (starting it when it is not running). A hidden window keeps the index up to date; with this shortcut set, Esc on an empty search box hides the window too; the close button quits. A combination the desktop already uses is named first, with Save anyway. Clearing it, or `bash install.sh --uninstall`, removes only the entry this tool wrote.

Without `install.sh` the shortcut points at the unpacked folder (`python3 <tool folder>/find_fast.py --toggle`) and must be set again after the folder moves. On other desktops, or without gsettings, nothing is written: the settings show the command, with Copy command, to add by hand:

- GNOME (Ubuntu): Settings → Keyboard → View and Customise Shortcuts → Custom Shortcuts → add, with `/home/<user>/.local/bin/find-fast --toggle` as the command.
- Kylin (UKUI): Settings → Devices → Shortcuts → Custom Shortcuts → add, with the same command.

The window's own shortcuts are under the same Settings section: Locate, Open the selected item (Enter always opens), Copy file, Copy path, Open settings, Rescan and Go to the search box. Arrows, Enter and Esc stay fixed and cannot be recorded; a shortcut needs Ctrl, Alt or Super, or is F1 to F12; two actions on the same keys cannot be saved. Changes apply at once and do not rebuild the index; Restore defaults puts back the defaults below, and Ctrl+Alt+Space for show or hide.

### Query syntax

| Query | Matches |
| --- | --- |
| `report 2024` | paths containing all the words (any case): each word in the name or in the name of any folder above it |
| `pdf\|docx` | either word |
| `!draft` | not containing the word |
| `*.pdf`, `img_??.png` | wildcards, matched against the whole name |
| `ext:pdf;docx` | by extension |
| `path:project`, `docs/2024` | the whole path (a word with `/` matches the path) |
| `regex:^img_\d+` | a regular expression on the name, any case |
| `"annual report"` | a space inside quotes belongs to the word |

Folders appear in the results as well.

Plain words match the whole path: `atlas 28` finds `~/Documents/Atlas/report 28.pdf`, and `!draft` leaves out entries with draft anywhere in their path. The path includes the indexed folder itself (such as the home folder `/home/<user>`), so a word from those folder names matches everything under them. Wildcards, `ext:`, `regex:` and the regular-expression mode still look at the name only. To search names only, turn off Search words also match the path in Settings.

### Window

- Type to search; the first result is selected. In the search box ↑ ↓, Page Up and Page Down move the selection while the cursor stays in the box, so typing goes on; typing in the list continues in the box.
- Each result takes two lines: the name, and below it the folder it is in (the home folder written as `~`, and only the last two levels of a deep path, such as `…/Atlas/2026`). Where the search words match is marked with a warm yellow background; a word marked in the name is not marked again in the folder. At the right are the size (Folder for a folder) over the modification time: just now within a minute, N min ago, N h ago, N days ago within a week, then month-day, and year-month-day for other years; the full time is in the tooltip and the details.
- In a window at least 960 pixels wide, a details panel at the right shows the selected row's name, type, full path (selectable, with a copy button), size, modification time and where the words matched (name, path or both), with Open, Locate, Copy path and Copy file and their keys. Without results it shows the number of entries and folders and the update mode. A narrower window hides it; the context menu and the keys do the same.
- With results, a filter bar sits under the search box: filter by type (All, Folders, Documents, Images, Archives, Code, Audio/Video, Other), each with its count over the whole result; a second click goes back to All. A type with no rows cannot be chosen, and Other is left out when it has none. Above 400 results two folder suggestions narrow the list to that folder; a second click clears it. Filtering does not search again, and the similar-version tags stay. At the right end is the order: Newest first, Oldest first, Name A→Z, Name Z→A, Largest first, Smallest first, Path A→Z.
- Without results the list area says why and offers a way on: with an empty box, a start hint and three examples; with no match, the words searched, Clear search and Show syntax, plus Clear the filter when one is on; while the index loads, a loading state. A bad regular expression is explained under the search box and the last results stay.
- ? in an empty search box opens Shortcuts and syntax: keys on the left, syntax examples on the right; an example clicked is put in the box and searched.
- In the list ↑ ↓, Page Up, Page Down, Home, End select; Enter or a double click opens; Ctrl+Enter locates; Ctrl+C copies the file; Ctrl+Shift+C copies the path. These are the default keys; see "Global hotkey" above for changing them.
- These keys also work in the search box: on the selected row, or the first row when none is selected; pressed right after typing they act on the new results. With text selected in the box, Ctrl+C and Ctrl+Shift+C copy that text.
- Locate opens the containing folder in the file manager with the item selected (files and folders alike); where the file manager cannot select it, only the folder is opened and the status bar says so.
- Copy file puts the file or folder itself on the clipboard: pasting in a file manager gives the item, pasting in other programs its path. Only the window has it; the browser page's clipboard holds text only, so there Ctrl+C still copies the path.
- Right click or the Menu key (Shift+F10; the menu opens below the selected row), in three groups: open, locate, copy path, copy file (each with its key); Exclude this folder (folder rows) or Exclude the containing folder (file rows), Go to the newest version (on Newer exists rows); rescan. Excluding asks first, naming the folder and how many entries leave the index; when that folder is an indexed folder itself the item cannot be chosen and its tooltip says why.
- Hovering a result row shows its full path and modification time.
- Similar versions: several versions of one file (copies, copies saved with a date or version number, drafts and finals) form a group; the newest by modification time is tagged Newest after its name and the others Newer exists. Results are shown as usual, not folded. Hovering adds a line with the group size and the newest one; right-click a Newer exists row for Go to the newest version. The rules are under "Similar versions" below.
- The gear button beside the search box, or Ctrl+, opens Settings; see "What is indexed, and settings" below. The More menu next to it has Shortcuts and syntax, Switch appearance (the theme's dark or light variant, remembered), Fold to a search box, Rescan and About.
- Results can be dragged into other programs.
- F5 rescans (the status bar says it started, or to try again later while a scan runs); Ctrl+, opens Settings; Ctrl+L goes to the search box.
- Esc: in the list it goes back to the search box; with text in the box it clears it (which folds the list); in an empty box it hides the window when a global show-or-hide shortcut is set, and closes it otherwise.
- While another program has the focus the window is 70 % opaque, and opaque again on return; the window's own context menu and dialogs do not count. This needs a desktop compositor; without one the window stays opaque.
- Window size, maximised state, position, sort and an appearance switched by hand are remembered on close and restored next time, in `~/.config/find-fast/ui-state.json` (mode 600), apart from the settings and without effect on the index. A damaged file or bad values fall back to defaults; column widths and order kept by earlier versions are no longer used; a remembered position that is no longer on a monitor, or any position under Wayland (where programs cannot place windows), is left to the desktop. The browser page is not affected.
- With an empty search box only the search row shows and the window becomes 90 pixels high where it is; the first character typed unfolds the result list to the height it last had unfolded, also when nothing matches (it then says so). Clearing the box, Esc, or More → Fold to a search box folds it again. A maximised window does not fold. While folded, the right end of the search box shows "N items" or "Indexing 42%", and messages such as copy results or errors for a few seconds; hovering the box shows the full index state and the version. When the window is too narrow for the search hint beside that text, the box shows only "Search..." and the hint moves into the tooltip.
- While the list shows, the status bar is the one place that counts results: the number and the time taken (or a message for a few seconds) at the left, the common keys in the middle (hidden below 860 pixels), and the update mode (live or periodic), the number of entries, scan progress, unreadable folders and the version at the right, after a dot that changes colour when folders are unreadable or only updated periodically. During a scan a 2-pixel progress line runs along the lower edge of the search row without moving anything.
- The window is at least 480 pixels wide. Colours and fonts follow the system theme; the yellow match marks come in a light and a dark set to suit it.

### Similar versions

Only files are grouped, not folders, and only within the current result (across folders). From the name without its extension these marks are removed in turn, then differences of case, full- and half-width forms, spaces and brackets are ignored; files with the same remainder and the same extension form a group:

- copy marks: `(1)`, `（2）`, `- 副本`, `_copy`, `copy of`;
- a leading number: `1 `, `02_`;
- a date at the start or end: `20260101`, `2026-01-01`, `2026.1.1`, `260101`, optionally in brackets;
- a version number: `v2`, `V2.1`, `ver3`, `第二版`;
- a draft word: 初稿, 二稿, 三稿, 终稿, 定稿, 修订版, 修改版, 最终版, 最终稿, final, draft.

A remainder shorter than 2 characters is not grouped. The newest in a group is the latest modification time; on a tie the later draft word wins (终稿, 定稿, 最终版, 最终稿, final last, then 修订版, 修改版, then 三稿, 二稿, 初稿 and draft), then the shorter path. Results above 100,000 are not grouped and the status bar says so; from 5,000 up the grouping runs in the background and the tags appear when it is done.

### Browser page

Without python3-gi (or with `--web`) a local web server starts and the browser opens its page, laid out like the window: two-line rows with marked matches, type filters and folder suggestions, the order menu, the details panel (hidden below 1080 pixels), the three empty states, the shortcuts and syntax panel, a context menu with exclusion, the status bar, Settings (four parts; Upgrade is the last, also reached from the More menu), and Quit. The first 200 rows show at once and more load when the list is scrolled near its end; when all are shown, the end of the list says how many. The focus stays in the search box and ↑ ↓ move the selection. The top bar switches between dark and light, kept in that browser and following the system at first; the default order is kept there too. There is no Copy file: a browser clipboard holds text only. Below 860, 760 and 560 pixels the key hints, the time in the rows and the version in the top bar give way in turn; no width scrolls sideways. On the page, Add folder... opens zenity's folder chooser; without zenity the path is typed instead.

The server listens on a random port of 127.0.0.1 only, and its address carries a token made at start. It exits a few seconds after the last page closes (a reload does not count), at once on Quit, and after 120 seconds when no page ever opened; a page left in a background tab does not count as closed. `--no-browser` only prints the address.

### Command line

```
python3 find_fast.py QUERY...            print matching paths, newest first
  --sort mtime|name|path|size  --asc / --desc
  --regex          the whole query is one regular expression
  --limit N        at most N paths; --count only the number; -0 NUL-separated
  --update         rescan changed folders first; --rebuild rescan everything
  --status         index status as JSON
  --gtk / --web    choose the window or the page; --no-browser prints the page address only
  --toggle         show the window, or hide it when it is in front (for a global shortcut)
  --remove-hotkey  remove the show-or-hide shortcut this tool wrote into the desktop settings
  --log-level DEBUG|INFO|WARNING|ERROR    (default WARNING, or LOG_LEVEL)
```

The exit code is 1 when nothing matches and 2 for an invalid query.

## Upgrade

Unpack the first release into a folder of your choice that you will keep (for example a Tools folder in your home folder) and send the launcher to the desktop from there, or run `install.sh`. Later releases replace that folder's contents in place, so the path never changes: desktop links, the menu entry `install.sh` wrote and the global show-or-hide shortcut (Ctrl+Alt+Space by default) keep working, and an installed copy needs no reinstall.

1. Download the new release zip (or unpack it and use the `find-fast` folder inside).
2. In the window, open Settings, go to the Upgrade page and choose Upgrade from a zip… or Upgrade from an unpacked folder…; on the browser page open Settings → Upgrade (also More → Upgrade), where a zip or a folder can be chosen, dropped or picked with the keyboard. The check shows current version → new version, the changes between the two from CHANGELOG.md, the files kept and any extra files; a downgrade or reinstall is called out.
3. Choose Upgrade to vX.Y.Z. The status bar (or the page) shows each stage while the search box stays usable; then the window opens again on the new version, or the page reconnects to the service restarted on the same address.

On the command line: `python3 find_fast.py --upgrade find-fast-vX.Y.Z.zip` shows the same check and asks (`--yes` skips the question).

- Kept: the paths in `upgrade-keep.txt` (none: settings are in `~/.config/find-fast`, the index in `~/.cache/find-fast`, outside the tool folder, and are not touched).
- Extra files: files in the tool folder that are neither on the keep list nor in the new release. They are listed first, are not deleted, and stay with the previous version.
- Previous version: the old folder becomes the hidden `.find-fast.上一版` next to it; only one is kept. Roll back to previous version (Settings, the page, or `--rollback`) swaps the two; doing it again returns to the newer one.
- Nothing changes, and the reason is shown, when the chosen item is not a find-fast release (its top folder is not `find-fast`), its version cannot be read, a program is missing, an entry has `..`, an absolute path, a symbolic link or a device file, it unpacks to more than 200 MB or 5000 entries, or the folder above the tool folder is not writable. A failure part-way restores the folder as it was.
- The page writes an uploaded zip only to the system temporary folder and removes it afterwards; a chosen folder is zipped by the page first.
- From a release without Upgrade (0.4.0 and earlier): unpack the new release elsewhere and run `python3 <unpacked folder>/tool_upgrade.py --tool-dir <tool folder> --upgrade find-fast-vX.Y.Z.zip`; later upgrades work as above.

## What is indexed, and settings

By default the home folder and local disks mounted under `/media` and `/mnt`. Network mounts (nfs, cifs/smb, sshfs and other FUSE file systems except local ones such as ntfs-3g and exfat) and pseudo file systems such as `/proc` and `/sys` are skipped, and symbolic links to folders are not followed.

The gear button beside the search box (or Ctrl+,) opens Settings, in four parts:

- Indexed folders: Index hidden files and folders; Search words also match the path (on by default, plain words are looked for in names and in the names of the folders above; off, in names only; changing it does not rescan); the folder list, where any can be removed and Add folder... picks one in the system folder chooser.
- Exclusions: remove any; Add folder... excludes a chosen folder by path, or type a name rule (such as `node_modules` or `*.tmp`) and choose Add.
- Search: the default order (kept with the interface state, not in the settings file) and a syntax summary; the window's shortcuts are on this page too.
- Upgrade: see "Upgrade" above.
- Restore defaults puts the default values in the panel; nothing is written until Save.

Saving checks first: an empty folder list cannot be saved; a folder that does not exist, one on a network mount, one inside another indexed folder, or an exclusion outside every indexed folder is listed with the reason, and Save anyway saves regardless. The same folder written two ways counts once, and folders under home are written as `~/...`.

The index is updated in the background right after saving, and searching goes on meanwhile: when exclusions were only added, matching entries are dropped from the index without a rescan; other changes rescan (turning hidden entries on or removing an exclusion lists every folder again). Saving during a scan stops it and starts over with the new settings.

Settings live in `~/.config/find-fast/config.json`, which can also be edited by hand; defaults apply without it:

```json
{
  "roots": ["~", "/media", "/mnt"],
  "exclude": ["node_modules", "__pycache__", "lost+found", "$RECYCLE.BIN", "System Volume Information"],
  "hidden": false,
  "match_path": true
}
```

- `roots`: folders to index (`~` allowed); a root inside another one is ignored.
- `exclude`: entries without `/` exclude by name (wildcards `*` `?` allowed); entries with `/` or starting with `~` exclude a whole folder by path.
- `hidden`: also index names that start with a dot.
- `match_path`: plain search words also match folder names in the path; `true` by default.
- `keys`, `toggle_default_done`: the shortcuts, and whether the default show-or-hide shortcut was dealt with; written by Settings.

After the file is edited by hand, the next start rescans everything.

The index is `~/.cache/find-fast/index.bin`, mode 600. Sizes and times are updated when their folder changes: live through inotify while the window is open, and at the next start for changes made while it was closed. When there are more folders than the system inotify limit (`/proc/sys/fs/inotify/max_user_watches`), the rest are rescanned every 5 minutes and the status bar says so.

## Performance

On GitHub's Ubuntu runners, with a million fictional entries from `scripts/bench.py`: about 0.3 s from start to a searchable index and about 250 MB peak memory; plain words and typing take 15 to 60 ms per search, and about 60 to 120 ms when the words also appear in many folder names and the results multiply (the benchmark draws folder and file names from the same words, the least favourable case); wildcard, extension, path and regular-expression queries, which test each entry more than once, take 60 to 130 ms depending on the machine.

## Privacy

The tool reads folder listings only, never file contents, changes no file and does not use the network. The index and settings stay in `~/.cache/find-fast` and `~/.config/find-fast`.

## Changes

See [CHANGELOG.md](CHANGELOG.md).

- 0.7.0: new layout: rows show the name over its folder with matches marked; a details panel at the right holds the full information and the actions, and the button row above the list and the locate button on every row are gone; type filters with counts over the whole result, folder suggestions for large results, and an order menu (column headers and the column order setting are removed); the status bar is the one place that counts, and a thin line under the search row shows a scan; three empty states, regular-expression errors explained in place, a ? panel for shortcuts and syntax, a grouped context menu; Settings in four parts; the folded window is 90 pixels high; the page switches between dark and light and never scrolls sideways.
- 0.6.0: window: Enter or a shortcut right after typing acts on the new results; locate and copy keys also work in the search box; Esc in an empty box hides the window when a show-or-hide shortcut is set; settings problems stay above the buttons, the upgrade report scrolls and unsaved settings are asked about before an upgrade; a bad regular expression and a missing program to open a file are explained; the exclude question gives the number of entries; similar versions with the same time are ranked by draft word.
- 0.5.1: an upgrade gives the new files permissions that follow the umask.
- 0.5.0: upgrade in place from a release zip or folder, in Settings, on the page and on the command line, keeping the previous version for roll-back.
- 0.3.1: feedback address in the READMEs; no change to the tool.
- 0.3.0: search words also match folder names in the path (can be turned off in Settings); result columns can be reordered by dragging or in Settings; default show-or-hide shortcut Ctrl+Alt+Space, written on install.
- 0.2.0: hovering a result shows its full path; settings panel and exclusion from the context menu; similar versions marked; a locate button on every row and copy file; a more compact window that remembers its layout and fades while unfocused; the list folds away under an empty search box; shortcuts can be changed and a global show-or-hide shortcut set.
- 0.1.0: first version.

## Licence

MIT, see [LICENSE](LICENSE).

## Feedback

Send suggestions and feedback to [hong.xie.me@outlook.com](mailto:hong.xie.me@outlook.com).

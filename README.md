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
| `双击运行.desktop` | Double-click launcher, shown as 秒搜文件 ("find-fast"). |
| `install.sh` | Optional install into `~/.local`: a `find-fast` command and a menu entry. |
| `find_fast.py` | Entry point: without arguments it opens the window; with a query it prints matches. |
| `find_fast_core.py` | Index and search: scanning, cache, query language, inotify. |
| `find_fast_gtk.py` | The GTK3 window. |
| `find_fast_web.py`, `find_fast.html` | The browser page, used when python3-gi is missing. |
| `tests/`, `scripts/`, `docs/` | Development only: tests, checks, benchmark, specification (not in the release zip). |

## Requirements

- A Linux desktop (Ubuntu, Kylin and others), x86_64 or arm64.
- Python 3.8 or later.
- For the window: python3-gi and the GTK 3 runtime (`import gi` works; usually preinstalled on desktop systems). Without them the browser page is used and a notice says so.
- Optional: `xdg-open` (opening files), `gdbus` (the browser page selecting a file in the file manager), `zenity` or `notify-send` (notices when started without a terminal).

## Use

Download `find-fast-v<version>.zip` from Releases, unpack it and double-click `双击运行.desktop`, or run `python3 find_fast.py`. A link to the launcher can go on the desktop; a copy cannot, since it must find the program next to it.

For a menu entry and a hotkey, run `bash install.sh` once. It copies the tool to `~/.local/share/find-fast` and creates the command `~/.local/bin/find-fast` and a menu entry; no root needed. `bash install.sh --uninstall` removes them and keeps the settings and the index.

The first start builds the index, with progress in the status bar; what has been scanned can be searched meanwhile. Later starts load the previous index and relist only folders that changed.

### Global hotkey

The tool does not grab keys itself; bind it in the system settings. Starting it while it is open brings the open window forward.

- GNOME (Ubuntu): Settings → Keyboard → View and Customise Shortcuts → Custom Shortcuts → add, with the full path of `~/.local/bin/find-fast` as the command (for example `/home/<user>/.local/bin/find-fast`).
- Kylin (UKUI): Settings → Devices → Shortcuts → Custom Shortcuts → add, with the same full path.
- Without `install.sh`, use `python3 <tool folder>/find_fast.py`.

### Query syntax

| Query | Matches |
| --- | --- |
| `report 2024` | names containing all the words (any case) |
| `pdf\|docx` | either word |
| `!draft` | not containing the word |
| `*.pdf`, `img_??.png` | wildcards, matched against the whole name |
| `ext:pdf;docx` | by extension |
| `path:project`, `docs/2024` | the whole path (a word with `/` matches the path) |
| `regex:^img_\d+` | a regular expression on the name, any case |
| `"annual report"` | a space inside quotes belongs to the word |

Folders appear in the results as well.

### Window

- Type to search; ↓ moves into the list and ↑ on the first row back to the box; typing in the list continues in the box.
- ↑ ↓, Page Up, Page Down, Home, End select; Enter or a double click opens; Ctrl+Enter locates; Ctrl+C copies the file; Ctrl+Shift+C copies the path.
- Locate opens the containing folder in the file manager with the item selected (files and folders alike); where the file manager cannot select it, only the folder is opened and the status bar says so. The locate button at the end of every row locates that row.
- Copy file puts the file or folder itself on the clipboard: pasting in a file manager gives the item, pasting in other programs its path. Only the window has it; the browser page's clipboard holds text only, so there Ctrl+C still copies the path.
- Right click or the Menu key (Shift+F10): locate, open, copy file, copy path; after a separator Go to the newest version (on Newer exists rows), Exclude this folder (folder rows) or Exclude the containing folder (file rows), rescan. Excluding asks first and names the folder; the item is not shown when that folder is an indexed folder itself.
- Click a column header to sort by name, path, size or modification time; click again to reverse. Newest first by default.
- Hovering a result row shows its full path.
- Similar versions: several versions of one file (copies, copies saved with a date or version number, drafts and finals) form a group; the newest by modification time is tagged Newest before its name and the others Newer exists. Results are shown as usual, not folded. Hovering adds a line with the group size and the newest one; right-click a Newer exists row for Go to the newest version. The rules are under "Similar versions" below.
- The gear button beside the search box, or Ctrl+, opens Settings; see "What is indexed, and settings" below.
- Results can be dragged into other programs.
- F5 or Ctrl+R rescans; Esc clears the box, and a second Esc closes the window.
- While another program has the focus the window is 70 % opaque, and opaque again on return; the window's own context menu and dialogs do not count. This needs a desktop compositor; without one the window stays opaque.
- Column widths, window size, maximised state, position and sort are remembered on close and restored next time, in `~/.config/find-fast/ui-state.json` (mode 600), apart from the settings and without effect on the index. A damaged file or bad values fall back to defaults; a remembered position that is no longer on a monitor, or any position under Wayland (where programs cannot place windows), is left to the desktop. The browser page is not affected.
- The status bar shows the number of results and the time taken on the left, and the number of entries, scan progress, unreadable folders, the update mode (live or periodic) and the version on the right.

### Similar versions

Only files are grouped, not folders, and only within the current result (across folders). From the name without its extension these marks are removed in turn, then differences of case, full- and half-width forms, spaces and brackets are ignored; files with the same remainder and the same extension form a group:

- copy marks: `(1)`, `（2）`, `- 副本`, `_copy`, `copy of`;
- a leading number: `1 `, `02_`;
- a date at the start or end: `20260101`, `2026-01-01`, `2026.1.1`, `260101`, optionally in brackets;
- a version number: `v2`, `V2.1`, `ver3`, `第二版`;
- a draft word: 初稿, 二稿, 三稿, 终稿, 定稿, 修订版, 修改版, 最终版, 最终稿, final, draft.

A remainder shorter than 2 characters is not grouped. The newest in a group is the latest modification time, the shorter path on a tie. Results above 100,000 are not grouped and the status bar says so; from 5,000 up the grouping runs in the background and the tags appear when it is done.

### Browser page

Without python3-gi (or with `--web`) a local web server starts and the browser opens its page: search, sort, a result table (200 rows at a time, "show more" for the next; hovering a row shows its full path), open, locate (also a button at the end of every row), copy path, rescan, settings (the gear button), a context menu with exclusion, and quit. On the page, Add folder... opens zenity's folder chooser; without zenity the path is typed instead.

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
  --log-level DEBUG|INFO|WARNING|ERROR    (default WARNING, or LOG_LEVEL)
```

The exit code is 1 when nothing matches and 2 for an invalid query.

## What is indexed, and settings

By default the home folder and local disks mounted under `/media` and `/mnt`. Network mounts (nfs, cifs/smb, sshfs and other FUSE file systems except local ones such as ntfs-3g and exfat) and pseudo file systems such as `/proc` and `/sys` are skipped, and symbolic links to folders are not followed.

The gear button beside the search box (or Ctrl+, in the window) opens Settings:

- Indexed folders: remove any; Add folder... picks one in the system folder chooser.
- Excluded: remove any; Add folder... excludes a chosen folder by path, or type a name rule (such as `node_modules` or `*.tmp`) and choose Add.
- Index hidden files and folders: a switch.
- Restore defaults puts the default values in the panel; nothing is written until Save.

Saving checks first: an empty folder list cannot be saved; a folder that does not exist, one on a network mount, one inside another indexed folder, or an exclusion outside every indexed folder is listed with the reason, and Save anyway saves regardless. The same folder written two ways counts once, and folders under home are written as `~/...`.

The index is updated in the background right after saving, and searching goes on meanwhile: when exclusions were only added, matching entries are dropped from the index without a rescan; other changes rescan (turning hidden entries on or removing an exclusion lists every folder again). Saving during a scan stops it and starts over with the new settings.

Settings live in `~/.config/find-fast/config.json`, which can also be edited by hand; defaults apply without it:

```json
{
  "roots": ["~", "/media", "/mnt"],
  "exclude": ["node_modules", "__pycache__", "lost+found", "$RECYCLE.BIN", "System Volume Information"],
  "hidden": false
}
```

- `roots`: folders to index (`~` allowed); a root inside another one is ignored.
- `exclude`: entries without `/` exclude by name (wildcards `*` `?` allowed); entries with `/` or starting with `~` exclude a whole folder by path.
- `hidden`: also index names that start with a dot.

After the file is edited by hand, the next start rescans everything.

The index is `~/.cache/find-fast/index.bin`, mode 600. Sizes and times are updated when their folder changes: live through inotify while the window is open, and at the next start for changes made while it was closed. When there are more folders than the system inotify limit (`/proc/sys/fs/inotify/max_user_watches`), the rest are rescanned every 5 minutes and the status bar says so.

## Performance

On GitHub's Ubuntu runners, with a million fictional entries from `scripts/bench.py`: about 0.3 s from start to a searchable index and about 250 MB peak memory; plain words and typing take 15 to 60 ms per search; wildcard, extension, path and regular-expression queries, which test each entry more than once, take 60 to 130 ms depending on the machine.

## Privacy

The tool reads folder listings only, never file contents, changes no file and does not use the network. The index and settings stay in `~/.cache/find-fast` and `~/.config/find-fast`.

## Changes

See [CHANGELOG.md](CHANGELOG.md).

- 0.2.0: hovering a result shows its full path; settings panel and exclusion from the context menu; similar versions marked; a locate button on every row and copy file; a more compact window that remembers its layout and fades while unfocused.
- 0.1.0: first version.

## Licence

MIT, see [LICENSE](LICENSE).

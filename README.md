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
- ↑ ↓, Page Up, Page Down, Home, End select; Enter or a double click opens; Ctrl+Enter opens the containing folder, with the item selected where the file manager supports it; Ctrl+C copies the path.
- Right click or the Menu key (Shift+F10): open, open containing folder, copy path, rescan.
- Click a column header to sort by name, path, size or modification time; click again to reverse. Newest first by default.
- Results can be dragged into other programs.
- F5 or Ctrl+R rescans; Esc clears the box, and a second Esc closes the window.
- The status bar shows the number of results and the time taken on the left, and the number of entries, scan progress, unreadable folders, the update mode (live or periodic) and the version on the right.

### Browser page

Without python3-gi (or with `--web`) a local web server starts and the browser opens its page: search, sort, a result table (200 rows at a time, "show more" for the next), open, open containing folder, copy path, rescan and quit.

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

Settings live in `~/.config/find-fast/config.json`; defaults apply without it:

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

After a change of settings the next start rescans everything.

The index is `~/.cache/find-fast/index.bin`, mode 600. Sizes and times are updated when their folder changes: live through inotify while the window is open, and at the next start for changes made while it was closed. When there are more folders than the system inotify limit (`/proc/sys/fs/inotify/max_user_watches`), the rest are rescanned every 5 minutes and the status bar says so.

## Performance

On GitHub's Ubuntu runners, with a million fictional entries from `scripts/bench.py`: about 0.3 s from start to a searchable index and about 250 MB peak memory; plain words and typing take 15 to 60 ms per search; wildcard, extension, path and regular-expression queries, which test each entry more than once, take 60 to 130 ms depending on the machine.

## Privacy

The tool reads folder listings only, never file contents, changes no file and does not use the network. The index and settings stay in `~/.cache/find-fast` and `~/.config/find-fast`.

## Changes

See [CHANGELOG.md](CHANGELOG.md).

## Licence

MIT, see [LICENSE](LICENSE).

# Changelog

## 0.2.0

- Hovering a result row shows its full path, in the GTK window and on the browser page.

## 0.1.0

First version.

- Whole-disk file-name index of the home folder and local disks under `/media` and `/mnt`, skipping network mounts, pseudo file systems, hidden names and configurable exclusions (`~/.config/find-fast/config.json`). Kept in a compact cache (`~/.cache/find-fast/index.bin`, mode 600); later starts relist only changed folders.
- Query language: several words, `a|b`, `!a`, wildcards on the whole name, `ext:`, `path:` (or any word with `/`), `regex:`.
- GTK3 window through the system's python3-gi: a virtual result list without a row limit, four sortable columns, keyboard control, context menu, drag and drop, one window per user session, inotify live updates with periodic rescans when the watch limit is reached.
- Browser page when python3-gi is missing (or with `--web`): a local server on a random port of 127.0.0.1 with a per-run token, search, sort, open, open containing folder, copy path; exits a few seconds after its last page closes.
- Command line: `find_fast.py QUERY` with `--sort`, `--asc`, `--limit`, `--count`, `-0`, `--update`, `--rebuild`, `--status`.
- `install.sh` installs into `~/.local` with a `find-fast` command and a menu entry; `--uninstall` removes them.
- Interface in English and Chinese, following `LANG`.

# find-fast: instant file-name search for the Linux desktop

[中文](README.zh-CN.md)

Type part of a name and every matching file under your home folder and local disks shows up as you type. It needs only Python 3 and the GTK3 bindings most Linux desktops already ship (python3-gi); without them it opens the same search in the browser.

- Nothing to install: Python 3 standard library plus the system's PyGObject. No pip, nothing to compile, no network access.
- Fast: the index is kept on disk in a compact form, so the window is searchable within a second of opening, and a background pass picks up what changed while it was closed. While the window is open, inotify keeps it current.
- Searches names and paths only, never file contents.
- Interface in English or Chinese, following `LANG`.

Status: under development towards 0.1.0. See [docs/design.md](docs/design.md) (in Chinese) for the specification.

## Licence

MIT, see [LICENSE](LICENSE).

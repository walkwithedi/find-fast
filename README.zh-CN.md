# 秒搜文件（find-fast）

[English](README.md)

在 Linux 桌面上按文件名秒搜家目录和本地磁盘里的文件，边输入边出结果。只需要 Python 3 和大多数 Linux 桌面自带的 GTK3 绑定（python3-gi）；没有时改用浏览器打开同样的搜索页面。

- 免安装：Python 3.8 及以上的标准库加系统自带的 PyGObject，不用 pip，不用编译，运行时不访问网络。
- 快：索引以紧凑格式存在磁盘上，打开窗口约 1 秒内即可搜索，后台补扫关窗期间的变化；窗口开着时用 inotify 实时更新。
- 结果不限条数：列表只绘制屏幕上看得到的行，一百万条结果也能滚动、排序。
- 只搜文件名和路径，不搜文件内容。
- 界面中英双语，跟随 `LANG`。

## 目录内容

| 文件 | 作用 |
| --- | --- |
| `双击运行.desktop` | 双击入口，显示为「秒搜文件」。 |
| `install.sh` | 可选安装：装到 `~/.local`，加命令 `find-fast` 和应用菜单项。 |
| `find_fast.py` | 入口：不带参数打开窗口，带查询词时在终端输出结果。 |
| `find_fast_core.py` | 索引与搜索：扫描、缓存、查询语法、inotify。 |
| `find_fast_gtk.py` | GTK3 窗口。 |
| `find_fast_web.py`、`find_fast.html` | 浏览器页面（没有 python3-gi 时使用）。 |
| `tests/`、`scripts/`、`docs/` | 开发用：测试、检查与基准脚本、规格（发行包里不含）。 |

## 运行环境

- Linux 桌面（麒麟、Ubuntu 等），x86_64 或 arm64。
- Python 3.8 或更新版本。
- 窗口版需要 python3-gi 和 GTK 3 运行库（`import gi` 能成功即可；Ubuntu、麒麟桌面一般已预装）。没有时自动改用浏览器页面并提示。
- 可选：`xdg-open`（打开文件）、`gdbus`（网页版在文件管理器里选中文件）、`zenity` 或 `notify-send`（没有终端时的提示）。

## 使用方法

从 Releases 下载 `find-fast-v<版本>.zip` 解压，双击 `双击运行.desktop`；或在终端运行 `python3 find_fast.py`。桌面上可以放它的链接，不要复制（复制后找不到同目录的程序）。

想从应用菜单打开或配快捷键，运行一次 `bash install.sh`。它把工具复制到 `~/.local/share/find-fast`，建立命令 `~/.local/bin/find-fast` 和菜单项「秒搜文件」，不需要 root。`bash install.sh --uninstall` 卸载，设置和索引保留。

第一次打开会建立索引，状态栏显示进度，期间已经可以搜索已扫到的部分。之后每次打开先载入上次的索引，后台只重新列出有变化的文件夹。

### 全局快捷键

工具本身不抓快捷键，由系统设置绑定：已经开着时再次启动会把现有窗口调到前面。

- GNOME（Ubuntu）：设置 → 键盘 → 查看及自定义快捷键 → 自定义快捷键 → 添加，命令填 `~/.local/bin/find-fast` 的完整路径（如 `/home/<用户名>/.local/bin/find-fast`）。
- 麒麟（UKUI）：设置 → 设备 → 快捷键 → 自定义快捷键 → 添加，程序填同样的完整路径。
- 没运行 `install.sh` 时，命令填 `python3 <工具目录>/find_fast.py`。

### 搜索语法

| 写法 | 含义 |
| --- | --- |
| `report 2024` | 名称里同时含有这几个词（不分大小写） |
| `pdf\|docx` | 含有任一个 |
| `!draft` | 不含 |
| `*.pdf`、`img_??.png` | 通配符，匹配整个文件名 |
| `ext:pdf;docx` | 按扩展名 |
| `path:project`、`docs/2024` | 匹配完整路径（带 `/` 的词自动按路径匹配） |
| `regex:^img_\d+` | 正则表达式（匹配名称，不分大小写） |
| `"annual report"` | 引号内的空格算词的一部分 |

文件夹本身也会出现在结果里。

### 窗口操作

- 输入即搜；↓ 进入列表，在第一行按 ↑ 回到搜索框；在列表里直接打字会回到搜索框继续输入。
- ↑ ↓、Page Up、Page Down、Home、End 选择；回车或双击打开；Ctrl+Enter 打开所在文件夹（文件管理器支持时选中该项）；Ctrl+C 复制路径。
- 右键或菜单键（Shift+F10）：打开、打开所在文件夹、复制路径、重新扫描。
- 点列头按名称、路径、大小、修改时间排序，再点反向。默认最新在前。
- 可以把结果拖到其他程序。
- F5 或 Ctrl+R 重新扫描；Esc 先清空搜索框，再按一次关闭窗口。
- 状态栏左边是结果数与耗时，右边是条目总数、扫描进度、无法读取的文件夹数、更新方式（实时更新或定时更新）和版本号。

### 浏览器页面

没有 python3-gi 时（或用 `--web`）启动本机网页服务并打开浏览器。功能：搜索、排序、结果表（每次 200 行，「显示更多」继续）、打开、打开所在文件夹、复制路径、重新扫描、退出。

服务只监听 127.0.0.1 的随机端口，网址带本次启动生成的令牌；关闭页面后数秒内自动退出（刷新不算关闭），点「退出」立即结束；页面挂在后台不会被判为关闭；120 秒内没有页面打开也会退出。`--no-browser` 只输出网址。

### 命令行

```
python3 find_fast.py 查询词...            输出匹配的完整路径，最新在前
  --sort mtime|name|path|size  --asc / --desc   排序
  --regex          整个查询作为正则表达式
  --limit N        最多输出 N 条；--count 只输出条数；-0 用 NUL 分隔
  --update         先补扫有变化的文件夹；--rebuild 全部重扫
  --status         输出索引状态（JSON）
  --gtk / --web    指定窗口或网页；--no-browser 网页版只输出网址
  --log-level DEBUG|INFO|WARNING|ERROR    日志级别（默认 WARNING，可用环境变量 LOG_LEVEL）
```

没有匹配时退出码为 1，查询写错时为 2。

## 索引范围与设置

默认索引家目录，以及 `/media`、`/mnt` 下挂载的本地磁盘。网络挂载（nfs、cifs/smb、sshfs 等，除 ntfs-3g、exfat 等本地格式外的 fuse 文件系统也按网络处理）和 `/proc`、`/sys` 等伪文件系统不索引；不跟随符号链接进入文件夹。

设置文件是 `~/.config/find-fast/config.json`，没有时用默认值：

```json
{
  "roots": ["~", "/media", "/mnt"],
  "exclude": ["node_modules", "__pycache__", "lost+found", "$RECYCLE.BIN", "System Volume Information"],
  "hidden": false
}
```

- `roots`：要索引的文件夹（可写 `~`）；互相包含时只算外层。
- `exclude`：不带 `/` 的按名称排除（可用 `*` `?` 通配），带 `/` 或以 `~` 开头的按路径排除整个文件夹。
- `hidden`：是否索引以点开头的隐藏文件和文件夹。

改了设置后下次启动会全部重扫。

索引存在 `~/.cache/find-fast/index.bin`，权限 600。大小与修改时间在文件夹有变化时更新：窗口开着时由 inotify 实时更新；关着时的变化在下次打开时补扫。文件夹太多、超过系统 inotify 监听上限（`/proc/sys/fs/inotify/max_user_watches`）时，超出的部分每 5 分钟补扫一次，状态栏显示「部分文件夹定时更新」。

## 性能

在 GitHub Actions 的 Ubuntu 运行器上，用 `scripts/bench.py` 造的一百万条虚构条目测得：载入索引到可搜约 0.3 秒，内存峰值约 250 MB；普通词搜索与逐字输入每次 15 到 60 毫秒；通配、扩展名、路径、正则等需要逐条多次判断的查询 60 到 130 毫秒，随机器快慢波动。

## 隐私

工具只读取文件夹列表，不读文件内容，不修改任何文件，运行时不访问网络。索引和设置只存在本机的 `~/.cache/find-fast`、`~/.config/find-fast`。

## 版本说明

见 [CHANGELOG.md](CHANGELOG.md)。

- 0.1.0：第一版。GTK3 窗口、浏览器页面与命令行；全盘文件名索引，inotify 实时更新；结果不限条数。

## 许可

MIT，见 [LICENSE](LICENSE)。

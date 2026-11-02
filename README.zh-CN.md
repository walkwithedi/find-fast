# 秒搜文件（find-fast）

[English](README.md)

在 Linux 桌面上按文件名秒搜家目录和本地磁盘里的文件，边输入边出结果。只需要 Python 3 和大多数 Linux 桌面自带的 GTK3 绑定（python3-gi）；没有时改用浏览器打开同样的搜索页面。

- 免安装：Python 3 标准库加系统自带的 PyGObject，不用 pip，不用编译，不访问网络。
- 快：索引以紧凑格式存在磁盘上，打开窗口 1 秒内即可搜索，后台补扫关窗期间的变化；窗口开着时用 inotify 实时更新。
- 只搜文件名和路径，不搜文件内容。
- 界面中英双语，跟随 `LANG`。

状态：正在开发 0.1.0，规格见 [docs/design.md](docs/design.md)。

## 许可

MIT，见 [LICENSE](LICENSE)。

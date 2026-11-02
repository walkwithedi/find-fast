# find-fast 协作约定

find-fast（秒搜文件）是 Linux 桌面上的全盘文件名搜索工具：Python 3 标准库加系统自带的 GTK3（PyGObject），没有 python3-gi 时退回本机网页。规格见 `docs/design.md`。本仓库将来会公开：代码、历史、提交邮箱、Issue、PR 与 Actions 日志都按公开内容对待。

## 目录说明

- `find_fast_core.py`：索引与搜索核心（扫描、缓存、查询解析、inotify），不依赖任何界面。
- `find_fast.py`：入口。命令行查询，以及按有无 gi 选择 GTK 窗口或网页退回。
- `find_fast_gtk.py`：GTK3 窗口。
- `find_fast_web.py`、`find_fast.html`：网页退回（本机服务与页面）。
- `双击运行.desktop`、`install.sh`：双击入口与可选安装脚本。
- `tests/`：unittest；`tests/ui_gtk_test.py` 在 xvfb 下测 GTK 窗口，`tests/web.test.js` 用 Playwright 测网页。
- `scripts/`：仓库检查（`run_checks.py`、`check_repo.py`）、敏感扫描（`sensitive_scan.py`）、基准测试（`bench.py`）。

## 运行环境约束

- 只用 Python 3.8+ 标准库，界面另加系统包 python3-gi（`gi`，GTK 3.0）；不得引入 pip 包。`scripts/check_repo.py` 检查导入。
- 页面不从网络加载任何资源（CDN、外部字体等）。
- 目标系统为麒麟与 Ubuntu（x86_64、arm64）；离线可用，运行时不访问网络。

## 本机服务约定（网页退回）

- 只监听 127.0.0.1 的随机端口；令牌每次启动随机生成，进程运行期间有效，退出即作废；网址带令牌并校验 Host、Origin。
- 页面关闭或刷新时用 `sendBeacon` 通知服务，全部页面关闭数秒后退出；心跳超时只作兜底，不得短到页面挂在后台就被判关闭；有任务进行时等任务结束再退出。
- 打不开浏览器或缺少页面文件时用 zenity、notify-send 提示。
- 界面是同目录的独立 `.html` 文件，不内嵌进 .py。

## 交互界面约定

网页界面：

- 页头写工具名（中文「秒搜文件」，英文 find-fast），页脚写版本号；右上角放「退出」，页脚常驻退出规则。
- 颜色用 `:root` 变量，同时给出 `prefers-color-scheme: dark` 的取值；字体用 `"Noto Sans CJK SC","WenQuanYi Micro Hei","PingFang SC","Microsoft YaHei",sans-serif`，等宽字体用 `"Noto Sans Mono CJK SC","DejaVu Sans Mono",monospace`，不加载外部字体。
- 360px 宽度下不出现横向滚动，宽表格放进可横向滚动的容器。
- 可聚焦元素有 `:focus-visible` 样式。
- 状态区分 ok、warn、bad、info 四种并加 `aria-live="polite"`；超过 1 秒的操作显示进度或阶段文字，期间禁用触发按钮。
- 文件名、错误信息等外来文本只用 `textContent` 或文本节点写入页面，不拼进 `innerHTML`。
- 复制按成败分别提示，失败时提示手动选中复制。
- 「清空」类操作点了直接清空，不弹确认框。

GTK 窗口：

- 窗口标题写工具名，状态栏写索引状态与版本号。
- 跟随系统主题与字体，不硬编码颜色。
- 超过 1 秒的操作（首次建索引、补扫）在状态栏显示进度，搜索框始终可用。
- 键盘可完成全部操作：输入即搜，方向键选结果，回车打开，Ctrl+Enter 打开所在文件夹，Ctrl+C 复制路径，Esc 清空搜索框，再按一次关闭窗口。

通用文案：

- 界面中英双语，按 `LANG` 选择；文字集中在一个字典里，两种语言的键保持一致，测试检查。
- 动作用词：「打开」「打开所在文件夹」「复制路径」「保存」「清空」「退出」「返回」；不用「下载」「导出」指保存。
- 失败提示写作「<动作>失败：<原因>。<下一步怎么做>」；省略号用「……」，界面元素名用「」。

## Python 脚本日志约定

- 用标准库 `logging`，格式 `%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s`，输出到标准错误。
- 提供 `--log-level` 参数（DEBUG / INFO / WARNING / ERROR），默认值可由环境变量 `LOG_LEVEL` 覆盖。

## 安全

- 不得出现个人信息、任何单位的内部信息（单位、主机、系统、项目、人名、内部路径与地址、业务数据）和凭据。示例用明显虚构的名字（张三、某某有限公司、Project Atlas）、example.com 地址与文档专用 IP 段。
- 只写规则和行为，不写来历：README、规格、代码注释、CHANGELOG、提交说明与 PR 描述不写「某次某人遇到」一类经过，不描述工具服务的工作环境、单位与人员，不引用真实文档里的数字。
- `scripts/sensitive_scan.py` 在每次提交与推送前（`.claude/hooks/pre_commit.py`、`.githooks`）和 CI 中运行。被拦下时停下来向使用者报告，不改写、删除或挪走命中的文字来绕过；只有使用者确认无害并同意后，才在该行加 `sensitive-scan: ignore`；私有敏感词命中不能用此标记放行。
- 测试里的挂载路径、家目录一律用临时目录或占位写法，不写真实路径。
- 私有敏感词表（仓库 Secret `SENSITIVE_TERMS`、`~/.config/find-fast/sensitive_terms.txt`）不进仓库，也不在提交、Issue、PR 中引用。

## 先设计后编码

- 会改动文件或执行有副作用操作（提交、推送、建 PR、改远端配置等）的任务，先设计再动手：目标、改动哪些文件、方案与取舍、如何验证；改动小的几行即可。
- 设计交使用者确认：计划模式下用退出计划模式的审批；否则用选择题弹窗（AskUserQuestion），批准项以「批准方案」开头。确认后才开始编码；实施中需要偏离设计时停下重新确认。
- 纯问答、只读排查不需要设计。
- `.claude/settings.json` 把 `permissions.defaultMode` 设为 `plan`；`.claude/hooks/plan_gate.py` 在本会话方案获批前拦下改动类操作。获批标记按会话存在仓库外的 `~/.claude/plan-approved/`，不得自行创建或改动；被误拦时报告使用者，不绕过。

## 决策方式

- 需要使用者决定的事项一律用选择题弹窗逐项提问，每题 2 到 4 个选项，推荐项放第一个并标注「（推荐）」，选项说明写清后果。
- 使用者已明确授权或答复过的事项直接执行，不重复提问。

## 提交与发版

- 功能改动走 PR，PR 描述用中文写清改了什么、为什么改、如何验证。分支名不加 claude/ 前缀。
- 提交作者用仓库所有者身份：Edi Xie <338403187+walkwithedi@users.noreply.github.com>；提交说明用中文，不加 Co-Authored-By、会话链接、「Generated with …」等署名行。
- 提交前运行 `python3 scripts/run_checks.py`（unittest、仓库检查、敏感扫描）。
- 行为改动同步更新两份 README 与 CHANGELOG。`VERSION` 存版本号 X.Y.Z，`CHANGELOG.md` 须有对应小节；合并带版本变更的提交到 main 后，`.github/workflows/release.yml` 发布 `v<版本>` 并附 `find-fast-v<版本>.zip`。

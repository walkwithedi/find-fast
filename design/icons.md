# 图标清单

`design/icons.svg` 是 sprite，只含 `<symbol>`，不直接显示。24×24 网格，线性风格，`stroke-width` 1.8，颜色一律 `currentColor`，由 CSS 的 `color` 控制。

Web 用法：

```html
<svg width="16" height="16" aria-hidden="true"><use href="#i-image"/></svg>
```

GTK 用法：GTK 不解析 SVG sprite，分两路——类型图标用主题图标名（下面表格第 4 列），操作图标用 `Gtk.Image.new_from_icon_name`；若主题缺图标，退回随包的单个 SVG（导出时按 symbol id 拆成 22×22 的独立文件）。

| symbol | 用途 | 建议尺寸 | GTK 主题图标名 |
|---|---|---|---|
| `i-search` | 搜索框左图标 | 17 | `edit-find-symbolic` |
| `i-folder` | 文件夹行 / 详情 | 17 / 46 | `folder` |
| `i-doc` | 文档类 | 17 / 46 | `text-x-generic` |
| `i-image` | 图片类 | 17 / 46 | `image-x-generic` |
| `i-archive` | 压缩包 | 17 / 46 | `package-x-generic` |
| `i-code` | 代码类 | 17 / 46 | `text-x-script` |
| `i-audio` | 音频 | 17 / 46 | `audio-x-generic` |
| `i-video` | 视频 | 17 / 46 | `video-x-generic` |
| `i-file` | 其他文件 | 17 / 46 | `text-x-generic` |
| `i-open` | 打开 | 14 | `document-open-symbolic` |
| `i-locate` | 在文件管理器中定位 | 14 | `folder-open-symbolic` |
| `i-copy` | 复制路径 / 复制文件 | 14 | `edit-copy-symbolic` |
| `i-ban` | 排除文件夹 | 14 | `action-unavailable-symbolic` |
| `i-refresh` | 重新扫描 | 14 | `view-refresh-symbolic` |
| `i-gear` | 设置 | 15 | `preferences-system-symbolic` |
| `i-sun` / `i-moon` | 外观切换（浅色显示月亮，深色显示太阳） | 14 | `weather-clear-symbolic` / `weather-clear-night-symbolic` |
| `i-sort` | 排序按钮前缀 | 13 | `view-sort-descending-symbolic` |
| `i-chevron` | 下拉箭头 | 11 | `pan-down-symbolic` |
| `i-close` | 清除搜索 / 关闭标签 | 11 | `window-close-symbolic` |
| `i-more` | 更多菜单 | 15 | `view-more-symbolic` |
| `i-fold` | 收起为搜索框 | 14 | `go-bottom-symbolic` |
| `i-help` | 快捷键与语法 | 14 | `help-about-symbolic` |
| `i-check` | 菜单当前项 | 14 | `object-select-symbolic` |

## 颜色规则

| 场景 | 颜色 |
|---|---|
| 行内类型图标（默认） | `--ink-3` |
| 行内文件夹图标 | `--ico-folder` |
| 选中行的类型图标 | `--accent` |
| 详情面板图标 | `--ink-2`，文件夹用 `--ico-folder` |
| 按钮内图标 | 跟随按钮文字色 |
| 禁用态 | 同色，`opacity:.45` |

## 禁止

- 不许用 emoji（`📁` `⚙` `⌕`），跨发行版字体缺字会变方框，且基线对不齐。
- 不许混用实心与线性两套风格。
- 不许给图标单独上第三种颜色（除上面的文件夹琥珀色）。
- 装饰性图标必须 `aria-hidden="true"`；按钮内的图标由按钮的 `aria-label` 承担语义。

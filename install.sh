#!/bin/bash
# find-fast installer: copies the tool to ~/.local/share/find-fast, adds the command
# ~/.local/bin/find-fast and an application menu entry. No root needed.
#   bash install.sh              install or update
#   bash install.sh --uninstall  remove the program, the command and the menu entry
#                                (the settings in ~/.config/find-fast and the index in
#                                ~/.cache/find-fast are kept; delete them by hand if wanted)
set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$DATA/find-fast"
BIN="$HOME/.local/bin"
MENU="$DATA/applications/find-fast.desktop"
FILES=(find_fast.py find_fast_core.py find_fast_gtk.py find_fast_web.py find_fast.html tool_upgrade.py upgrade-keep.txt
       TOOL_UPGRADE_VERSION VERSION LICENSE
       README.md README.zh-CN.md CHANGELOG.md)

zh() { case "${LC_ALL:-${LC_MESSAGES:-${LANGUAGE:-${LANG:-}}}}" in zh*) return 0 ;; *) return 1 ;; esac; }
say() { if zh; then echo "$1"; else echo "$2"; fi; }

if [ "${1:-}" = "--uninstall" ]; then
  # the show-or-hide shortcut written into the desktop settings goes too (only this tool's own)
  if [ -f "$DEST/find_fast.py" ] && command -v python3 >/dev/null 2>&1; then
    python3 "$DEST/find_fast.py" --remove-hotkey || true
  fi
  rm -f "$BIN/find-fast" "$MENU"
  rm -rf "$DEST"
  say "已卸载。设置（~/.config/find-fast）和索引（~/.cache/find-fast）保留，需要时手动删除。" \
      "Uninstalled. Settings (~/.config/find-fast) and the index (~/.cache/find-fast) are kept; delete them by hand if wanted."
  exit 0
fi
if [ -n "${1:-}" ]; then
  say "用法：bash install.sh [--uninstall]" "Usage: bash install.sh [--uninstall]" >&2
  exit 2
fi

for f in "${FILES[@]}"; do
  if [ ! -f "$SRC/$f" ]; then
    say "安装失败：缺少 $f。请重新解压完整的工具目录后再运行。" \
        "Install failed: $f is missing. Unpack the whole tool folder again and rerun." >&2
    exit 1
  fi
done
if ! command -v python3 >/dev/null 2>&1; then
  say "安装失败：找不到 python3。请先安装 Python 3.8 或更新版本。" \
      "Install failed: python3 not found. Install Python 3.8 or later first." >&2
  exit 1
fi

mkdir -p "$DEST" "$BIN" "$(dirname "$MENU")"
for f in "${FILES[@]}"; do
  install -m 0644 "$SRC/$f" "$DEST/$f"
done
chmod 0755 "$DEST/find_fast.py"
ln -sfn "$DEST/find_fast.py" "$BIN/find-fast"

cat > "$MENU.tmp" <<DESKTOP
[Desktop Entry]
Type=Application
Name=find-fast
Name[zh_CN]=秒搜文件
Comment=Instant file-name search for your home folder and local disks
Comment[zh_CN]=按文件名秒搜家目录与本地磁盘里的文件
Exec=python3 "$DEST/find_fast.py"
Terminal=false
Icon=system-search
Categories=Utility;FileTools;
StartupNotify=true
DESKTOP
mv "$MENU.tmp" "$MENU"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$(dirname "$MENU")" 2>/dev/null || true

# the default show-or-hide shortcut (Ctrl+Alt+Space) goes into the desktop settings now, so it
# works before the tool was ever started; one set earlier is pointed at the installed command
HOTKEY="$(python3 "$DEST/find_fast.py" --default-hotkey 2>/dev/null || true)"

say "已安装到 $DEST。
命令：find-fast（在 $BIN；该目录不在 PATH 时用完整路径）
应用菜单：秒搜文件
唤起快捷键：在窗口的「设置」→「快捷键」里修改；也可在系统设置里新建自定义快捷键，命令填：$BIN/find-fast --toggle" \
"Installed to $DEST.
Command: find-fast (in $BIN; use the full path when that folder is not in PATH)
Menu entry: find-fast
Hotkey: change it in the window under Settings > Shortcuts, or add a custom shortcut in the system keyboard settings with the command: $BIN/find-fast --toggle"
if [ -n "$HOTKEY" ]; then
  echo "$HOTKEY"
fi
case ":$PATH:" in *":$BIN:"*) ;; *) say "注意：$BIN 不在 PATH 中。" "Note: $BIN is not in PATH." ;; esac

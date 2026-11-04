#!/usr/bin/env python3
"""find-fast GTK3 window (system python3-gi).

The result list is virtual: a Gtk.TreeView whose ListStore holds only the rows that fit on
screen, refilled from the search result as the separate scroll bar moves, so the number of
results is not limited. Keyboard: type to search; Down moves into the list; Up/Down, Page
Up/Down, Home/End move; Enter opens; Menu or Shift+F10 opens the context menu; Esc clears the
search box, and when it is empty closes the window. Default shortcuts, changeable in Settings:
Ctrl+Enter locates the item in the file manager; Ctrl+C copies the file itself, Ctrl+Shift+C its
path; F5 rescans; Ctrl+, opens the settings; Ctrl+L goes to the search box. A global shortcut set
in Settings runs `--toggle` through the desktop's custom shortcuts.
"""
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse

import find_fast_core as core

try:
    import tool_upgrade
except ImportError:     # without the upgrade module everything else still works
    tool_upgrade = None

log = logging.getLogger('find_fast_gtk')
APP_ID = 'io.github.walkwithedi.findfast'
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))   # the folder an upgrade replaces (tests change it)
UPGRADE_MAIN = ('find_fast.py', 'find_fast_core.py', 'find_fast_gtk.py', 'find_fast_web.py', 'find_fast.html')
RESCAN_EVERY = 300              # seconds between rescans when inotify cannot watch every folder
NOTICE_SECONDS = 30             # how long a start-up notice stays in the status bar
CHANGE_THROTTLE = 1.0           # seconds between result refreshes caused by file changes
WHEEL_ROWS = 3
CONFIRM_LINES, CONFIRM_CHARS = 12, 600    # a confirmation text beyond these scrolls
CONFIRM_HEIGHT = 360
TAG_ALPHA = 0.6     # opacity of the version tags' text
HINT_GAP = 80       # pixels kept free between the search hint and the state text: icons and margins

UI = {
    'zh': {
        'search': '搜索文件名或所在文件夹……（* ? 通配，ext:pdf，path:，!排除，a|b）',
        'col_name': '名称', 'col_path': '路径', 'col_size': '大小', 'col_mtime': '修改时间',
        'open': '打开', 'open_folder': '定位', 'copy_path': '复制路径', 'copy_file': '复制文件', 'rescan': '重新扫描',
        'col_locate': '定位', 'locate_tip': '在文件管理器中打开所在文件夹并选中', 'locate_item': '定位 {name}',
        'located_folder': '已打开所在文件夹，文件管理器不支持自动选中',
        'copied_file': '已复制文件：{path}，可在文件管理器或其他程序中粘贴',
        'copy_gone': '复制失败：文件已不存在。请重新扫描后再试。',
        'loading': '正在载入索引……',
        'first_scan': '首次建立索引：{dirs} 个文件夹，{files} 个条目……',
        'scanning': '正在更新索引：{dirs} 个文件夹……',
        'results': '{count} 个结果',
        'results_ms': '{count} 个结果（{ms} 毫秒）',
        'entries': '共 {entries} 个条目',
        'copied': '已复制路径：{path}',
        'copy_failed': '复制失败：剪贴板不可用。请在「路径」列选中后手动复制。',
        'open_failed': '打开失败：{error}。请在文件管理器中打开试试。',
        'open_no_app': '打开失败：没有找到能打开这类文件的程序。请在文件管理器中右键它，在「打开方式」里选一个程序。',
        'rescan_started': '已开始重新扫描', 'rescan_busy': '正在扫描，稍后再试',
        'search_short': '搜索……',
        'unsaved_q': '设置里有未保存的修改',
        'unsaved_detail': '完成后窗口会以新版重新打开，设置里这些修改不会保存。要保留，先点「取消」，保存设置后再操作。',
        'unsaved_go': '仍然继续',
        'gone': '打开失败：文件已不存在。索引将在下次扫描时更新。',
        'unreadable': '{count} 个文件夹无法读取',
        'no_match': '没有找到', 'hint_entries': '共 {count} 项', 'hint_scanning': '索引中 {pct}%',
        'hint_first': '索引中，已有 {count} 项',
        'ver_newest': '最新', 'ver_older': '有更新版', 'jump_newest': '跳到最新版',
        'ver_tip': '同组共 {count} 个类似版本，最新：{path}',
        'ver_skipped': '结果过多，未标出类似版本',
        'settings': '设置', 'set_roots': '索引的文件夹', 'set_exclude': '排除',
        'set_exclude_hint': '名称规则，如 node_modules、*.tmp', 'set_hidden': '索引隐藏文件和文件夹',
        'add_folder': '添加文件夹……', 'add': '添加', 'remove': '删除', 'remove_item': '删除 {item}',
        'defaults': '恢复默认', 'cancel': '取消', 'save': '保存', 'save_anyway': '仍然保存',
        'set_blocked': '保存失败：{reason}。请先添加一个文件夹。',
        'set_warn': '保存前请确认以下几项，确认无误后点「仍然保存」：',
        'choose_folder': '选择文件夹',
        'exclude_this': '排除此文件夹', 'exclude_parent': '排除所在文件夹',
        'exclude_q': '排除 {path}？', 'exclude_btn': '排除',
        'exclude_detail': '这个文件夹及其中的 {count} 个条目会从索引中移除，以后也不再索引。可在「设置」的「排除」里删除这条规则来恢复。',
        'applying': '正在按新设置更新索引……', 'applied': '已按新设置更新索引',
        'save_failed': '保存失败：{error}。请检查设置文件夹是否可写。',
        'keys': '快捷键', 'key_none': '未设置', 'key_press': '请按组合键……（Esc 取消）', 'key_clear': '清除',
        'key_clear_item': '清除「{action}」的快捷键',
        'key_toggle': '唤起或隐藏窗口（全局，写入系统快捷键）', 'key_locate': '定位', 'key_open': '打开所选（回车始终可用）',
        'key_copy_file': '复制文件', 'key_copy_path': '复制路径', 'key_settings': '打开设置', 'key_rescan': '重新扫描',
        'key_focus': '聚焦搜索框',
        'key_fixed': '{key} 是列表操作用的固定键（方向键、回车、Esc 等），不能设置为快捷键',
        'key_plain': '{key} 没有 Ctrl、Alt 或 Super，会和输入冲突；请加上修饰键，或用 F1 至 F12',
        'key_dup': '保存失败：「{a}」与「{b}」的快捷键相同。请改掉其中一个。',
        'key_taken': '{key} 已被桌面快捷键「{name}」占用',
        'key_manual': '没有找到可写入的桌面快捷键设置（需要麒麟 UKUI 或 GNOME，以及 gsettings）。唤起快捷键请在系统设置的自定义快捷键里添加，命令填：{command}',
        'key_moved': '工具没有用 install.sh 安装，唤起快捷键指向当前目录；移动工具目录后需重新设置。',
        'copy_command': '复制命令',
        'hotkey_written': '已写入系统快捷键：{key}', 'hotkey_removed': '已删除系统里的唤起快捷键',
        'hotkey_failed': '保存失败：写入系统快捷键时出错（{error}）。请在系统设置的自定义快捷键里手动添加，命令填：{command}',
        'set_match_path': '搜索词也匹配路径（所在文件夹的名称）',
        'set_columns': '列顺序', 'col_up': '上移', 'col_down': '下移', 'col_up_item': '上移「{col}」',
        'col_down_item': '下移「{col}」', 'col_defaults': '恢复默认顺序',
        'hotkey_default_set': '已设置唤起快捷键 {key}：随时按下即可打开或隐藏窗口，可在「设置」→「快捷键」里修改',
        'hotkey_default_taken': '设置默认唤起快捷键失败：{key} 已被桌面快捷键「{name}」占用。'
                                '请在「设置」→「快捷键」→「唤起或隐藏窗口」里换一个组合键。',
        'hotkey_default_manual': '设置默认唤起快捷键失败：没有找到可写入的桌面快捷键设置。'
                                 '请在系统设置的自定义快捷键里手动添加，命令填：{command}',
        'hotkey_default_failed': '设置默认唤起快捷键失败：写入系统快捷键时出错（{error}）。'
                                 '请在「设置」→「快捷键」→「唤起或隐藏窗口」里重新设置。',
        'set_upgrade': '升级', 'upgrade_zip': '从 zip 升级……', 'upgrade_dir': '从解压好的目录升级……',
        'rollback': '退回上一版',
        'upgrade_hint': '新版在原位置替换，桌面链接、菜单项和唤起键不变；旧版留作上一版，可随时退回。',
        'upgrade_now': '当前版本 {cur}，上一版 {prev}', 'upgrade_now_none': '当前版本 {cur}，还没有上一版',
        'pick_zip': '选择新版的 zip 文件', 'pick_dir': '选择解压好的 find-fast 目录', 'zip_filter': 'zip 文件',
        'pick': '选择', 'upgrade_title': '升级秒搜文件',
        'upgrade_versions': '当前版本 {cur} → 新版本 {new}（{kind}）', 'upgrade_notes': '更新说明：',
        'upgrade_keep': '会保留的文件：{files}', 'upgrade_none': '无',
        'upgrade_extras': '多出来的文件（不带到新版，随旧目录留在上一版里，不删除）：{files}',
        'upgrade_more': '……共 {n} 个', 'upgrade_restart_note': '升级后窗口用新版重新打开。',
        'upgrade_refused': '不能升级：{why}。请换一个新版的 zip 或目录。',
        'upgrade_failed_title': '升级没有完成', 'rollback_failed_title': '退回没有完成',
        'rollback_title': '退回上一版',
        'rollback_q': '会把当前 {cur} 换成上一版 {prev}，当前版本留作上一版，可再次退回。退回后窗口重新打开。',
        'rollback_ok': '退回到 {prev}', 'ok': '好',
        'upgrade_missing': '升级模块 tool_upgrade.py 缺失，请重新解压完整的工具目录',
    },
    'en': {
        'search': 'Search names and folders... (* ? wildcards, ext:pdf, path:, !not, a|b)',
        'col_name': 'Name', 'col_path': 'Path', 'col_size': 'Size', 'col_mtime': 'Modified',
        'open': 'Open', 'open_folder': 'Locate', 'copy_path': 'Copy path', 'copy_file': 'Copy file', 'rescan': 'Rescan',
        'col_locate': 'Locate', 'locate_tip': 'Open the containing folder in the file manager and select the item',
        'locate_item': 'Locate {name}',
        'located_folder': 'Opened the containing folder; the file manager cannot select the item',
        'copied_file': 'File copied: {path}; paste it in a file manager or another program',
        'copy_gone': 'Copy failed: the file no longer exists. Rescan and try again.',
        'loading': 'Loading the index...',
        'first_scan': 'Building the index: {dirs} folders, {files} entries...',
        'scanning': 'Updating the index: {dirs} folders...',
        'results': '{count} results',
        'results_ms': '{count} results ({ms} ms)',
        'entries': '{entries} entries',
        'copied': 'Path copied: {path}',
        'copy_failed': 'Copy failed: the clipboard is unavailable. Select the path and copy it by hand.',
        'open_failed': 'Open failed: {error}. Try opening it from a file manager.',
        'open_no_app': 'Open failed: no program is set to open this kind of file. Right-click it in a file manager '
                       'and choose a program under Open With.',
        'rescan_started': 'Rescan started', 'rescan_busy': 'A scan is running; try again later',
        'search_short': 'Search...',
        'unsaved_q': 'Settings have unsaved changes',
        'unsaved_detail': 'The window opens again with the new version afterwards and these changes are not saved. '
                          'To keep them, choose Cancel, save the settings, then try again.',
        'unsaved_go': 'Continue anyway',
        'gone': 'Open failed: the file no longer exists. The index is updated at the next scan.',
        'unreadable': '{count} folders unreadable',
        'no_match': 'No matches', 'hint_entries': '{count} items', 'hint_scanning': 'Indexing {pct}%',
        'hint_first': 'Indexing, {count} items so far',
        'ver_newest': 'Newest', 'ver_older': 'Newer exists', 'jump_newest': 'Go to the newest version',
        'ver_tip': '{count} similar versions; newest: {path}',
        'ver_skipped': 'Too many results to mark similar versions',
        'settings': 'Settings', 'set_roots': 'Indexed folders', 'set_exclude': 'Excluded',
        'set_exclude_hint': 'Name rule, such as node_modules or *.tmp', 'set_hidden': 'Index hidden files and folders',
        'add_folder': 'Add folder...', 'add': 'Add', 'remove': 'Remove', 'remove_item': 'Remove {item}',
        'defaults': 'Restore defaults', 'cancel': 'Cancel', 'save': 'Save', 'save_anyway': 'Save anyway',
        'set_blocked': 'Save failed: {reason}. Add a folder first.',
        'set_warn': 'Check these before saving; if they are as intended, choose Save anyway:',
        'choose_folder': 'Choose a folder',
        'exclude_this': 'Exclude this folder', 'exclude_parent': 'Exclude the containing folder',
        'exclude_q': 'Exclude {path}?', 'exclude_btn': 'Exclude',
        'exclude_detail': 'The folder and the {count} entries in it are removed from the index and no longer indexed. '
                          'Remove the rule under Excluded in Settings to undo this.',
        'applying': 'Updating the index for the new settings...', 'applied': 'Index updated for the new settings',
        'save_failed': 'Save failed: {error}. Check that the settings folder is writable.',
        'keys': 'Shortcuts', 'key_none': 'None', 'key_press': 'Press the keys... (Esc cancels)', 'key_clear': 'Clear',
        'key_clear_item': 'Clear the shortcut of {action}',
        'key_toggle': 'Show or hide the window (global, a system shortcut)', 'key_locate': 'Locate',
        'key_open': 'Open the selected item (Enter always works)', 'key_copy_file': 'Copy file',
        'key_copy_path': 'Copy path', 'key_settings': 'Open settings', 'key_rescan': 'Rescan',
        'key_focus': 'Go to the search box',
        'key_fixed': '{key} is used by the list (arrows, Enter, Esc and the like) and cannot be a shortcut',
        'key_plain': '{key} has no Ctrl, Alt or Super and would take over typing; add a modifier or use F1 to F12',
        'key_dup': 'Save failed: {a} and {b} have the same shortcut. Change one of them.',
        'key_taken': '{key} is already a desktop shortcut ({name})',
        'key_manual': 'No desktop shortcut settings this tool can write to were found (UKUI or GNOME with gsettings '
                      'is needed). Add the show-or-hide shortcut as a custom shortcut in the system settings, with '
                      'the command: {command}',
        'key_moved': 'The tool was not installed with install.sh, so the shortcut points at this folder; set it '
                     'again after moving the folder.',
        'copy_command': 'Copy command',
        'hotkey_written': 'System shortcut saved: {key}', 'hotkey_removed': 'Show-or-hide shortcut removed from the system',
        'hotkey_failed': 'Save failed: the system shortcut could not be written ({error}). Add it by hand as a '
                         'custom shortcut in the system settings, with the command: {command}',
        'set_match_path': 'Search words also match the path (names of the folders above)',
        'set_columns': 'Column order', 'col_up': 'Move up', 'col_down': 'Move down', 'col_up_item': 'Move {col} up',
        'col_down_item': 'Move {col} down', 'col_defaults': 'Default order',
        'hotkey_default_set': 'Show-or-hide shortcut set to {key}: press it anywhere to open or hide the window; '
                              'change it under Settings > Shortcuts',
        'hotkey_default_taken': 'Setting the default show-or-hide shortcut failed: {key} is already a desktop '
                                'shortcut ({name}). Choose other keys under Settings > Shortcuts > Show or hide.',
        'hotkey_default_manual': 'Setting the default show-or-hide shortcut failed: no desktop shortcut settings '
                                 'this tool can write to were found. Add it as a custom shortcut in the system '
                                 'settings, with the command: {command}',
        'hotkey_default_failed': 'Setting the default show-or-hide shortcut failed: the system shortcut could not '
                                 'be written ({error}). Set it again under Settings > Shortcuts > Show or hide.',
        'set_upgrade': 'Upgrade', 'upgrade_zip': 'Upgrade from a zip…', 'upgrade_dir': 'Upgrade from an unpacked folder…',
        'rollback': 'Roll back to previous version',
        'upgrade_hint': 'The new version replaces this one in place; desktop links, the menu entry and the '
                        'show-or-hide shortcut stay as they are, and the old version is kept for rolling back.',
        'upgrade_now': 'Current version {cur}, previous {prev}', 'upgrade_now_none': 'Current version {cur}, no previous version yet',
        'pick_zip': 'Choose the new release zip', 'pick_dir': 'Choose the unpacked find-fast folder', 'zip_filter': 'Zip files',
        'pick': 'Choose', 'upgrade_title': 'Upgrade find-fast',
        'upgrade_versions': 'Current version {cur} → new version {new} ({kind})', 'upgrade_notes': 'Changes:',
        'upgrade_keep': 'Files kept: {files}', 'upgrade_none': 'none',
        'upgrade_extras': 'Extra files (not carried over; they stay with the previous version, nothing is deleted): {files}',
        'upgrade_more': '… {n} in all', 'upgrade_restart_note': 'The window opens again on the new version.',
        'upgrade_refused': 'Cannot upgrade: {why}. Choose another release zip or folder.',
        'upgrade_failed_title': 'The upgrade did not finish', 'rollback_failed_title': 'The roll-back did not finish',
        'rollback_title': 'Roll back to previous version',
        'rollback_q': 'The current {cur} is replaced by the previous {prev}; the current version becomes the '
                      'previous one, so this can be undone. The window opens again afterwards.',
        'rollback_ok': 'Roll back to {prev}', 'ok': 'OK',
        'upgrade_missing': 'The upgrade module tool_upgrade.py is missing; unpack the whole tool folder again',
    },
}
COLUMNS = [('name', 'col_name'), ('path', 'col_path'), ('size', 'col_size'), ('mtime', 'col_mtime'),
           ('locate', 'col_locate')]
# clipboard formats offered by "copy file": file managers paste the file, other programs the path
COPY_FILE_TARGETS = ('x-special/gnome-copied-files', 'text/uri-list', 'UTF8_STRING', 'text/plain;charset=utf-8',
                     'text/plain', 'TEXT', 'STRING')
LOCATE_ICONS = ('find-location-symbolic', 'edit-find-symbolic', 'folder-open-symbolic', 'folder')
UNFOCUSED_OPACITY = 0.7         # window opacity while another program has the focus (needs a compositor)
COLUMN_WIDTHS = {'name': 300, 'path': 380, 'size': 90, 'mtime': 140, 'locate': 36}
DATA_COLUMNS = ('name', 'path', 'size', 'mtime')   # default order; the locate column always comes last
MIN_COLUMN_WIDTH = 24
DEFAULT_SIZE = (960, 600)
EXPANDED_MIN = 150              # a smaller window height is not remembered as the unfolded height


# ---------------------------------------------------------------- shortcuts
#
# Window shortcuts are kept in config.json under "keys" as GTK accelerator names (such as
# <Primary><Shift>c); an empty string means none. "toggle" is the global shortcut, written into
# the desktop's own custom shortcuts, which runs `find-fast --toggle`.

KEY_DEFAULTS = {
    'locate': '<Primary>Return', 'open': '', 'copy_file': '<Primary>c', 'copy_path': '<Primary><Shift>c',
    'settings': '<Primary>comma', 'rescan': 'F5', 'focus': '<Primary>l', 'toggle': '',
}
DEFAULT_TOGGLE = '<Primary><Alt>space'     # written into the desktop once when no global shortcut was ever set
KEY_ORDER = ('toggle', 'locate', 'open', 'copy_file', 'copy_path', 'settings', 'rescan', 'focus')
LIST_KEYS = ('locate', 'open', 'copy_file', 'copy_path')        # act on the selected row (or the first one)
COPY_KEYS = ('copy_file', 'copy_path')      # in the search box these leave selected text to the box
FIXED_KEYS = {'up', 'down', 'left', 'right', 'return', 'kp_enter', 'escape', 'page_up', 'page_down',
              'home', 'end', 'tab', 'iso_left_tab'}
_MOD_NAMES = {'primary': 'Primary', 'control': 'Primary', 'ctrl': 'Primary', 'ctl': 'Primary', 'shift': 'Shift',
              'alt': 'Alt', 'mod1': 'Alt', 'super': 'Super', 'mod4': 'Super', 'meta': 'Meta', 'hyper': 'Hyper'}
_MOD_ORDER = ('Primary', 'Shift', 'Alt', 'Super', 'Meta', 'Hyper')


def canonical_accel(accel):
    """A comparable form of an accelerator name: modifiers in a fixed order, key in lower case;
    '' for none, None when it cannot be read."""
    if not isinstance(accel, str):
        return None
    accel = accel.strip()
    if not accel:
        return ''
    mods = set()
    pos = 0
    for m in re.finditer(r'<([^<>]+)>', accel):
        if m.start() != pos:
            return None
        name = _MOD_NAMES.get(m.group(1).lower())
        if name is None:
            return None
        mods.add(name)
        pos = m.end()
    key = accel[pos:].strip()
    if not key or '<' in key or '>' in key:
        return None
    return ''.join('<%s>' % m for m in _MOD_ORDER if m in mods) + key.lower()


def is_fixed_key(accel):
    """Arrows, Enter, Esc and other keys the list uses, without Ctrl, Alt or Super."""
    c = canonical_accel(accel)
    if not c:
        return False
    key = re.sub(r'<[^>]+>', '', c)
    return key in FIXED_KEYS and not any(m in c for m in ('<Primary>', '<Alt>', '<Super>'))


def load_keys(config):
    """{action: accelerator} from the settings, defaults for missing or unreadable ones."""
    keys = dict(KEY_DEFAULTS)
    stored = config.other.get('keys')
    if stored is None:
        return keys
    if not isinstance(stored, dict):
        log.warning('settings: "keys" is not an object; default shortcuts used')
        return keys
    for action, accel in stored.items():
        if action not in KEY_DEFAULTS:
            continue
        c = canonical_accel(accel)
        if c is None or is_fixed_key(accel) or not plain_key_ok(accel):
            log.warning('settings: bad shortcut %r for %s; the default is used', accel, action)
            continue
        keys[action] = accel.strip()
    return keys


def plain_key_ok(accel):
    """A shortcut needs Ctrl, Alt or Super, or a function key: a plain key would take over typing."""
    c = canonical_accel(accel)
    if not c:
        return True
    if any(m in c for m in ('<Primary>', '<Alt>', '<Super>')):
        return True
    return re.fullmatch(r'(?:<[^>]+>)*f([1-9]|1[0-9]|2[0-4])', c) is not None


def key_clashes(keys):
    """[(action, other action)] for window shortcuts set to the same keys."""
    seen, out = {}, []
    for action in KEY_ORDER:
        c = canonical_accel(keys.get(action, ''))
        if not c:
            continue
        if c in seen:
            out.append((action, seen[c]))
        else:
            seen[c] = action
    return out


def run_command(args):
    """(exit code, standard output) of a command; (127, '') when it cannot run."""
    try:
        p = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError) as e:
        log.info('%s failed: %s', args[0], e)
        return 127, ''


def _gs_list(text):
    """Accelerators or paths in a gsettings value: a string or a list of strings."""
    return re.findall(r"'((?:[^'\\]|\\.)*)'", text or '')


class DesktopHotkey:
    """The global shortcut as a custom shortcut of the desktop (UKUI or GNOME), through
    gsettings and dconf. Only the entry this tool writes is ever changed. `run` executes a
    command and returns (exit code, output); tests pass a stand-in."""

    GNOME_LIST = ('org.gnome.settings-daemon.plugins.media-keys', 'custom-keybindings')
    GNOME_ENTRY = 'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding'
    GNOME_PATH = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/find-fast/'
    GNOME_SYSTEM = ('org.gnome.desktop.wm.keybindings', 'org.gnome.settings-daemon.plugins.media-keys',
                    'org.gnome.shell.keybindings', 'org.gnome.mutter.keybindings')
    UKUI_ENTRY = 'org.ukui.control-center.keybinding'
    UKUI_DIR = '/org/ukui/desktop/keybindings/'
    UKUI_PATH = UKUI_DIR + 'find-fast/'
    UKUI_SYSTEM = ('org.ukui.SettingsDaemon.plugins.media-keys', 'org.ukui.SettingsDaemon.plugins.keybindings')

    def __init__(self, run=run_command, env=None, which=shutil.which):
        self.run = run
        self.env = os.environ if env is None else env
        self.which = which
        self._schemas = None

    def schemas(self):
        if self._schemas is None:
            code, out = self.run(['gsettings', 'list-schemas'])
            self._schemas = set(out.split()) if code == 0 else set()
        return self._schemas

    def desktop(self):
        """'ukui', 'gnome' or None (no gsettings, or a desktop this tool cannot write to)."""
        if not self.which('gsettings'):
            return None
        names = (self.env.get('XDG_CURRENT_DESKTOP', '') + ':' + self.env.get('DESKTOP_SESSION', '')).lower()
        have = self.schemas()
        if 'ukui' in names and self.UKUI_ENTRY in have and self.which('dconf'):
            return 'ukui'
        if 'gnome' in names and self.GNOME_LIST[0] in have:
            return 'gnome'
        return None

    def _gs(self, *args):
        code, out = self.run(['gsettings'] + list(args))
        return out.strip() if code == 0 else None

    def _set(self, schema_path, key, value):
        code, _ = self.run(['gsettings', 'set', schema_path, key, value])
        if code != 0:
            raise OSError('gsettings set %s %s failed' % (schema_path, key))

    @staticmethod
    def _quote(s):
        return "'" + s.replace('\\', '\\\\').replace("'", "\\'") + "'"

    def write(self, accel, command, name):
        """Add or update this tool's custom shortcut; raises OSError when gsettings fails."""
        kind = self.desktop()
        if kind == 'gnome':
            paths = _gs_list(self._gs('get', *self.GNOME_LIST))
            if self.GNOME_PATH not in paths:
                self._set(self.GNOME_LIST[0], self.GNOME_LIST[1],
                          '[' + ', '.join(self._quote(p) for p in paths + [self.GNOME_PATH]) + ']')
            where = self.GNOME_ENTRY + ':' + self.GNOME_PATH
            for key, value in (('name', name), ('command', command), ('binding', accel)):
                self._set(where, key, self._quote(value))
        elif kind == 'ukui':
            where = self.UKUI_ENTRY + ':' + self.UKUI_PATH
            for key, value in (('name', name), ('action', command), ('binding', accel)):
                self._set(where, key, self._quote(value))
        else:
            raise OSError('no supported desktop')

    def remove(self):
        """Remove this tool's custom shortcut (nothing else); True when there was one."""
        kind = self.desktop()
        if kind == 'gnome':
            paths = _gs_list(self._gs('get', *self.GNOME_LIST))
            if self.GNOME_PATH not in paths:
                return False
            rest = [p for p in paths if p != self.GNOME_PATH]
            self._set(self.GNOME_LIST[0], self.GNOME_LIST[1],
                      '[' + ', '.join(self._quote(p) for p in rest) + ']' if rest else '@as []')
            for key in ('name', 'command', 'binding'):
                self.run(['gsettings', 'reset', self.GNOME_ENTRY + ':' + self.GNOME_PATH, key])
            return True
        if kind == 'ukui':
            code, out = self.run(['dconf', 'list', self.UKUI_DIR])
            if code != 0 or 'find-fast/' not in out.split():
                return False
            self.run(['dconf', 'reset', '-f', self.UKUI_PATH])
            return True
        return False

    def taken(self, accel):
        """Name of a desktop shortcut already on these keys (not this tool's own), or None."""
        want = canonical_accel(accel)
        if not want:
            return None
        kind = self.desktop()
        if kind is None:
            return None
        system = self.GNOME_SYSTEM if kind == 'gnome' else self.UKUI_SYSTEM
        for schema in system:
            if schema not in self.schemas():
                continue
            code, out = self.run(['gsettings', 'list-recursively', schema])
            if code != 0:
                continue
            for line in out.splitlines():
                parts = line.split(None, 2)
                if len(parts) == 3 and any(canonical_accel(a) == want for a in _gs_list(parts[2])):
                    return parts[1]
        if kind == 'gnome':
            paths = [p for p in _gs_list(self._gs('get', *self.GNOME_LIST)) if p != self.GNOME_PATH]
            entries = [(self.GNOME_ENTRY + ':' + p) for p in paths]
        else:
            code, out = self.run(['dconf', 'list', self.UKUI_DIR])
            dirs = [d for d in out.split() if d.endswith('/') and d != 'find-fast/'] if code == 0 else []
            entries = [(self.UKUI_ENTRY + ':' + self.UKUI_DIR + d) for d in dirs]
        for where in entries:
            if any(canonical_accel(a) == want for a in _gs_list(self._gs('get', where, 'binding'))):
                names = _gs_list(self._gs('get', where, 'name'))
                return names[0] if names else where
        return None


def toggle_command(here=None, home=None):
    """(command for the global shortcut, installed): the installed command when this copy is the
    one install.sh made, else python3 with this file's path (which breaks if the folder moves)."""
    here = here or os.path.dirname(os.path.abspath(__file__))
    home = home or core.HOME
    data = os.environ.get('XDG_DATA_HOME') or os.path.join(home, '.local', 'share')
    command = os.path.join(home, '.local', 'bin', 'find-fast')
    if os.path.normpath(here) == os.path.normpath(os.path.join(data, 'find-fast')) and os.path.exists(command):
        return shlex.quote(command) + ' --toggle', True
    return 'python3 ' + shlex.quote(os.path.join(here, 'find_fast.py')) + ' --toggle', False


def valid_order(order):
    """True for a list holding each data column once."""
    return (isinstance(order, list) and len(order) == len(DATA_COLUMNS)
            and all(isinstance(k, str) for k in order) and sorted(order) == sorted(DATA_COLUMNS))


def accel_text(accel):
    """A readable form of an accelerator name without GTK, such as Ctrl+Alt+Space."""
    c = canonical_accel(accel)
    if not c:
        return ''
    names = {'Primary': 'Ctrl', 'Shift': 'Shift', 'Alt': 'Alt', 'Super': 'Super', 'Meta': 'Meta', 'Hyper': 'Hyper'}
    mods = [names[m] for m in re.findall(r'<([^>]+)>', c)]
    key = re.sub(r'<[^>]+>', '', c)
    return '+'.join(mods + [key[:1].upper() + key[1:]])


def ensure_default_toggle(config, hotkey=None, lang=None, refresh=False):
    """Write the default global shortcut into the desktop once, when it was never set (no
    "toggle" among the saved shortcuts) and its keys are free. The settings then record that
    this was done, so a shortcut changed or cleared later is left alone. With refresh, a
    shortcut already set is written again with the current command (install.sh does this, as the
    command changes once the tool is installed). Returns (message, kind) or None."""
    lang = lang or core.ui_language()
    hotkey = hotkey or DesktopHotkey()
    command, _ = toggle_command()
    stored = config.other.get('keys')
    stored = stored if isinstance(stored, dict) else {}
    if config.other.get('toggle_default_done') or 'toggle' in stored:
        accel = stored.get('toggle') if isinstance(stored.get('toggle'), str) else ''
        if refresh and accel and hotkey.desktop() is not None:
            try:
                hotkey.write(accel, command, core.text('app_name', lang))
            except OSError as e:
                log.warning('cannot rewrite the system shortcut: %s', e)
        if not config.other.get('toggle_default_done'):
            config.other['toggle_default_done'] = True
            _save_quietly(config)
        return None
    key = accel_text(DEFAULT_TOGGLE)
    if hotkey.desktop() is None:
        result = (t(lang, 'hotkey_default_manual', command=command), 'warn')
    else:
        owner = hotkey.taken(DEFAULT_TOGGLE)
        if owner:
            result = (t(lang, 'hotkey_default_taken', key=key, name=owner), 'warn')
        else:
            try:
                hotkey.write(DEFAULT_TOGGLE, command, core.text('app_name', lang))
            except OSError as e:
                log.warning('cannot write the system shortcut: %s', e)
                result = (t(lang, 'hotkey_default_failed', error=e), 'bad')
            else:
                keys = dict(stored)
                keys['toggle'] = DEFAULT_TOGGLE
                config.other['keys'] = keys
                result = (t(lang, 'hotkey_default_set', key=key), 'ok')
    config.other['toggle_default_done'] = True
    _save_quietly(config)
    return result


def _save_quietly(config):
    try:
        config.save()
    except OSError as e:
        log.warning('cannot save %s: %s', config.path, e)


def load_ui_state(path):
    """Interface state remembered between runs (column widths, window size, position, sort).
    Missing or bad values are left out, so the defaults apply to them."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning('cannot read %s, using defaults: %s', path, e)
        return {}
    if not isinstance(data, dict):
        log.warning('%s is not an object, using defaults', path)
        return {}
    out, bad = {}, []

    def num(key, lo, hi):
        v = data.get(key)
        if v is None:
            return
        if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
            out[key] = v
        else:
            bad.append(key)

    for key in ('width', 'height'):
        num(key, 100, 20000)
    for key in ('x', 'y'):
        num(key, -100000, 100000)
    for key in ('maximized', 'desc'):
        if key in data:
            if isinstance(data[key], bool):
                out[key] = data[key]
            else:
                bad.append(key)
    if 'sort' in data:
        if data['sort'] in core.SORTS:
            out['sort'] = data['sort']
        else:
            bad.append('sort')
    cols = data.get('columns')
    if isinstance(cols, dict):
        out['columns'] = {}
        for k, v in cols.items():
            if k in COLUMN_WIDTHS and isinstance(v, int) and not isinstance(v, bool) and 0 < v <= 20000:
                out['columns'][k] = max(MIN_COLUMN_WIDTH, v)
            else:
                bad.append('columns.' + str(k))
    elif cols is not None:
        bad.append('columns')
    if 'order' in data:
        if valid_order(data['order']):
            out['order'] = list(data['order'])
        else:
            bad.append('order')
    if bad:
        log.warning('%s: ignoring bad values for %s', path, ', '.join(bad))
    return out
COL_TIP = 5                     # store column holding the row's tooltip
COL_TAG = 6                     # store column holding the similar-version tag
VERSIONS_SYNC = 5000            # results up to this size are grouped at once, larger ones in the background
DEFAULT_DESC = {'name': False, 'path': False, 'size': True, 'mtime': True}

Gtk = Gdk = GLib = Gio = Pango = None


def load_gi():
    """Import GTK 3 through gi; False when python3-gi or GTK 3 is missing."""
    global Gtk, Gdk, GLib, Gio, Pango
    if Gtk is not None:
        return True
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('Gdk', '3.0')
        gi.require_version('Pango', '1.0')
        from gi.repository import Gdk as _Gdk, Gio as _Gio, GLib as _GLib, Gtk as _Gtk, Pango as _Pango
    except (ImportError, ValueError) as e:
        log.info('GTK 3 unavailable: %s', e)
        return False
    Gtk, Gdk, GLib, Gio, Pango = _Gtk, _Gdk, _GLib, _Gio, _Pango
    return True


def available():
    """True when GTK 3 can be imported and a display opened."""
    if not load_gi():
        return False
    ok, _ = Gtk.init_check(sys.argv[:1])
    return bool(ok)


def file_uri(path):
    return 'file://' + urllib.parse.quote(os.fsencode(path))


def t(_lang, _name, **kw):
    """Interface text _name in language _lang, with {placeholders} filled from kw."""
    table = UI.get(_lang, UI['en'])
    return table.get(_name, UI['en'][_name]).format(**kw)


class Window:
    """The search window around an Index. Holds no GTK subclass so it can be built after gi is
    loaded lazily."""

    def __init__(self, app, index, lang=None, state_path=None, notice=None):
        self.app = app
        self.notice = notice            # (text, kind) shown once the index is loaded
        self.pinned = None              # a message kept over searches until the user types or it expires
        self.index = index
        self.lang = lang or core.ui_language()
        # interface state lives beside the settings file
        self.state_path = state_path or os.path.join(os.path.dirname(index.config.path), 'ui-state.json')
        self.ui_state = load_ui_state(self.state_path)
        self.result = None
        self.sort = self.ui_state.get('sort', core.DEFAULT_SORT)
        self.desc = self.ui_state.get('desc', True)
        self.top = 0                    # result row shown first
        self.cur = -1                   # selected result row
        self.rows = 1                   # rows that fit
        self.row_height = 0
        self.filling = False
        self.last_change = 0.0
        self.change_pending = False
        self.stop = threading.Event()
        self.worker = None
        self.message = None             # (text, kind) shown instead of the result count
        self.upgrading = False          # an upgrade or roll-back is being checked, asked or run
        self.query = None               # text of the last search
        self.versions = None            # core.VersionGroups of the result, once worked out
        self.keys = load_keys(index.config)
        self.hotkey = DesktopHotkey()
        self.searches = 0
        self.closed = False             # set when the window is destroyed; late callbacks do nothing
        self.build()

    # ------------------------------------------------------------ layout

    def build(self):
        w = self.win = Gtk.ApplicationWindow(application=self.app)
        w.set_title(core.text('app_name', self.lang))
        st = self.ui_state
        w.set_default_size(st.get('width', DEFAULT_SIZE[0]), st.get('height', DEFAULT_SIZE[1]))
        if st.get('maximized'):
            w.maximize()
        self.size = (st.get('width', DEFAULT_SIZE[0]), st.get('height', DEFAULT_SIZE[1]))
        self.maximized = bool(st.get('maximized'))
        if 'x' in st and 'y' in st and self.can_place(st['x'], st['y']):
            w.move(st['x'], st['y'])
        w.connect('configure-event', self.on_configure)
        w.connect('window-state-event', self.on_window_state)
        w.connect('notify::is-active', lambda *_: GLib.idle_add(self.update_opacity))
        w.set_icon_name('system-search')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        w.add(box)

        top = self.top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        top.set_margin_start(6)
        top.set_margin_end(6)
        top.set_margin_top(4)
        top.set_margin_bottom(4)
        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text(t(self.lang, 'search'))
        self.entry.connect('search-changed', self.on_search_changed)
        self.entry.connect('key-press-event', self.on_entry_key)
        self.entry.connect('activate', lambda *_: self.open_current())
        self.entry.connect('size-allocate', lambda *_: GLib.idle_add(self._hint_after_resize))
        # while the list is folded away, the index state shows at the right end of the search box
        over = Gtk.Overlay()
        over.add(self.entry)
        self.hint = Gtk.Label(xalign=1)
        self.hint.get_style_context().add_class('dim-label')
        self.hint.set_halign(Gtk.Align.END)
        self.hint.set_valign(Gtk.Align.CENTER)
        self.hint.set_margin_end(30)
        self.hint.set_no_show_all(True)
        over.add_overlay(self.hint)
        over.set_overlay_pass_through(self.hint, True)
        top.pack_start(over, True, True, 0)
        self.gear = Gtk.Button.new_from_icon_name('preferences-system-symbolic', Gtk.IconSize.BUTTON)
        self.gear.set_relief(Gtk.ReliefStyle.NONE)
        self.gear.set_tooltip_text(t(self.lang, 'settings'))
        self.gear.get_accessible().set_name(t(self.lang, 'settings'))
        self.gear.connect('clicked', lambda *_: self.open_settings())
        top.pack_start(self.gear, False, False, 0)
        box.pack_start(top, False, False, 0)
        self.settings = None            # the open settings dialog

        row = self.list_area = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(row, True, True, 0)

        # icon name, name, folder, size, time, tooltip (Pango markup), similar-version tag
        self.store = Gtk.ListStore(str, str, str, str, str, str, str)
        tv = self.tree = Gtk.TreeView(model=self.store)
        tv.set_has_tooltip(True)
        tv.connect('query-tooltip', self.on_query_tooltip)
        tv.set_enable_search(False)
        tv.set_headers_clickable(True)
        tv.set_fixed_height_mode(True)
        tv.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        tv.set_vexpand(True)
        tv.set_hexpand(True)
        self.columns = {}
        tv.set_column_drag_function(self.column_drop_ok)
        for i, (key, label) in enumerate(COLUMNS):
            col = Gtk.TreeViewColumn(t(self.lang, label))
            col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            if key == 'locate':
                # a button-like icon at the end of every row
                theme = Gtk.IconTheme.get_default()
                icon = Gtk.CellRendererPixbuf()
                icon.set_padding(2, 1)
                icon.set_property('icon-name', next((n for n in LOCATE_ICONS if theme.has_icon(n)), 'folder'))
                col.pack_start(icon, True)
                head = Gtk.Image.new_from_icon_name(icon.get_property('icon-name'), Gtk.IconSize.MENU)
                head.set_tooltip_text(t(self.lang, 'locate_tip'))
                head.show()
                col.set_widget(head)
                col.set_fixed_width(self.column_width(key))
                self.columns[key] = col
                continue
            col.set_resizable(True)
            col.set_reorderable(True)
            col.set_clickable(True)
            col.connect('clicked', self.on_header, key)
            if key == 'name':
                icon = Gtk.CellRendererPixbuf()
                icon.set_padding(2, 1)
                col.pack_start(icon, False)
                col.add_attribute(icon, 'icon-name', 0)
                tag = self.tag_cell = Gtk.CellRendererText()
                tag.set_padding(2, 1)
                tag.set_property('scale', 0.85)         # dimmed by dim_tags: still read as plain text
                col.pack_start(tag, False)
                col.add_attribute(tag, 'text', COL_TAG)
                col.set_expand(False)
            cell = Gtk.CellRendererText()
            cell.set_padding(4, 1)              # compact rows
            cell.set_property('ellipsize', Pango.EllipsizeMode.MIDDLE if key == 'path' else Pango.EllipsizeMode.END)
            if key in ('size', 'mtime'):
                cell.set_property('xalign', 1.0 if key == 'size' else 0.0)
            col.pack_start(cell, True)
            col.add_attribute(cell, 'text', i + 1)
            col.set_fixed_width(self.column_width(key))
            if key == 'path':
                col.set_expand(True)
            self.columns[key] = col
        for key in list(self.ui_state.get('order', DATA_COLUMNS)) + ['locate']:
            tv.append_column(self.columns[key])
        tv.connect('style-updated', lambda *_: self.dim_tags())
        self.dim_tags()
        tv.connect('scroll-event', self.on_scroll)
        tv.connect('key-press-event', self.on_tree_key)
        tv.connect('button-press-event', self.on_button)
        tv.connect('row-activated', lambda *_: self.open_current())
        tv.get_selection().connect('changed', self.on_selection_changed)
        tv.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, [], Gdk.DragAction.COPY)
        tv.drag_source_add_uri_targets()
        tv.drag_source_add_text_targets()
        tv.connect('drag-data-get', self.on_drag_data_get)

        self.adj = Gtk.Adjustment(value=0, lower=0, upper=0, step_increment=1, page_increment=10, page_size=1)
        self.adj.connect('value-changed', self.on_adj)
        self.scrollbar = Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL, adjustment=self.adj)
        # EXTERNAL: the tree may be shorter than its rows; the store never holds more than fit
        self.sw = Gtk.ScrolledWindow()
        self.sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.EXTERNAL)
        self.sw.add(tv)
        self.sw.connect('size-allocate', self.on_area_allocate)
        over = Gtk.Overlay()
        over.add(self.sw)
        self.empty = Gtk.Label(label=t(self.lang, 'no_match'))
        self.empty.get_style_context().add_class('dim-label')
        self.empty.set_halign(Gtk.Align.CENTER)
        self.empty.set_valign(Gtk.Align.CENTER)
        self.empty.set_no_show_all(True)
        over.add_overlay(self.empty)
        over.set_overlay_pass_through(self.empty, True)
        row.pack_start(over, True, True, 0)
        row.pack_start(self.scrollbar, False, False, 0)

        bar = self.bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.set_margin_start(6)
        bar.set_margin_end(6)
        bar.set_margin_top(2)
        bar.set_margin_bottom(2)
        self.status = Gtk.Label(xalign=0)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_selectable(False)
        self.state = Gtk.Label(xalign=1)
        self.state.set_ellipsize(Pango.EllipsizeMode.START)
        bar.pack_start(self.status, True, True, 0)
        bar.pack_end(self.state, False, False, 0)
        box.pack_start(bar, False, False, 0)

        self.menu = Gtk.Menu()
        for key, cb in (('open_folder', self.open_folder), ('open', self.open_current),
                        ('copy_file', self.copy_file), ('copy_path', self.copy_path)):
            item = Gtk.MenuItem(label=t(self.lang, key))
            item.connect('activate', lambda _i, f=cb: f())
            self.menu.append(item)
        self.menu.append(Gtk.SeparatorMenuItem())
        self.jump_item = Gtk.MenuItem(label=t(self.lang, 'jump_newest'))
        self.jump_item.connect('activate', lambda *_: self.jump_to_newest())
        self.menu.append(self.jump_item)
        self.exclude_item = Gtk.MenuItem(label=t(self.lang, 'exclude_parent'))
        self.exclude_item.connect('activate', lambda *_: self.exclude_current())
        self.menu.append(self.exclude_item)
        item = Gtk.MenuItem(label=t(self.lang, 'rescan'))
        item.connect('activate', lambda *_: self.rescan())
        self.menu.append(item)
        self.menu.show_all()
        self.menu.connect('deactivate', lambda *_: GLib.idle_add(self.update_opacity))

        w.connect('delete-event', self.on_delete)
        w.connect('destroy', lambda *_: setattr(self, 'closed', True))
        self.accel = None
        self.apply_keys(self.keys)
        self.update_sort_indicators()
        w.show_all()
        self.expanded = None
        self.apply_layout()
        self.entry.grab_focus()

    # ------------------------------------------------------------ index lifecycle

    def start(self):
        """Load the cache in the background, then rescan and watch."""
        self.index.on_change = self.on_index_change
        self.set_state(t(self.lang, 'loading'))
        self.worker = threading.Thread(target=self._load_and_refresh, args=(self.stop,), name='index', daemon=True)
        self.worker.start()

    def _load_and_refresh(self, stop):
        loaded = self.index.load()
        GLib.idle_add(self.after_load, loaded)
        if stop.is_set():
            return
        self.index.refresh(stop=stop)
        if stop.is_set():
            return
        watching = self.index.start_watching()
        GLib.idle_add(self.after_refresh, watching)

    def after_load(self, loaded):
        if self.closed:
            return False
        self.run_search()
        self.update_state()
        if self.notice:
            text, kind = self.notice
            self.notice = None
            self.pinned = (text, kind)
            self.show_message(text, kind, seconds=None)
            GLib.timeout_add_seconds(NOTICE_SECONDS, self._unpin, text)
        return False

    def _unpin(self, text):
        if self.pinned is not None and self.pinned[0] == text:
            self.pinned = None
            self._clear_message(text)
        return False

    def after_refresh(self, watching):
        if self.closed:
            return False
        self.run_search(keep=True)
        self.update_state()
        if not watching or (self.index.watcher is not None and self.index.watcher.limited):
            GLib.timeout_add_seconds(RESCAN_EVERY, self.periodic_rescan)
        return False

    def periodic_rescan(self):
        if self.stop.is_set():
            return False
        self.start_refresh()
        return True

    def rescan(self):
        """Rescan asked for by the person (F5, the menu): say whether it started."""
        if self.worker is not None and self.worker.is_alive():
            self.show_message(t(self.lang, 'rescan_busy'), 'info')
            return
        self.start_refresh()
        self.show_message(t(self.lang, 'rescan_started'), 'info')

    def start_refresh(self):
        if self.worker is not None and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._refresh, args=(self.stop,), name='index', daemon=True)
        self.worker.start()

    def _refresh(self, stop):
        self.index.refresh_and_watch(stop=stop)
        GLib.idle_add(self.after_change)

    # ------------------------------------------------------------ shortcuts

    def matches(self, event, action):
        """True when a key event is the shortcut set for action."""
        accel = self.keys.get(action)
        if not accel:
            return False
        keyval, mods = Gtk.accelerator_parse(accel)
        if not keyval:
            return False
        pressed = Gdk.KEY_Return if event.keyval == Gdk.KEY_KP_Enter else event.keyval
        state = int(event.state) & int(Gtk.accelerator_get_default_mod_mask())
        return Gdk.keyval_to_lower(pressed) == Gdk.keyval_to_lower(keyval) and state == int(mods)

    def apply_keys(self, keys):
        """Use these shortcuts: the window-wide ones go into an accelerator group, the list ones
        are checked in the list's key handler."""
        self.keys = dict(keys)
        if self.accel is not None:
            self.win.remove_accel_group(self.accel)
        self.accel = Gtk.AccelGroup()
        self.win.add_accel_group(self.accel)
        calls = {'settings': self.open_settings, 'rescan': self.rescan, 'focus': self.entry.grab_focus}
        for action, call in calls.items():
            keyval, mods = Gtk.accelerator_parse(self.keys.get(action) or '')
            if keyval:
                self.accel.connect(keyval, mods, 0, lambda *_, f=call: (f(), True)[1])

    def toggle(self):
        """The global shortcut: hide the window when it is in front, else bring it forward with
        the search text selected. A hidden window keeps the index up to date."""
        if self.win.get_visible() and self.window_active():
            self.win.hide()
            return
        self.win.show()
        stamp = Gtk.get_current_event_time()
        if stamp:
            self.win.present_with_time(stamp)
        else:
            self.win.present()
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    # ------------------------------------------------------------ settings

    def save_config(self, config):
        """Save settings that do not change the index scope (shortcuts)."""
        try:
            config.save()
        except OSError as e:
            log.warning('cannot save %s: %s', config.path, e)
            self.show_message(t(self.lang, 'save_failed', error=e.strerror or e), 'bad')
            return False
        with self.index.lock:
            self.index.config = config
        return True

    def write_hotkey(self, accel):
        """Put the global shortcut into the desktop's custom shortcuts, or remove it."""
        command, _ = toggle_command()
        if self.hotkey.desktop() is None:
            return False
        try:
            if accel:
                self.hotkey.write(accel, command, core.text('app_name', self.lang))
                keyval, mods = Gtk.accelerator_parse(accel)
                label = Gtk.accelerator_get_label(keyval, mods) if keyval else accel
                self.show_message(t(self.lang, 'hotkey_written', key=label), 'ok')
            else:
                self.hotkey.remove()
                self.show_message(t(self.lang, 'hotkey_removed'), 'ok')
            return True
        except OSError as e:
            log.warning('cannot write the system shortcut: %s', e)
            self.show_message(t(self.lang, 'hotkey_failed', error=e, command=command), 'bad', seconds=15)
            return False

    def open_settings(self):
        if self.settings is not None:
            self.settings.dialog.present()
            return self.settings
        self.settings = SettingsDialog(self, self.index.config, self.index.mounts)
        self.settings.dialog.connect('destroy', lambda *_: setattr(self, 'settings', None))
        self.settings.dialog.show_all()
        self.settings.update_problems([])
        return self.settings

    def apply_scope(self, config):
        """Save a new index scope and use it: a scan in progress is stopped first."""
        try:
            config.save()
        except OSError as e:
            log.warning('cannot save %s: %s', config.path, e)
            self.show_message(t(self.lang, 'save_failed', error=e.strerror or e), 'bad')
            return False
        self.pending_scope = config
        self.stop.set()
        self.show_message(t(self.lang, 'applying'), 'info', seconds=None)
        self._start_pending()
        return True

    def _start_pending(self):
        if self.closed or getattr(self, 'pending_scope', None) is None:
            return False
        if self.worker is not None and self.worker.is_alive():
            GLib.timeout_add(100, self._start_pending)
            return False
        config, self.pending_scope = self.pending_scope, None
        self.stop = threading.Event()
        self.worker = threading.Thread(target=self._reconfigure, args=(config, self.stop), name='index', daemon=True)
        self.worker.start()
        return False

    def _reconfigure(self, config, stop):
        mode = self.index.reconfigure(config, stop=stop)
        if mode != 'stopped' and self.index.watcher is None:
            self.index.start_watching()
        GLib.idle_add(self.after_reconfigure, mode)

    def after_reconfigure(self, mode):
        if self.closed:
            return False
        self.update_state()
        self.run_search(keep=True)
        if mode != 'stopped':
            self.show_message(t(self.lang, 'applied'), 'ok')
        return False

    def exclude_target(self):
        """The folder that 'exclude' would add for the selected row, or None when it is an
        indexed folder itself (or outside them)."""
        if self.result is None or not 0 <= self.cur < self.count():
            return None, False
        name, folder, size, _ = self.result.row(self.cur)
        is_dir = size < 0
        target = os.path.join(folder, name) if is_dir else folder
        roots = self.index.config.resolved_roots()
        if target in roots or not any(core.under(target, r) for r in roots):
            return None, is_dir
        return target, is_dir

    def exclude_current(self):
        target, _ = self.exclude_target()
        if target is None:
            return
        shown = core.display(target)

        def done(ok):
            if not ok:
                return
            c = self.index.config
            roots, exclude = core.tidy_scope(c.roots, c.exclude + [core.to_tilde(target)])
            self.apply_scope(c.with_scope(roots, exclude, c.hidden))

        count = '{:,}'.format(self.index.count_under(target))
        self.confirm(t(self.lang, 'exclude_q', path=shown), t(self.lang, 'exclude_detail', count=count),
                     t(self.lang, 'exclude_btn'), done)

    def confirm(self, text, detail, ok_label, callback):
        """Ask with a modal dialog; callback(True) when ok_label was chosen. Tests replace this."""
        d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE, text=text)
        if detail.count('\n') > CONFIRM_LINES or len(detail) > CONFIRM_CHARS:
            # a long text (the upgrade report) scrolls instead of growing past the screen
            lab = Gtk.Label(label=detail, xalign=0, yalign=0)
            lab.set_line_wrap(True)
            lab.set_selectable(True)
            lab.set_max_width_chars(70)
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.set_propagate_natural_height(True)
            sw.set_max_content_height(CONFIRM_HEIGHT)
            sw.add(lab)
            d.get_message_area().pack_start(sw, True, True, 0)
            self.confirm_scroll = sw
        else:
            d.format_secondary_text(detail)
        d.add_button(t(self.lang, 'cancel'), Gtk.ResponseType.CANCEL)
        d.add_button(ok_label, Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.CANCEL)

        def answer(dialog, response):
            dialog.destroy()
            callback(response == Gtk.ResponseType.OK)

        d.connect('response', answer)
        d.show_all()

    # ------------------------------------------------------------ upgrade in place

    def alert(self, text, detail):
        """An error dialog with one button. Tests replace this."""
        d = Gtk.MessageDialog(transient_for=self.win, modal=True, message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.NONE, text=text)
        d.format_secondary_text(detail)
        d.add_button(t(self.lang, 'ok'), Gtk.ResponseType.OK)
        d.connect('response', lambda dialog, _r: dialog.destroy())
        d.show_all()

    def upgrade_report(self, rep):
        lang = self.lang

        def files(items, total):
            if not items:
                return t(lang, 'upgrade_none')
            text = '、'.join(items[:12]) if lang == 'zh' else ', '.join(items[:12])
            return text + (t(lang, 'upgrade_more', n=total) if total > 12 else '')
        lines = [t(lang, 'upgrade_versions', cur=rep['current'], new=rep['new'], kind=rep['kind_text'])]
        if rep['warning']:
            lines += ['', rep['warning']]
        if rep['notes']:
            lines += ['', t(lang, 'upgrade_notes')]
            for n in rep['notes'][:10]:
                lines += ['%s: %s' % (n['version'], n['text'][:600])]
        lines += ['', t(lang, 'upgrade_keep', files=files(rep['keep'], len(rep['keep']))),
                  t(lang, 'upgrade_extras', files=files(rep['extras'], rep['extras_total'])),
                  '', t(lang, 'upgrade_restart_note')]
        return '\n'.join(lines)

    def set_upgrading(self, on):
        self.upgrading = on
        if self.settings is not None:
            self.settings.refill_upgrade()

    def upgrade_stage(self, key):
        """Called from the worker thread with a stage key of the upgrade module."""
        GLib.idle_add(self.show_message, tool_upgrade.text(self.lang, key), 'info', None)

    def upgrade_from(self, path):
        """Check the chosen release in the background, then ask; the search box stays usable."""
        if self.upgrading or tool_upgrade is None:
            return
        self.set_upgrading(True)
        self.upgrade_stage('stage_check')

        def work():
            rep = tool_upgrade.inspect(TOOL_DIR, path, UPGRADE_MAIN, self.lang)
            GLib.idle_add(self.confirm_upgrade, rep, path)
        threading.Thread(target=work, daemon=True).start()

    def confirm_upgrade(self, rep, path):
        lang = self.lang
        if not rep['ok']:
            self.set_upgrading(False)
            why = t(lang, 'upgrade_refused', why=('；' if lang == 'zh' else '; ').join(rep['errors']))
            self.show_message(why, 'bad', 10)
            self.alert(t(lang, 'upgrade_title'), why)
            return False
        self.message = None
        self.update_status()

        def answer(ok):
            if not ok:
                self.set_upgrading(False)
                return
            threading.Thread(target=self.run_upgrade, args=(path,), daemon=True).start()
        self.confirm(t(lang, 'upgrade_title'), self.upgrade_report(rep), rep['confirm'], answer)
        return False

    def run_upgrade(self, path):
        try:
            res = tool_upgrade.apply(TOOL_DIR, path, UPGRADE_MAIN, self.lang, progress=self.upgrade_stage)
        except tool_upgrade.UpgradeError as e:
            GLib.idle_add(self.upgrade_failed, 'upgrade_failed_title', tool_upgrade.sentence(e.message(self.lang), self.lang))
            return
        GLib.idle_add(self.upgrade_done, res['message'])

    def ask_rollback(self):
        if self.upgrading or tool_upgrade is None:
            return
        info = tool_upgrade.rollback_info(TOOL_DIR)
        if not info['available']:
            return
        self.set_upgrading(True)

        def answer(ok):
            if not ok:
                self.set_upgrading(False)
                return

            def work():
                try:
                    res = tool_upgrade.rollback(TOOL_DIR, self.lang, progress=self.upgrade_stage)
                except tool_upgrade.UpgradeError as e:
                    GLib.idle_add(self.upgrade_failed, 'rollback_failed_title',
                                  tool_upgrade.sentence(e.message(self.lang), self.lang))
                    return
                GLib.idle_add(self.upgrade_done, res['message'])
            threading.Thread(target=work, daemon=True).start()
        self.confirm(t(self.lang, 'rollback_title'), t(self.lang, 'rollback_q', cur=info['current'], prev=info['previous']),
                     t(self.lang, 'rollback_ok', prev=info['previous']), answer)

    def upgrade_failed(self, title_key, why):
        self.set_upgrading(False)
        self.show_message(why, 'bad', 15)
        self.alert(t(self.lang, title_key), why)
        return False

    def upgrade_done(self, message):
        """The folder now holds the other version: close and let main() start it again."""
        self.show_message(message + ' ' + tool_upgrade.text(self.lang, 'restarting'), 'ok', None)
        self.app.restart_after_upgrade = True
        GLib.timeout_add(600, self.restart_now)
        return False

    def restart_now(self):
        self.save_ui_state()
        self.stop.set()
        if self.settings is not None:
            self.settings.dialog.destroy()
        self.win.hide()
        self.quit()
        return False

    def on_index_change(self):
        """From any thread: the index or its progress changed."""
        GLib.idle_add(self.after_change)

    def after_change(self):
        if self.closed:
            return False
        self.update_state()
        if self.index.state == 'scanning':
            return False
        now = time.monotonic()
        if now - self.last_change < CHANGE_THROTTLE:
            if not self.change_pending:
                self.change_pending = True
                GLib.timeout_add(int(CHANGE_THROTTLE * 1000), self._pending_change)
            return False
        self.last_change = now
        self.run_search(keep=True)
        return False

    def _pending_change(self):
        self.change_pending = False
        if self.closed:
            return False
        self.last_change = time.monotonic()
        self.run_search(keep=True)
        return False

    def on_delete(self, *_):
        """Close: remember the interface state, stop a scan in progress; a cache being written
        is finished first."""
        self.save_ui_state()
        self.stop.set()
        self.win.hide()
        w = self.worker
        if w is not None and w.is_alive():
            def wait():
                if w.is_alive():
                    return True
                self.quit()
                return False
            GLib.timeout_add(100, wait)
            return True
        self.quit()
        return True

    def quit(self):
        self.index.close()
        self.app.quit()

    # ------------------------------------------------------------ interface state and opacity

    def column_width(self, key):
        return self.ui_state.get('columns', {}).get(key, COLUMN_WIDTHS[key])

    def column_order(self):
        """The data columns as shown, left to right."""
        keys = {c: k for k, c in self.columns.items()}
        return [keys[c] for c in self.tree.get_columns() if keys.get(c) in DATA_COLUMNS]

    def set_column_order(self, order):
        """Show the data columns in this order, the locate column last."""
        if not valid_order(list(order)):
            return
        prev = None
        for key in order:
            self.tree.move_column_after(self.columns[key], prev)
            prev = self.columns[key]

    def column_drop_ok(self, _tree, column, prev, nxt):
        """Columns dragged by their headers stay in front of the locate column."""
        locate = self.columns.get('locate')
        return column is not locate and prev is not locate and nxt is not None

    @staticmethod
    def on_wayland():
        return 'wayland' in type(Gdk.Display.get_default()).__name__.lower()

    def can_place(self, x, y):
        """True when a window corner at (x, y) is on a monitor and the desktop lets programs
        place windows (not under Wayland)."""
        if self.on_wayland():
            return False
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            g = display.get_monitor(i).get_geometry()
            if g.x <= x < g.x + g.width and g.y <= y < g.y + g.height:
                return True
        return False

    def on_configure(self, win, _event):
        if self.maximized:
            return False
        width, height = win.get_size()
        # the folded height is never remembered; only the height with the list shown
        if self.expanded and height >= EXPANDED_MIN:
            self.size = (width, height)
        else:
            self.size = (width, self.size[1])
        return False

    def on_window_state(self, _win, event):
        maximized = bool(event.new_window_state & Gdk.WindowState.MAXIMIZED)
        if maximized != self.maximized:
            self.maximized = maximized
            GLib.idle_add(lambda: (self.closed or self.apply_layout(), False)[1])
        return False

    # ------------------------------------------------------------ folding the list

    def want_expanded(self):
        """The list shows while there is search text, and always in a maximised window."""
        return bool(self.entry.get_text()) or self.maximized

    def apply_layout(self):
        """Fold the result list and status bar away under an empty search box, or unfold them
        to the remembered height; the window keeps its width and place."""
        want = self.want_expanded()
        if want != self.expanded:
            if self.expanded:
                for c in self.columns.values():     # keep widths dragged by hand
                    if c.get_width() > 0:
                        c.set_fixed_width(c.get_width())
            self.expanded = want
            self.list_area.set_visible(want)
            self.bar.set_visible(want)
            self.hint.set_visible(not want)
            if not self.maximized:
                self.win.resize(self.size[0], self.size[1] if want else 1)
        self.empty.set_visible(want and self.result is not None and self.count() == 0 and self.message is None
                               and bool(self.query))
        self.update_hint()

    def update_hint(self):
        """The text at the right of the search box while folded: a message for a few seconds,
        else the index state; its tooltip has the whole state with the version."""
        if self.expanded:
            self.entry.set_tooltip_text(None)
            return
        ctx = self.hint.get_style_context()
        for c in ('error', 'warning'):
            ctx.remove_class(c)
        if self.message is not None:
            text, kind = self.message
            if kind in ('bad', 'warn'):
                ctx.add_class('error' if kind == 'bad' else 'warning')
        else:
            text = self.hint_state()
        self.hint.set_text(text)
        short = self.placeholder_short()
        self.entry.set_placeholder_text(t(self.lang, 'search_short' if short else 'search'))
        tip = self.state.get_text()
        if short:
            tip = t(self.lang, 'search') + ('\n' + tip if tip else '')
        self.entry.set_tooltip_text(tip or None)

    def placeholder_short(self):
        """True when the whole search hint and the state text at its right would overlap."""
        width = self.entry.get_allocated_width()
        if width <= 1 or not self.hint.get_text():
            return False
        hint_w = self.entry.create_pango_layout(t(self.lang, 'search')).get_pixel_size()[0]
        state_w = self.hint.create_pango_layout(self.hint.get_text()).get_pixel_size()[0]
        return hint_w + state_w + HINT_GAP > width

    def _hint_after_resize(self):
        if not self.closed and not self.expanded:
            self.update_hint()
        return False

    def hint_state(self):
        st = self.index.status()
        if st['state'] == 'scanning':
            dirs, files = st['progress']
            known = len(self.index.base.dirs)
            if known:
                return t(self.lang, 'hint_scanning', pct=min(99, dirs * 100 // known))
            return t(self.lang, 'hint_first', count='{:,}'.format(files))
        if st['state'] == 'empty':
            return t(self.lang, 'loading')
        return t(self.lang, 'hint_entries', count='{:,}'.format(st['entries']))

    def ui_state_now(self):
        st = {'width': self.size[0], 'height': self.size[1], 'maximized': self.maximized,
              'sort': self.sort, 'desc': self.desc,
              'columns': {k: (c.get_width() if self.expanded else 0) or c.get_fixed_width()
                          for k, c in self.columns.items()},
              'order': self.column_order()}
        if not self.on_wayland() and not self.maximized:
            st['x'], st['y'] = self.win.get_position()
        return st

    def save_ui_state(self):
        try:
            core.write_private(self.state_path, json.dumps(self.ui_state_now(), indent=2).encode('utf-8'))
        except OSError as e:
            log.warning('cannot write %s: %s', self.state_path, e)

    def composited(self):
        return self.win.get_screen().is_composited()

    def window_active(self):
        return self.win.is_active()

    def own_popup_active(self):
        """The context menu or a dialog of this window is in use."""
        if self.menu.get_visible():
            return True
        return any(top.is_active() and top.get_transient_for() is self.win for top in Gtk.Window.list_toplevels())

    def update_opacity(self):
        """Fade the window while another program has the focus; never without a compositor."""
        if self.closed:
            return False
        if not self.composited():
            if not getattr(self, 'opacity_logged', False):
                log.debug('no compositor; the window stays opaque')
                self.opacity_logged = True
            Gtk.Widget.set_opacity(self.win, 1.0)
            return False
        away = not self.window_active() and not self.own_popup_active()
        Gtk.Widget.set_opacity(self.win, UNFOCUSED_OPACITY if away else 1.0)
        return False

    # ------------------------------------------------------------ search

    def on_search_changed(self, *_):
        if self.result is not None and self.entry.get_text() == self.query:
            return                      # searched already: an action ran the search before the delay ended
        self.pinned = None
        self.run_search()

    def sync_search(self):
        """Run the search now when the box holds text not searched yet, so that an action right
        after typing works on the new result and not the previous one."""
        if self.entry.get_text() != self.query or self.result is None:
            self.pinned = None
            self.run_search()

    def target_row(self):
        """The selected row for an action, else the first row; -1 without results."""
        self.sync_search()
        if 0 <= self.cur < self.count():
            return self.cur
        if self.count():
            self.scroll_to(0)
            return self.cur
        return -1

    def run_search(self, keep=False):
        """Search for the entry text. keep: stay on the selected path and scroll position."""
        keep_path = self.current_path() if keep else None
        top = self.top if keep else 0
        self.query = self.entry.get_text()
        self.searches += 1
        try:
            self.result = self.index.search(self.query, self.sort, self.desc)
            self.message = self.pinned
        except core.QueryError as e:
            self.result = None
            self.message = (str(e), 'warn')
        n = self.count()
        self.top = max(0, min(top, n - self.rows))
        self.cur = -1
        if keep_path is not None:
            for k in range(self.top, min(n, self.top + self.rows)):
                if self.result.path(k) == keep_path:
                    self.cur = k
                    break
        self.start_versions()
        self.sync_adjustment()
        self.fill()
        self.update_status()

    def start_versions(self):
        """Group similar versions in the result: small results at once, others in the background
        (the marks appear when done; a newer search makes the work stop)."""
        res = self.result
        self.versions = None
        if res is None:
            return
        if len(res) <= VERSIONS_SYNC or len(res) > core.VERSION_GROUP_LIMIT:
            self.versions = core.VersionGroups(res)
            return

        def work():
            groups = core.VersionGroups(res, stop=lambda: self.result is not res or self.closed)
            GLib.idle_add(done, groups)

        def done(groups):
            if not self.closed and self.result is res and not groups.skipped:
                self.versions = groups
                self.fill()
            return False
        threading.Thread(target=work, name='versions', daemon=True).start()

    def jump_to_newest(self):
        if self.versions is None:
            return
        k = self.versions.newest(self.cur)
        if k is not None:
            self.scroll_to(k)

    def count(self):
        return len(self.result) if self.result is not None else 0

    def on_header(self, _col, key):
        if self.sort == key:
            self.desc = not self.desc
        else:
            self.sort = key
            self.desc = DEFAULT_DESC[key]
        self.update_sort_indicators()
        self.run_search()

    def update_sort_indicators(self):
        for key, col in self.columns.items():
            col.set_sort_indicator(key == self.sort)
            if key == self.sort:
                col.set_sort_order(Gtk.SortType.DESCENDING if self.desc else Gtk.SortType.ASCENDING)

    # ------------------------------------------------------------ virtual list

    def measure_row_height(self):
        """Height of a row as drawn; an estimate until a row has been shown."""
        if len(self.store) and self.tree.get_realized():
            h = self.tree.get_background_area(Gtk.TreePath.new_first(), self.columns['name']).height
            if h > 0:
                return h, True
        _x, _y, _w, h = self.columns['name'].cell_get_size()
        return max(h, 24), False

    def on_area_allocate(self, _sw, alloc):
        self.area_height = alloc.height
        self.update_rows()

    def update_rows(self):
        if self.closed:
            return
        h, exact = self.measure_row_height()
        if exact:
            self.row_height = h
        h = self.row_height or h
        header = self.columns['name'].get_button().get_allocated_height() if self.tree.get_headers_visible() else 0
        rows = max(1, (getattr(self, 'area_height', 0) - header) // h)
        if rows != self.rows:
            self.rows = rows
            GLib.idle_add(self._after_resize)

    def _after_resize(self):
        if self.closed:
            return False
        n = self.count()
        self.top = max(0, min(self.top, n - self.rows))
        self.sync_adjustment()
        self.fill()
        return False

    def sync_adjustment(self):
        n = self.count()
        self.filling = True
        self.adj.configure(self.top, 0, max(n, 1), 1, max(1, self.rows - 1), min(max(n, 1), self.rows))
        self.filling = False
        self.scrollbar.set_visible(n > self.rows)

    def on_adj(self, adj):
        if self.filling:
            return
        top = int(round(adj.get_value()))
        if top != self.top:
            self.top = top
            self.fill()

    def fill(self):
        """Put the visible rows of the result into the store."""
        if self.closed:
            return
        res = self.result
        n = self.count()
        end = min(n, self.top + self.rows)
        self.filling = True
        try:
            store = self.store
            want = end - self.top
            while len(store) > want:
                store.remove(store.get_iter(len(store) - 1))
            for j, k in enumerate(range(self.top, end)):
                name, folder, size, mtime = res.row(k)
                mark = self.versions.mark(k) if self.versions is not None else None
                values = ['folder' if size < 0 else 'text-x-generic', core.display(name), core.display(folder),
                          core.human_size(size), core.human_time(mtime), self.tooltip(k, name, folder),
                          t(self.lang, 'ver_' + mark) if mark else '']
                if j < len(store):
                    store.set_row(store.get_iter(j), values)
                else:
                    store.append(values)
            if want and not self.row_height:
                GLib.idle_add(lambda: (self.closed or self.update_rows(), False)[1])
            sel = self.tree.get_selection()
            if self.top <= self.cur < end:
                path = Gtk.TreePath.new_from_indices([self.cur - self.top])
                sel.select_path(path)
                self.tree.set_cursor(path, None, False)
            else:
                sel.unselect_all()
        finally:
            self.filling = False

    def tooltip(self, k, name, folder):
        """Tooltip of result row k: the full path, and for a similar version the size of its group
        and the newest one; escaped for Pango markup."""
        text = core.display(os.path.join(folder, name))
        v = self.versions
        if v is not None and v.mark(k):
            text += '\n' + t(self.lang, 'ver_tip', count=v.size(k), path=core.display(self.result.path(v.newest(k))))
        return GLib.markup_escape_text(text, -1)

    def tooltip_markup(self, j, key):
        """Tooltip of shown row j over column key: 'Locate <name>' over the locate column, the
        row's tooltip (full path) elsewhere."""
        if not 0 <= j < len(self.store):
            return None
        if key == 'locate':
            return GLib.markup_escape_text(t(self.lang, 'locate_item', name=self.store[j][1]), -1)
        return self.store[j][COL_TIP]

    def on_query_tooltip(self, tv, x, y, keyboard, tooltip):
        ok, bx, by, _model, path, _it = tv.get_tooltip_context(x, y, keyboard)
        if not ok or path is None:
            return False
        key = None
        if not keyboard:
            hit = tv.get_path_at_pos(bx, by)
            if hit is not None:
                key = next((k for k, c in self.columns.items() if c is hit[1]), None)
        markup = self.tooltip_markup(path.get_indices()[0], key)
        if not markup:
            return False
        tooltip.set_markup(markup)
        if key == 'locate':
            tv.set_tooltip_cell(tooltip, path, self.columns['locate'], None)
        else:
            tv.set_tooltip_row(tooltip, path)
        return True

    def scroll_to(self, k):
        """Make result row k visible and selected."""
        n = self.count()
        if n == 0:
            return
        k = max(0, min(n - 1, k))
        self.cur = k
        if k < self.top:
            self.top = k
        elif k >= self.top + self.rows:
            self.top = k - self.rows + 1
        self.filling = True
        self.adj.set_value(self.top)
        self.filling = False
        self.fill()

    def dim_tags(self):
        """The version tags in the theme's text colour, faded: a set colour, not an insensitive
        cell, so that screen readers do not call them unavailable."""
        color = self.tree.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        color.alpha *= TAG_ALPHA
        self.tag_cell.set_property('foreground-rgba', color)

    def on_scroll(self, _tv, event):
        ok, dx, dy = event.get_scroll_deltas()
        if ok and dy:
            delta = int(round(dy * WHEEL_ROWS)) or (1 if dy > 0 else -1)
        elif event.direction == Gdk.ScrollDirection.UP:
            delta = -WHEEL_ROWS
        elif event.direction == Gdk.ScrollDirection.DOWN:
            delta = WHEEL_ROWS
        else:
            return False
        self.adj.set_value(max(0, min(self.adj.get_upper() - self.adj.get_page_size(), self.top + delta)))
        return True

    def on_selection_changed(self, sel):
        if self.filling:
            return
        model, it = sel.get_selected()
        if it is not None:
            self.cur = self.top + model.get_path(it).get_indices()[0]

    def current_path(self):
        if self.result is not None and 0 <= self.cur < self.count():
            return self.result.path(self.cur)
        return None

    # ------------------------------------------------------------ input

    def on_entry_key(self, _entry, event):
        key = event.keyval
        if key == Gdk.KEY_Escape:
            if self.entry.get_text():
                self.entry.set_text('')
            elif self.keys.get('toggle'):
                self.hide_window()          # the global shortcut brings it back at once
            else:
                self.on_delete()
            return True
        if key in (Gdk.KEY_Down, Gdk.KEY_Page_Down):
            self.sync_search()
            if self.count():
                self.tree.grab_focus()
                self.scroll_to(max(self.cur, 0) if self.cur >= 0 else 0)
                return True
            return False
        for action in LIST_KEYS:
            if self.matches(event, action):
                if action in COPY_KEYS and self.entry.get_selection_bounds():
                    return False            # copy the text selected in the box
                self.list_actions()[action]()
                return True
        return False

    def list_actions(self):
        return {'locate': self.open_folder, 'open': self.open_current, 'copy_file': self.copy_file,
                'copy_path': self.copy_path}

    def hide_window(self):
        """Hide instead of closing: the index stays in memory and up to date."""
        self.save_ui_state()
        self.win.hide()

    def on_tree_key(self, _tv, event):
        key = event.keyval
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        page = max(1, self.rows - 1)
        moves = {Gdk.KEY_Up: -1, Gdk.KEY_Down: 1, Gdk.KEY_Page_Up: -page, Gdk.KEY_Page_Down: page}
        if key in moves:
            if key == Gdk.KEY_Up and self.cur <= 0:
                self.entry.grab_focus()
                return True
            self.scroll_to(max(self.cur, 0) + moves[key])
            return True
        if key == Gdk.KEY_Home:
            self.scroll_to(0)
            return True
        if key == Gdk.KEY_End:
            self.scroll_to(self.count() - 1)
            return True
        actions = self.list_actions()
        for action in LIST_KEYS:
            if self.matches(event, action):
                actions[action]()
                return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not ctrl:
            self.open_current()
            return True
        if key == Gdk.KEY_Menu or (shift and key == Gdk.KEY_F10):
            self.popup_menu(None)
            return True
        if key == Gdk.KEY_Escape:
            self.entry.grab_focus()
            return True
        uni = Gdk.keyval_to_unicode(key)
        if uni and not ctrl and chr(uni).isprintable():
            self.entry.grab_focus_without_selecting()
            pos = self.entry.insert_text(chr(uni), self.entry.get_text_length())
            self.entry.set_position(pos if isinstance(pos, int) else -1)
            return True
        return False

    def on_button(self, tv, event):
        hit = tv.get_path_at_pos(int(event.x), int(event.y))
        if hit is None:
            return False
        k = self.top + hit[0].get_indices()[0]
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS and hit[1] is self.columns['locate']:
            self.cur = k
            self.fill()
            self.open_folder()
            return True
        if event.button == 3:
            self.cur = k
            self.fill()
            self.popup_menu(event)
            return True
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.cur = k
            self.open_current()
            return True
        return False

    def popup_menu(self, event):
        if self.cur < 0:
            return
        self.jump_item.set_visible(self.versions is not None and self.versions.mark(self.cur) == 'older')
        target, is_dir = self.exclude_target()
        self.exclude_item.set_label(t(self.lang, 'exclude_this' if is_dir else 'exclude_parent'))
        self.exclude_item.set_visible(target is not None)
        if event is not None:
            self.menu.popup_at_pointer(event)
            return
        rect = None
        if self.top <= self.cur < self.top + len(self.store):
            rect = self.tree.get_cell_area(Gtk.TreePath.new_from_indices([self.cur - self.top]),
                                           self.columns['name'])
        if rect is not None and rect.height > 0:
            # below the selected row, at the left of its name (bin window coordinates)
            rect.x, rect.width = rect.x + 24, 1
            self.menu.popup_at_rect(self.tree.get_bin_window(), rect, Gdk.Gravity.SOUTH_WEST,
                                    Gdk.Gravity.NORTH_WEST, None)
        else:
            self.menu.popup_at_widget(self.tree, Gdk.Gravity.CENTER, Gdk.Gravity.NORTH_WEST, None)

    def on_drag_data_get(self, _tv, _ctx, data, info, _time):
        path = self.current_path()
        if path is None:
            return
        if data.get_target().name() == 'text/uri-list':
            data.set_uris([file_uri(path)])
        else:
            data.set_text(core.display(path), -1)

    # ------------------------------------------------------------ actions

    def open_uri(self, uri):
        """Open with the desktop's default application. Kept separate so tests can replace it."""
        Gtk.show_uri_on_window(self.win, uri, Gtk.get_current_event_time())

    def open_current(self):
        if self.target_row() < 0:
            return
        path = self.current_path()
        if not os.path.lexists(path):
            self.show_message(t(self.lang, 'gone'), 'bad')
            return
        try:
            self.open_uri(file_uri(path))
        except Exception as e:  # GLib.Error and OSError alike
            self.show_message(self.open_error(e), 'bad')

    def open_folder(self):
        """Locate: show the item selected in the file manager, else open its folder."""
        if self.target_row() < 0:
            return
        path = self.current_path()
        try:
            if not self.show_in_file_manager(path):
                self.open_uri(file_uri(os.path.dirname(path)))
                self.show_message(t(self.lang, 'located_folder'), 'info')
        except Exception as e:
            self.show_message(self.open_error(e), 'bad')

    def open_error(self, e):
        """The message for a failed open: no program for the file type has its own words."""
        io = isinstance(e, GLib.Error) and e.domain == GLib.quark_to_string(Gio.io_error_quark())
        if io and e.code == Gio.IOErrorEnum.NOT_SUPPORTED:
            return t(self.lang, 'open_no_app')
        return t(self.lang, 'open_failed', error=getattr(e, 'message', None) or e)

    def show_in_file_manager(self, path):
        """Ask the file manager to show the item selected (org.freedesktop.FileManager1)."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call_sync('org.freedesktop.FileManager1', '/org/freedesktop/FileManager1',
                          'org.freedesktop.FileManager1', 'ShowItems',
                          GLib.Variant('(ass)', ([file_uri(path)], '')), None, Gio.DBusCallFlags.NONE, 3000, None)
            return True
        except Exception as e:
            log.info('FileManager1 unavailable: %s', e)
            return False

    def copy_file(self):
        """Put the selected file (or folder) itself on the clipboard: file managers paste the
        item, other programs get its path."""
        if self.target_row() < 0:
            return
        path = self.current_path()
        if not os.path.lexists(path):
            self.show_message(t(self.lang, 'copy_gone'), 'bad')
            return
        try:
            if not getattr(self, 'clip_targets', None):
                self.clip_targets = [Gdk.Atom.intern(n, False) for n in COPY_FILE_TARGETS]
                Gtk.selection_clear_targets(self.win, Gdk.SELECTION_CLIPBOARD)
                for i, atom in enumerate(self.clip_targets):
                    Gtk.selection_add_target(self.win, Gdk.SELECTION_CLIPBOARD, atom, i)
                self.win.connect('selection-get', self.on_selection_get)
            self.clip_path = path
            if not Gtk.selection_owner_set(self.win, Gdk.SELECTION_CLIPBOARD, Gtk.get_current_event_time()):
                raise RuntimeError('clipboard refused')
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            cb.set_can_store([Gtk.TargetEntry.new(n, 0, i) for i, n in enumerate(COPY_FILE_TARGETS)])
            self.show_message(t(self.lang, 'copied_file', path=core.display(path)), 'ok')
        except Exception as e:
            log.warning('copy file failed: %s', e)
            self.show_message(t(self.lang, 'copy_failed'), 'bad')

    def on_selection_get(self, _widget, data, _info, _time):
        path = getattr(self, 'clip_path', None)
        if path is None:
            return
        uri = file_uri(path)
        name = data.get_target().name()
        if name == 'x-special/gnome-copied-files':
            data.set(data.get_target(), 8, ('copy\n' + uri).encode('ascii'))
        elif name == 'text/uri-list':
            data.set(data.get_target(), 8, (uri + '\r\n').encode('ascii'))
        else:
            data.set_text(core.display(path), -1)

    def copy_path(self):
        if self.target_row() < 0:
            return
        path = self.current_path()
        try:
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            cb.set_text(core.display(path), -1)
            cb.store()
            self.show_message(t(self.lang, 'copied', path=core.display(path)), 'ok')
        except Exception as e:
            log.warning('copy failed: %s', e)
            self.show_message(t(self.lang, 'copy_failed'), 'bad')

    # ------------------------------------------------------------ status

    def show_message(self, text, kind, seconds=4):
        """Show text instead of the result count; seconds=None keeps it until the next message."""
        self.message = (text, kind)
        self.update_status()
        if seconds is not None:
            GLib.timeout_add_seconds(seconds, self._clear_message, text)

    def _clear_message(self, text):
        if self.message is not None and self.message[0] == text:
            self.message = None
            self.update_status()
        return False

    def update_status(self):
        if getattr(self, 'expanded', None) is not None:
            self.apply_layout()
        if self.message is not None:
            text, kind = self.message
            self.status.set_text(text)
            ctx = self.status.get_style_context()
            for c in ('error', 'warning'):
                ctx.remove_class(c)
            if kind in ('bad', 'warn'):
                ctx.add_class('error' if kind == 'bad' else 'warning')
            return
        for c in ('error', 'warning'):
            self.status.get_style_context().remove_class(c)
        if self.result is None:
            self.status.set_text('')
            return
        text = t(self.lang, 'results_ms', count='{:,}'.format(self.count()), ms=self.result.ms)
        if self.versions is not None and self.versions.skipped:
            text += ' · ' + t(self.lang, 'ver_skipped')
        self.status.set_text(text)

    def set_state(self, text):
        self.state.set_text(text)

    def update_state(self):
        st = self.index.status()
        if st['state'] == 'scanning':
            dirs, files = st['progress']
            key = 'first_scan' if not self.index.base.n and not self.index.extra else 'scanning'
            parts = [t(self.lang, key, dirs='{:,}'.format(dirs), files='{:,}'.format(files))]
        else:
            parts = [t(self.lang, 'entries', entries='{:,}'.format(st['entries']))]
        if st['unreadable_count']:
            parts.append(t(self.lang, 'unreadable', count=st['unreadable_count']))
        parts.append(core.text('watch_' + st['watch'], self.lang))
        parts.append('v' + core.VERSION)
        self.set_state(' · '.join(parts))
        if getattr(self, 'expanded', None) is not None:
            self.update_hint()
        return False


class SettingsDialog:
    """Index scope (folders to index, exclusions, hidden entries) and shortcuts. Edits stay in
    the dialog until Save; problems are listed first and Save anyway saves regardless (an empty
    folder list or two actions on the same keys cannot be saved)."""

    RESTORE, ANYWAY = 1, 2

    def __init__(self, window, config, mounts=None):
        self.window = window
        self.lang = window.lang
        self.config = config
        self.mounts = mounts
        self.roots = list(config.roots)
        self.exclude = list(config.exclude)
        self.keys = load_keys(config)
        self.saved_toggle = self.keys['toggle']
        self.order = window.column_order()
        self.recording = None           # action whose shortcut is being recorded
        lang = self.lang
        d = self.dialog = Gtk.Dialog(title=t(lang, 'settings'), transient_for=window.win, modal=True,
                                     destroy_with_parent=True)
        d.set_default_size(580, 680)
        d.add_button(t(lang, 'defaults'), self.RESTORE)
        d.add_button(t(lang, 'cancel'), Gtk.ResponseType.CANCEL)
        self.anyway = d.add_button(t(lang, 'save_anyway'), self.ANYWAY)
        d.add_button(t(lang, 'save'), Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        d.connect('response', self.on_response)
        d.connect('key-press-event', self.on_key)
        outer = Gtk.ScrolledWindow()
        outer.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        d.get_content_area().pack_start(outer, True, True, 0)
        area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.add(area)
        for side in ('start', 'end', 'top', 'bottom'):
            getattr(area, 'set_margin_' + side)(10)

        area.pack_start(self.heading(t(lang, 'set_roots')), False, False, 0)
        self.roots_box = self.list_box()
        area.pack_start(self.scrolled(self.roots_box), True, True, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        b = Gtk.Button(label=t(lang, 'add_folder'))
        b.connect('clicked', lambda *_: self.pick_into('roots'))
        row.pack_start(b, False, False, 0)
        area.pack_start(row, False, False, 0)

        area.pack_start(self.heading(t(lang, 'set_exclude')), False, False, 0)
        self.exclude_box = self.list_box()
        area.pack_start(self.scrolled(self.exclude_box), True, True, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        b = Gtk.Button(label=t(lang, 'add_folder'))
        b.connect('clicked', lambda *_: self.pick_into('exclude'))
        row.pack_start(b, False, False, 0)
        self.rule = Gtk.Entry()
        self.rule.set_placeholder_text(t(lang, 'set_exclude_hint'))
        self.rule.get_accessible().set_name(t(lang, 'set_exclude_hint'))
        self.rule.connect('activate', lambda *_: self.add_rule())
        row.pack_start(self.rule, True, True, 0)
        b = Gtk.Button(label=t(lang, 'add'))
        b.connect('clicked', lambda *_: self.add_rule())
        row.pack_start(b, False, False, 0)
        area.pack_start(row, False, False, 0)

        self.hidden = Gtk.CheckButton(label=t(lang, 'set_hidden'))
        self.hidden.set_active(config.hidden)
        area.pack_start(self.hidden, False, False, 0)
        self.match_path = Gtk.CheckButton(label=t(lang, 'set_match_path'))
        self.match_path.set_active(config.match_path())
        area.pack_start(self.match_path, False, False, 0)

        area.pack_start(self.heading(t(lang, 'set_columns')), False, False, 0)
        self.columns_box = self.list_box()
        frame = Gtk.Frame()
        frame.add(self.columns_box)
        area.pack_start(frame, False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        b = Gtk.Button(label=t(lang, 'col_defaults'))
        b.connect('clicked', lambda *_: self.reset_columns())
        row.pack_start(b, False, False, 0)
        area.pack_start(row, False, False, 0)

        area.pack_start(self.heading(t(lang, 'keys')), False, False, 0)
        grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        self.key_buttons = {}
        for r, action in enumerate(KEY_ORDER):
            lab = Gtk.Label(label=t(lang, 'key_' + action), xalign=0)
            lab.set_line_wrap(True)
            lab.set_hexpand(True)
            grid.attach(lab, 0, r, 1, 1)
            b = self.key_buttons[action] = Gtk.Button()
            b.connect('clicked', lambda _b, a=action: self.record(a))
            grid.attach(b, 1, r, 1, 1)
            c = Gtk.Button(label=t(lang, 'key_clear'))
            c.set_relief(Gtk.ReliefStyle.NONE)
            c.get_accessible().set_name(t(lang, 'key_clear_item', action=t(lang, 'key_' + action)))
            c.connect('clicked', lambda _b, a=action: self.set_key(a, ''))
            grid.attach(c, 2, r, 1, 1)
        area.pack_start(grid, False, False, 0)
        self.key_note = Gtk.Label(xalign=0)
        self.key_note.set_line_wrap(True)
        self.key_note.set_selectable(True)
        self.key_note.get_style_context().add_class('dim-label')
        self.key_note.set_no_show_all(True)
        area.pack_start(self.key_note, False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.copy_command = Gtk.Button(label=t(lang, 'copy_command'))
        self.copy_command.connect('clicked', lambda *_: self.copy_toggle_command())
        self.copy_command.set_no_show_all(True)
        row.pack_start(self.copy_command, False, False, 0)
        area.pack_start(row, False, False, 0)
        area.pack_start(self.heading(t(lang, 'set_upgrade')), False, False, 0)
        hint = Gtk.Label(label=t(lang, 'upgrade_hint'), xalign=0)
        hint.set_line_wrap(True)
        hint.get_style_context().add_class('dim-label')
        area.pack_start(hint, False, False, 0)
        self.upgrade_state = Gtk.Label(xalign=0)
        self.upgrade_state.set_line_wrap(True)
        area.pack_start(self.upgrade_state, False, False, 0)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.upgrade_buttons = []
        for label, how in (('upgrade_zip', 'zip'), ('upgrade_dir', 'dir'), ('rollback', 'rollback')):
            b = Gtk.Button(label=t(lang, label))
            b.connect('clicked', lambda _b, h=how: self.upgrade(h))
            row.pack_start(b, False, False, 0)
            self.upgrade_buttons.append(b)
        self.rollback_button = self.upgrade_buttons[2]
        area.pack_start(row, False, False, 0)
        # problems sit right above the buttons, outside the scrolled part, so they are always in view
        self.problems = Gtk.Label(xalign=0)
        self.problems.set_line_wrap(True)
        self.problems.set_selectable(True)
        for side in ('start', 'end', 'top'):
            getattr(self.problems, 'set_margin_' + side)(10)
        d.get_content_area().pack_start(self.problems, False, False, 0)
        self.refill_upgrade()
        self.refill()
        self.refill_columns()
        self.refill_keys()

    def refill_upgrade(self):
        """Versions under Upgrade; the buttons are off while an upgrade runs or without the module."""
        lang = self.lang
        busy = self.window.upgrading
        if tool_upgrade is None:
            self.upgrade_state.set_text(t(lang, 'upgrade_missing'))
            for b in self.upgrade_buttons:
                b.set_sensitive(False)
            return
        info = tool_upgrade.rollback_info(TOOL_DIR)
        cur = info['current'] or 'v' + core.VERSION
        self.upgrade_state.set_text(t(lang, 'upgrade_now', cur=cur, prev=info['previous']) if info['available']
                                    else t(lang, 'upgrade_now_none', cur=cur))
        for b in self.upgrade_buttons[:2]:
            b.set_sensitive(not busy)
        self.rollback_button.set_sensitive(info['available'] and not busy)

    def upgrade(self, how):
        """Upgrade or roll back; unsaved changes here would be lost when the window restarts, so
        that is asked first."""
        if not self.dirty():
            self._upgrade(how)
            return
        lang = self.lang
        self.window.confirm(t(lang, 'unsaved_q'), t(lang, 'unsaved_detail'), t(lang, 'unsaved_go'),
                            lambda ok: ok and self._upgrade(how))

    def _upgrade(self, how):
        if how == 'rollback':
            self.window.ask_rollback()
            return
        path = self.choose_upgrade(how)
        if path:
            self.window.upgrade_from(path)

    def dirty(self):
        """True when the dialog holds changes not saved yet."""
        c = self.config
        return (core.tidy_scope(self.roots, self.exclude) != core.tidy_scope(c.roots, c.exclude)
                or self.hidden.get_active() != c.hidden or self.match_path.get_active() != c.match_path()
                or self.keys != load_keys(c) or list(self.order) != list(self.window.column_order()))

    def choose_upgrade(self, how):
        """A file chooser for the release zip or its unpacked folder; returns the path or None. Tests replace this."""
        lang = self.lang
        action = Gtk.FileChooserAction.SELECT_FOLDER if how == 'dir' else Gtk.FileChooserAction.OPEN
        d = Gtk.FileChooserDialog(title=t(lang, 'pick_dir' if how == 'dir' else 'pick_zip'),
                                  transient_for=self.dialog, action=action, modal=True)
        d.add_button(t(lang, 'cancel'), Gtk.ResponseType.CANCEL)
        d.add_button(t(lang, 'pick'), Gtk.ResponseType.OK)
        if how == 'zip':
            f = Gtk.FileFilter()
            f.set_name(t(lang, 'zip_filter'))
            f.add_pattern('*.zip')
            f.add_pattern('*.ZIP')
            d.add_filter(f)
        path = d.get_filename() if d.run() == Gtk.ResponseType.OK else None
        d.destroy()
        return path

    @staticmethod
    def heading(text):
        lab = Gtk.Label(xalign=0)
        lab.set_markup('<b>%s</b>' % GLib.markup_escape_text(text, -1))
        return lab

    @staticmethod
    def list_box():
        lb = Gtk.ListBox()
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        return lb

    @staticmethod
    def scrolled(child):
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(90)
        sw.set_shadow_type(Gtk.ShadowType.IN)
        sw.add(child)
        return sw

    def refill(self):
        for which, box in (('roots', self.roots_box), ('exclude', self.exclude_box)):
            for child in box.get_children():
                box.remove(child)
            for i, item in enumerate(getattr(self, which)):
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                row.set_margin_start(6)
                row.set_margin_end(2)
                lab = Gtk.Label(label=core.display(item), xalign=0)
                lab.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                lab.set_tooltip_text(core.display(item))
                row.pack_start(lab, True, True, 0)
                b = Gtk.Button(label=t(self.lang, 'remove'))
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.get_accessible().set_name(t(self.lang, 'remove_item', item=core.display(item)))
                b.connect('clicked', lambda _b, w=which, k=i: self.remove(w, k))
                row.pack_end(b, False, False, 0)
                box.add(row)
            box.show_all()

    # edits

    def add(self, which, item):
        roots, exclude = core.tidy_scope(self.roots + ([item] if which == 'roots' else []),
                                         self.exclude + ([item] if which == 'exclude' else []))
        self.roots, self.exclude = roots, exclude
        self.refill()
        self.update_problems([])

    def remove(self, which, k):
        items = getattr(self, which)
        if 0 <= k < len(items):
            del items[k]
            self.refill()
            self.update_problems([])

    def add_rule(self):
        text = self.rule.get_text().strip()
        if text:
            self.add('exclude', text)
            self.rule.set_text('')

    def pick_into(self, which):
        path = self.choose_folder()
        if path:
            self.add(which, path)

    def choose_folder(self):
        """A folder from the system folder chooser, or None. Tests replace this."""
        fc = Gtk.FileChooserDialog(title=t(self.lang, 'choose_folder'), transient_for=self.dialog,
                                   action=Gtk.FileChooserAction.SELECT_FOLDER)
        fc.add_button(t(self.lang, 'cancel'), Gtk.ResponseType.CANCEL)
        fc.add_button(t(self.lang, 'add'), Gtk.ResponseType.OK)
        fc.set_current_folder(core.HOME)
        try:
            return fc.get_filename() if fc.run() == Gtk.ResponseType.OK else None
        finally:
            fc.destroy()

    def restore_defaults(self):
        self.roots, self.exclude = list(core.DEFAULT_ROOTS), list(core.DEFAULT_EXCLUDE)
        self.hidden.set_active(False)
        self.match_path.set_active(True)
        self.order = list(DATA_COLUMNS)
        self.keys = dict(KEY_DEFAULTS, toggle=DEFAULT_TOGGLE)
        self.recording = None
        self.refill()
        self.refill_columns()
        self.refill_keys()
        self.update_problems([])

    def reset_columns(self):
        self.order = list(DATA_COLUMNS)
        self.refill_columns()

    # column order

    def refill_columns(self):
        box = self.columns_box
        for child in box.get_children():
            box.remove(child)
        last = len(self.order) - 1
        for i, key in enumerate(self.order):
            name = t(self.lang, 'col_' + key)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row.set_margin_start(6)
            row.set_margin_end(2)
            row.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            for label, item, step, ok in (('col_up', 'col_up_item', -1, i > 0),
                                          ('col_down', 'col_down_item', 1, i < last)):
                b = Gtk.Button(label=t(self.lang, label))
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.set_sensitive(ok)
                b.get_accessible().set_name(t(self.lang, item, col=name))
                b.connect('clicked', lambda _b, k=i, d=step: self.move_column(k, d))
                row.pack_start(b, False, False, 0)
            box.add(row)
        box.show_all()

    def move_column(self, k, step):
        j = k + step
        if 0 <= k < len(self.order) and 0 <= j < len(self.order):
            self.order[k], self.order[j] = self.order[j], self.order[k]
            self.refill_columns()
            # keep the keyboard on the moved column's button in its new row
            row = self.columns_box.get_row_at_index(j)
            if row is not None:
                buttons = [w for w in row.get_child().get_children() if isinstance(w, Gtk.Button)]
                target = buttons[0] if step < 0 else buttons[1]
                if not target.get_sensitive():
                    target = buttons[1] if step < 0 else buttons[0]
                target.grab_focus()


    # shortcuts

    def key_label(self, accel):
        if not accel:
            return t(self.lang, 'key_none')
        keyval, mods = Gtk.accelerator_parse(accel)
        return Gtk.accelerator_get_label(keyval, mods) if keyval else accel

    def refill_keys(self):
        for action, b in self.key_buttons.items():
            if action == self.recording:
                b.set_label(t(self.lang, 'key_press'))
            else:
                b.set_label(self.key_label(self.keys.get(action, '')))
            b.get_accessible().set_name(t(self.lang, 'key_' + action) + ': ' + b.get_label())
        command, installed = toggle_command()
        notes = []
        manual = self.window.hotkey.desktop() is None
        if manual:
            notes.append(t(self.lang, 'key_manual', command=command))
        elif not installed:
            notes.append(t(self.lang, 'key_moved'))
        self.key_note.set_text('\n'.join(notes))
        self.key_note.set_visible(bool(notes))
        self.copy_command.set_visible(manual)

    def record(self, action):
        """Wait for the next key combination for action (Esc cancels)."""
        self.recording = action
        self.refill_keys()
        self.key_buttons[action].grab_focus()

    def set_key(self, action, accel):
        self.keys[action] = accel
        self.recording = None
        self.refill_keys()
        self.update_problems([])

    def on_key(self, _dialog, event):
        if self.recording is None:
            return False
        keyval = Gdk.keyval_to_lower(event.keyval)
        mods = Gdk.ModifierType(int(event.state) & int(Gtk.accelerator_get_default_mod_mask()))
        if keyval == Gdk.KEY_Escape and not int(mods):
            self.recording = None
            self.refill_keys()
            return True
        name = Gdk.keyval_name(keyval) or ''
        if name.startswith(('Control', 'Shift', 'Alt', 'Super', 'Meta', 'Hyper', 'ISO_Level', 'Caps')):
            return True                 # a modifier alone: wait for the key
        self.offer_key(self.recording, Gtk.accelerator_name(keyval, mods))
        return True

    def offer_key(self, action, accel):
        """Take a recorded combination unless it is a key the list needs or a plain key."""
        label = self.key_label(accel)
        if is_fixed_key(accel):
            self.show_key_problem(t(self.lang, 'key_fixed', key=label))
            return False
        if not plain_key_ok(accel):
            self.show_key_problem(t(self.lang, 'key_plain', key=label))
            return False
        self.set_key(action, accel)
        return True

    def show_key_problem(self, text):
        self.recording = None
        self.refill_keys()
        self.update_problems([text], blocked=True)

    def copy_toggle_command(self):
        command, _ = toggle_command()
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        cb.set_text(command, -1)
        cb.store()

    # saving

    def update_problems(self, lines, blocked=False):
        """Show problems: blocked ones (one line each, cannot be saved) or warnings listed under
        a heading, with Save anyway."""
        ctx = self.problems.get_style_context()
        ctx.remove_class('error')
        ctx.remove_class('warning')
        self.anyway.set_visible(bool(lines) and not blocked)
        if not lines:
            self.problems.set_text('')
            self.problems.set_visible(False)
            return
        if blocked:
            text = '\n'.join(lines)
            ctx.add_class('error')
        else:
            text = '\n'.join([t(self.lang, 'set_warn')] + ['· ' + line for line in lines])
            ctx.add_class('warning')
        self.problems.set_text(text)
        self.problems.set_visible(True)

    def save(self, force=False):
        """'saved', 'warn' (problems listed, not saved) or 'blocked' (cannot be saved)."""
        lang = self.lang
        roots, exclude = core.tidy_scope(self.roots, self.exclude)
        problems = core.check_scope(roots, exclude, self.mounts)
        blocked = []
        if any(code == 'no_roots' for _, _, code in problems):
            blocked.append(t(lang, 'set_blocked', reason=core.scope_problem_text('', 'no_roots', lang)))
        for action, other in key_clashes({k: v for k, v in self.keys.items() if k != 'toggle'}):
            blocked.append(t(lang, 'key_dup', a=t(lang, 'key_' + action), b=t(lang, 'key_' + other)))
        if blocked:
            self.update_problems(blocked, blocked=True)
            return 'blocked'
        warnings = [core.scope_problem_text(item, code, lang) for _, item, code in problems]
        toggle = self.keys['toggle']
        if toggle and toggle != self.saved_toggle:
            owner = self.window.hotkey.taken(toggle)
            if owner:
                warnings.append(t(lang, 'key_taken', key=self.key_label(toggle), name=owner))
        if warnings and not force:
            self.update_problems(warnings)
            return 'warn'
        new = self.config.with_scope(roots, exclude, self.hidden.get_active())
        new.other['keys'] = {k: v for k, v in self.keys.items() if v != KEY_DEFAULTS[k] or k == 'toggle'}
        new.other['match_path'] = self.match_path.get_active()
        same_scope = (new.resolved_roots() == self.config.resolved_roots() and new.exclude == self.config.exclude
                      and new.hidden == self.config.hidden)
        ok = self.window.save_config(new) if same_scope else self.window.apply_scope(new)
        if not ok:
            return 'blocked'
        self.window.set_column_order(self.order)
        if same_scope and new.match_path() != self.config.match_path():
            self.window.run_search(keep=True)
        self.window.apply_keys(self.keys)
        if toggle != self.saved_toggle:
            self.window.write_hotkey(toggle)
        self.dialog.destroy()
        return 'saved'

    def on_response(self, dialog, response):
        if response == self.RESTORE:
            self.restore_defaults()
        elif response == Gtk.ResponseType.OK:
            self.save()
        elif response == self.ANYWAY:
            self.save(force=True)
        else:
            dialog.destroy()


def build_app(index, lang=None, notice=None):
    """A Gtk.Application with one window; a second start activates the first one. notice: a
    dict whose "notice" (message, kind), when set by the time the window opens, is shown once."""
    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
    holder = {}

    def activate(a):
        if 'win' in holder:
            holder['win'].win.present()
            return
        w = holder['win'] = Window(a, index, lang, notice=(notice or {}).get('notice'))
        w.start()

    def toggle(_action, _param):
        if 'win' in holder:
            holder['win'].toggle()
        else:
            activate(app)

    app.connect('activate', activate)
    action = Gio.SimpleAction.new('toggle', None)
    action.connect('activate', toggle)
    app.add_action(action)
    app.holder = holder
    return app


def main(args=None):
    if not load_gi():
        print('find-fast: python3-gi (GTK 3) is not installed', file=sys.stderr)
        return 1
    config = core.Config(getattr(args, 'config', core.CONFIG_FILE))
    index = core.Index(config, getattr(args, 'cache', core.CACHE_FILE))
    holder = {}
    app = build_app(index, notice=holder)
    if getattr(args, 'toggle', False):
        # a running window is shown or hidden by the first instance; otherwise start as usual
        app.register(None)
        if app.get_is_remote():
            app.activate_action('toggle', None)
            conn = app.get_dbus_connection()
            if conn is not None:
                conn.flush_sync(None)
            return 0
    holder['notice'] = ensure_default_toggle(config)
    if tool_upgrade and tool_upgrade.resumed() is not None:
        wait_for_name(APP_ID)
    rc = app.run(sys.argv[:1])
    if getattr(app, 'restart_after_upgrade', False):
        argv = ['--gtk', '--log-level', logging.getLevelName(logging.getLogger().level)]
        for opt, default in (('config', core.CONFIG_FILE), ('cache', core.CACHE_FILE)):
            value = getattr(args, opt, default)
            if value != default:
                argv += ['--' + opt, value]
        tool_upgrade.restart(os.path.join(TOOL_DIR, 'find_fast.py'), argv, {'gtk': True})
    return rc


def wait_for_name(name, timeout=5.0):
    """After an upgrade the old process has just left the session bus: wait until its name is free,
    so this start opens a window instead of handing over to a process that is gone."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as e:
        log.debug('no session bus: %s', e)
        return
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            owned = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                                  'NameHasOwner', GLib.Variant('(s)', (name,)), GLib.VariantType('(b)'),
                                  Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        except GLib.Error as e:
            log.debug('NameHasOwner: %s', e)
            return
        if not owned:
            return
        time.sleep(0.1)
    log.warning('%s still owned after %.0f s', name, timeout)


if __name__ == '__main__':
    import find_fast
    sys.exit(find_fast.main(['--gtk'] + sys.argv[1:]))

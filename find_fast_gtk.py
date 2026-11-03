#!/usr/bin/env python3
"""find-fast GTK3 window (system python3-gi).

The result list is virtual: a Gtk.TreeView whose ListStore holds only the rows that fit on
screen, refilled from the search result as the separate scroll bar moves, so the number of
results is not limited. Keyboard: type to search; Down moves into the list; Up/Down, Page
Up/Down, Home/End move; Enter opens; Ctrl+Enter opens the containing folder; Ctrl+C copies the
path; Menu or Shift+F10 opens the context menu; F5 or Ctrl+R rescans; Esc clears the search
box, and when it is empty closes the window.
"""
import logging
import os
import sys
import threading
import time
import urllib.parse

import find_fast_core as core

log = logging.getLogger('find_fast_gtk')
APP_ID = 'io.github.walkwithedi.findfast'
RESCAN_EVERY = 300              # seconds between rescans when inotify cannot watch every folder
CHANGE_THROTTLE = 1.0           # seconds between result refreshes caused by file changes
WHEEL_ROWS = 3

UI = {
    'zh': {
        'search': '搜索文件名……（* ? 通配，ext:pdf，path:，!排除，a|b）',
        'col_name': '名称', 'col_path': '路径', 'col_size': '大小', 'col_mtime': '修改时间',
        'open': '打开', 'open_folder': '打开所在文件夹', 'copy_path': '复制路径', 'rescan': '重新扫描',
        'loading': '正在载入索引……',
        'first_scan': '首次建立索引：{dirs} 个文件夹，{files} 个条目……',
        'scanning': '正在更新索引：{dirs} 个文件夹……',
        'results': '{count} 个结果',
        'results_ms': '{count} 个结果（{ms} 毫秒）',
        'entries': '共 {entries} 个条目',
        'copied': '已复制路径：{path}',
        'copy_failed': '复制失败：剪贴板不可用。请在「路径」列选中后手动复制。',
        'open_failed': '打开失败：{error}。请检查文件是否还在，或用文件管理器打开。',
        'gone': '打开失败：文件已不存在。索引将在下次扫描时更新。',
        'unreadable': '{count} 个文件夹无法读取',
    },
    'en': {
        'search': 'Search file names... (* ? wildcards, ext:pdf, path:, !not, a|b)',
        'col_name': 'Name', 'col_path': 'Path', 'col_size': 'Size', 'col_mtime': 'Modified',
        'open': 'Open', 'open_folder': 'Open containing folder', 'copy_path': 'Copy path', 'rescan': 'Rescan',
        'loading': 'Loading the index...',
        'first_scan': 'Building the index: {dirs} folders, {files} entries...',
        'scanning': 'Updating the index: {dirs} folders...',
        'results': '{count} results',
        'results_ms': '{count} results ({ms} ms)',
        'entries': '{entries} entries',
        'copied': 'Path copied: {path}',
        'copy_failed': 'Copy failed: the clipboard is unavailable. Select the path and copy it by hand.',
        'open_failed': 'Open failed: {error}. Check that the file still exists, or open it from a file manager.',
        'gone': 'Open failed: the file no longer exists. The index is updated at the next scan.',
        'unreadable': '{count} folders unreadable',
    },
}
COLUMNS = [('name', 'col_name'), ('path', 'col_path'), ('size', 'col_size'), ('mtime', 'col_mtime')]
COL_TIP = 5                     # store column holding the row's tooltip
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


def t(lang, key, **kw):
    table = UI.get(lang, UI['en'])
    return table.get(key, UI['en'][key]).format(**kw)


class Window:
    """The search window around an Index. Holds no GTK subclass so it can be built after gi is
    loaded lazily."""

    def __init__(self, app, index, lang=None):
        self.app = app
        self.index = index
        self.lang = lang or core.ui_language()
        self.result = None
        self.sort = core.DEFAULT_SORT
        self.desc = True
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
        self.query = None               # text of the last search
        self.searches = 0
        self.closed = False             # set when the window is destroyed; late callbacks do nothing
        self.build()

    # ------------------------------------------------------------ layout

    def build(self):
        w = self.win = Gtk.ApplicationWindow(application=self.app)
        w.set_title(core.text('app_name', self.lang))
        w.set_default_size(960, 600)
        w.set_icon_name('system-search')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        w.add(box)

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text(t(self.lang, 'search'))
        self.entry.set_margin_start(8)
        self.entry.set_margin_end(8)
        self.entry.set_margin_top(8)
        self.entry.set_margin_bottom(6)
        self.entry.connect('search-changed', self.on_search_changed)
        self.entry.connect('key-press-event', self.on_entry_key)
        self.entry.connect('activate', lambda *_: self.open_current())
        box.pack_start(self.entry, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.pack_start(row, True, True, 0)

        # icon name, name, folder, size, time, tooltip (Pango markup: the full path)
        self.store = Gtk.ListStore(str, str, str, str, str, str)
        tv = self.tree = Gtk.TreeView(model=self.store)
        tv.set_tooltip_column(COL_TIP)
        tv.set_enable_search(False)
        tv.set_headers_clickable(True)
        tv.set_fixed_height_mode(True)
        tv.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        tv.set_vexpand(True)
        tv.set_hexpand(True)
        self.columns = {}
        for i, (key, label) in enumerate(COLUMNS):
            col = Gtk.TreeViewColumn(t(self.lang, label))
            col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            col.set_resizable(True)
            col.set_clickable(True)
            col.connect('clicked', self.on_header, key)
            if key == 'name':
                icon = Gtk.CellRendererPixbuf()
                col.pack_start(icon, False)
                col.add_attribute(icon, 'icon-name', 0)
                col.set_fixed_width(300)
                col.set_expand(False)
            cell = Gtk.CellRendererText()
            cell.set_property('ellipsize', Pango.EllipsizeMode.MIDDLE if key == 'path' else Pango.EllipsizeMode.END)
            if key in ('size', 'mtime'):
                cell.set_property('xalign', 1.0 if key == 'size' else 0.0)
            col.pack_start(cell, True)
            col.add_attribute(cell, 'text', i + 1)
            if key == 'path':
                col.set_fixed_width(380)
                col.set_expand(True)
            elif key == 'size':
                col.set_fixed_width(90)
            elif key == 'mtime':
                col.set_fixed_width(140)
            tv.append_column(col)
            self.columns[key] = col
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
        row.pack_start(self.sw, True, True, 0)
        row.pack_start(self.scrollbar, False, False, 0)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.set_margin_start(8)
        bar.set_margin_end(8)
        bar.set_margin_top(4)
        bar.set_margin_bottom(4)
        self.status = Gtk.Label(xalign=0)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_selectable(False)
        self.state = Gtk.Label(xalign=1)
        self.state.set_ellipsize(Pango.EllipsizeMode.START)
        bar.pack_start(self.status, True, True, 0)
        bar.pack_end(self.state, False, False, 0)
        box.pack_start(bar, False, False, 0)

        self.menu = Gtk.Menu()
        for key, cb in (('open', self.open_current), ('open_folder', self.open_folder),
                        ('copy_path', self.copy_path)):
            item = Gtk.MenuItem(label=t(self.lang, key))
            item.connect('activate', lambda _i, f=cb: f())
            self.menu.append(item)
        self.menu.append(Gtk.SeparatorMenuItem())
        item = Gtk.MenuItem(label=t(self.lang, 'rescan'))
        item.connect('activate', lambda *_: self.start_refresh())
        self.menu.append(item)
        self.menu.show_all()

        w.connect('delete-event', self.on_delete)
        w.connect('destroy', lambda *_: setattr(self, 'closed', True))
        accel = Gtk.AccelGroup()
        w.add_accel_group(accel)
        for key in ('F5', '<Control>r'):
            k, mods = Gtk.accelerator_parse(key)
            accel.connect(k, mods, 0, lambda *_: (self.start_refresh(), True)[1])
        k, mods = Gtk.accelerator_parse('<Control>l')
        accel.connect(k, mods, 0, lambda *_: (self.entry.grab_focus(), True)[1])
        self.update_sort_indicators()
        w.show_all()
        self.entry.grab_focus()

    # ------------------------------------------------------------ index lifecycle

    def start(self):
        """Load the cache in the background, then rescan and watch."""
        self.index.on_change = self.on_index_change
        self.set_state(t(self.lang, 'loading'))
        self.worker = threading.Thread(target=self._load_and_refresh, name='index', daemon=True)
        self.worker.start()

    def _load_and_refresh(self):
        loaded = self.index.load()
        GLib.idle_add(self.after_load, loaded)
        if self.stop.is_set():
            return
        self.index.refresh(stop=self.stop)
        if self.stop.is_set():
            return
        watching = self.index.start_watching()
        GLib.idle_add(self.after_refresh, watching)

    def after_load(self, loaded):
        if self.closed:
            return False
        self.run_search()
        self.update_state()
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

    def start_refresh(self):
        if self.worker is not None and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._refresh, name='index', daemon=True)
        self.worker.start()

    def _refresh(self):
        self.index.refresh_and_watch(stop=self.stop)
        GLib.idle_add(self.after_change)

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
        """Close: stop a scan in progress; a cache being written is finished first."""
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

    # ------------------------------------------------------------ search

    def on_search_changed(self, *_):
        self.run_search()

    def run_search(self, keep=False):
        """Search for the entry text. keep: stay on the selected path and scroll position."""
        keep_path = self.current_path() if keep else None
        top = self.top if keep else 0
        self.query = self.entry.get_text()
        self.searches += 1
        try:
            self.result = self.index.search(self.query, self.sort, self.desc)
            self.message = None
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
        self.sync_adjustment()
        self.fill()
        self.update_status()

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
                values = ['folder' if size < 0 else 'text-x-generic', core.display(name), core.display(folder),
                          core.human_size(size), core.human_time(mtime), self.tooltip(k, name, folder)]
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
        """Tooltip of result row k: the full path, escaped for Pango markup."""
        return GLib.markup_escape_text(core.display(os.path.join(folder, name)), -1)

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
            else:
                self.on_delete()
            return True
        if key in (Gdk.KEY_Down, Gdk.KEY_Page_Down) and self.count():
            self.tree.grab_focus()
            self.scroll_to(max(self.cur, 0) if self.cur >= 0 else 0)
            return True
        return False

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
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if ctrl:
                self.open_folder()
            else:
                self.open_current()
            return True
        if ctrl and key in (Gdk.KEY_c, Gdk.KEY_C):
            self.copy_path()
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
        if event is not None:
            self.menu.popup_at_pointer(event)
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
        path = self.current_path()
        if path is None:
            if self.count():
                self.scroll_to(0)
                path = self.current_path()
            if path is None:
                return
        if not os.path.lexists(path):
            self.show_message(t(self.lang, 'gone'), 'bad')
            return
        try:
            self.open_uri(file_uri(path))
        except Exception as e:  # GLib.Error and OSError alike
            self.show_message(t(self.lang, 'open_failed', error=getattr(e, 'message', None) or e), 'bad')

    def open_folder(self):
        path = self.current_path()
        if path is None:
            return
        try:
            if not self.show_in_file_manager(path):
                self.open_uri(file_uri(os.path.dirname(path)))
        except Exception as e:
            self.show_message(t(self.lang, 'open_failed', error=getattr(e, 'message', None) or e), 'bad')

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

    def copy_path(self):
        path = self.current_path()
        if path is None:
            return
        try:
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            cb.set_text(core.display(path), -1)
            cb.store()
            self.show_message(t(self.lang, 'copied', path=core.display(path)), 'ok')
        except Exception as e:
            log.warning('copy failed: %s', e)
            self.show_message(t(self.lang, 'copy_failed'), 'bad')

    # ------------------------------------------------------------ status

    def show_message(self, text, kind):
        self.message = (text, kind)
        self.update_status()
        GLib.timeout_add_seconds(4, self._clear_message, text)

    def _clear_message(self, text):
        if self.message is not None and self.message[0] == text:
            self.message = None
            self.update_status()
        return False

    def update_status(self):
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
        self.status.set_text(t(self.lang, 'results_ms', count='{:,}'.format(self.count()), ms=self.result.ms))

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
        return False


def build_app(index, lang=None):
    """A Gtk.Application with one window; a second start activates the first one."""
    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
    holder = {}

    def activate(a):
        if 'win' in holder:
            holder['win'].win.present()
            return
        w = holder['win'] = Window(a, index, lang)
        w.start()

    app.connect('activate', activate)
    app.holder = holder
    return app


def main(args=None):
    if not load_gi():
        print('find-fast: python3-gi (GTK 3) is not installed', file=sys.stderr)
        return 1
    config = core.Config(getattr(args, 'config', core.CONFIG_FILE))
    index = core.Index(config, getattr(args, 'cache', core.CACHE_FILE))
    app = build_app(index)
    return app.run(sys.argv[:1])


if __name__ == '__main__':
    import find_fast
    sys.exit(find_fast.main(['--gtk'] + sys.argv[1:]))

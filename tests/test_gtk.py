"""Tests of the GTK window. They need python3-gi with GTK 3 and a display (xvfb-run in CI) and
are skipped otherwise."""
import os
import shutil
import sys
import tempfile
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import find_fast_core as core  # noqa: E402
import find_fast_gtk as ui  # noqa: E402
from test_core import make_tree, touch  # noqa: E402

HAVE_GTK = bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) and ui.available()


def pump(seconds=0.0, until=None):
    """Run the GTK main loop for a while, or until until() is true (at most 10 s)."""
    Gtk = ui.Gtk
    end = time.monotonic() + (seconds if until is None else 10)
    while time.monotonic() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until is None


def key(keyval, state=0):
    return types.SimpleNamespace(keyval=keyval, state=state)


@unittest.skipUnless(HAVE_GTK, 'needs python3-gi, GTK 3 and a display')
class GtkTest(unittest.TestCase):
    apps = 0

    def setUp(self):
        Gio = ui.Gio
        self.tmp = tempfile.mkdtemp(prefix='ff-gtk-')
        self.root = os.path.join(self.tmp, 'root')
        make_tree(self.root)
        config = core.Config(os.path.join(self.tmp, 'config.json'), {'roots': [self.root]})
        self.index = core.Index(config, os.path.join(self.tmp, 'index.bin'), mounts={})
        GtkTest.apps += 1     # every test registers its own id: a session bus refuses a second export
        self.app = ui.Gtk.Application(application_id='io.github.walkwithedi.findfast.test%d.n%d' % (os.getpid(),
                                                                                                GtkTest.apps),
                                      flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.app.register(None)
        self.quit_called = False

    def tearDown(self):
        w = getattr(self, 'w', None)
        if w is not None:
            w.stop.set()
            w.index.close()
            w.win.destroy()
        pump(0.05)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def window(self, lang='en', start=True):
        self.w = ui.Window(self.app, self.index, lang)
        self.w.quit = lambda: setattr(self, 'quit_called', True)
        if start:
            self.w.start()
            self.assertTrue(pump(until=lambda: self.index.state == 'ready' and self.w.result is not None
                                 and not self.w.worker.is_alive()))
            pump(0.1)
        return self.w

    def type(self, text):
        before = self.w.searches
        if self.w.entry.get_text() == text:
            self.w.run_search()
        else:
            self.w.entry.set_text(text)
        self.assertTrue(pump(until=lambda: self.w.searches > before and self.w.query == text))
        pump(0.02)

    def names(self):
        return [r[1] for r in self.w.store]

    def test_title_columns_and_language(self):
        w = self.window('zh', start=False)
        self.assertEqual(w.win.get_title(), '秒搜文件')
        self.assertEqual([c.get_title() for c in w.tree.get_columns()], ['名称', '路径', '大小', '修改时间', '定位'])
        self.assertEqual([l for l in (i.get_label() for i in w.menu.get_children()) if l],
                         ['定位', '打开', '复制文件', '复制路径', '跳到最新版', '排除所在文件夹', '重新扫描'])
        w2 = ui.Window(self.app, self.index, 'en')
        self.assertEqual(w2.win.get_title(), 'find-fast')
        w2.win.destroy()

    def test_strings_have_same_keys(self):
        self.assertEqual(set(ui.UI['zh']), set(ui.UI['en']))

    def test_search_sort_and_status(self):
        w = self.window()
        self.type('report')
        self.assertEqual(self.names(), ['Report 2024.pdf', 'report-draft.docx', 'report-2019.pdf'])
        self.assertTrue(w.status.get_text().startswith('3 results'))
        w.columns['name'].clicked()
        pump(0.05)
        self.assertEqual(self.names(), ['Report 2024.pdf', 'report-2019.pdf', 'report-draft.docx'])
        self.assertEqual(w.columns['name'].get_sort_order(), ui.Gtk.SortType.ASCENDING)
        w.columns['name'].clicked()
        pump(0.05)
        self.assertEqual(self.names(), ['report-draft.docx', 'report-2019.pdf', 'Report 2024.pdf'])
        self.type('regex:(')
        self.assertTrue(pump(until=lambda: 'Invalid regular expression' in w.status.get_text()))
        self.assertEqual(len(w.store), 0)
        self.assertIn('v' + core.VERSION, w.state.get_text())

    def test_keyboard(self):
        w = self.window()
        self.type('report')
        Gdk = ui.Gdk
        self.assertTrue(w.on_entry_key(w.entry, key(Gdk.KEY_Down)))
        self.assertEqual(w.cur, 0)
        w.on_tree_key(w.tree, key(Gdk.KEY_Down))
        self.assertEqual(w.cur, 1)
        w.on_tree_key(w.tree, key(Gdk.KEY_End))
        self.assertEqual(w.cur, 2)
        w.on_tree_key(w.tree, key(Gdk.KEY_Home))
        self.assertEqual(w.cur, 0)
        w.on_tree_key(w.tree, key(Gdk.KEY_Up))
        self.assertTrue(w.entry.has_focus())
        opened = []
        w.open_uri = opened.append
        w.cur = 1
        w.on_tree_key(w.tree, key(Gdk.KEY_Return))
        self.assertEqual(opened, [ui.file_uri(os.path.join(self.root, 'docs', 'report-draft.docx'))])
        w.show_in_file_manager = lambda p: False
        w.on_tree_key(w.tree, key(Gdk.KEY_Return, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(opened[-1], ui.file_uri(os.path.join(self.root, 'docs')))
        self.assertTrue(w.status.get_text().startswith('Opened the containing folder'))
        target = os.path.join(self.root, 'docs', 'report-draft.docx')
        w.on_tree_key(w.tree, key(Gdk.KEY_C, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK))
        pump(0.05)
        clip = ui.Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        self.assertEqual(clip, target)
        self.assertTrue(w.status.get_text().startswith('Path copied'))
        w.on_tree_key(w.tree, key(Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK))
        pump(0.05)
        self.assertEqual(self.clipboard('x-special/gnome-copied-files'), b'copy\n' + ui.file_uri(target).encode())
        self.assertEqual(self.clipboard('text/uri-list'), ui.file_uri(target).encode() + b'\r\n')
        self.assertEqual(ui.Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text(), target)
        self.assertTrue(w.status.get_text().startswith('File copied'))
        w.on_entry_key(w.entry, key(Gdk.KEY_Escape))
        self.assertEqual(w.entry.get_text(), '')
        self.assertFalse(self.quit_called)
        w.on_entry_key(w.entry, key(Gdk.KEY_Escape))
        self.assertTrue(pump(until=lambda: self.quit_called))

    def test_tooltip_is_full_path(self):
        w = self.window()
        long_dir = os.path.join(self.root, 'deep', 'a folder & <more> ' + 'x' * 120)
        touch(os.path.join(long_dir, 'long name & <tag> ' + 'y' * 150 + '.txt'))
        self.index.refresh()
        w.win.resize(500, 300)
        self.type('')
        pump(0.2)
        self.assertTrue(w.tree.get_has_tooltip())
        for j, row in enumerate(w.store):
            self.assertEqual(w.tooltip_markup(j, 'name'), row[ui.COL_TIP])
            self.assertEqual(w.tooltip_markup(j, 'size'), row[ui.COL_TIP])
            self.assertEqual(ui.Pango.parse_markup(w.tooltip_markup(j, 'locate'), -1, '\0')[2], 'Locate ' + row[1])
            full = w.result.path(w.top + j)
            self.assertEqual(row[ui.COL_TIP], ui.GLib.markup_escape_text(full, -1))
            ok, _attrs, text, _accel = ui.Pango.parse_markup(row[ui.COL_TIP], -1, '\0')
            self.assertTrue(ok)
            self.assertEqual(text, full)
        self.assertIn(os.path.join(long_dir, 'long name & <tag> ' + 'y' * 150 + '.txt'),
                      [ui.Pango.parse_markup(r[ui.COL_TIP], -1, '\0')[2] for r in w.store])
        if len(w.result) > w.rows:
            w.adj.set_value(1)
            pump(0.05)
            self.assertEqual(ui.Pango.parse_markup(w.store[0][ui.COL_TIP], -1, '\0')[2], w.result.path(1))

    def wait_ready(self):
        self.assertTrue(pump(until=lambda: self.index.state == 'ready' and not self.w.worker.is_alive()
                             and getattr(self.w, 'pending_scope', None) is None))
        pump(0.1)

    def test_settings_dialog_edits_and_saves(self):
        w = self.window()
        Gdk = ui.Gdk
        # Ctrl+, and the gear button both open the same dialog
        self.assertTrue(self.accel(Gdk.KEY_comma, Gdk.ModifierType.CONTROL_MASK))
        s = w.settings
        self.assertIsNotNone(s)
        w.gear.clicked()
        self.assertIs(w.settings, s)
        other = os.path.join(self.tmp, 'other')
        touch(os.path.join(other, 'from-other-root.txt'))
        s.choose_folder = lambda: other
        s.pick_into('roots')
        s.choose_folder = lambda: os.path.join(self.root, 'docs')
        s.pick_into('exclude')
        s.rule.set_text('*.jpg')
        s.add_rule()
        s.rule.set_text('*.jpg')
        s.add_rule()
        self.assertEqual(s.roots, [self.root, other])
        self.assertEqual(s.exclude.count('*.jpg'), 1)
        self.assertIn(os.path.join(self.root, 'docs'), s.exclude)
        self.assertEqual(len(s.roots_box.get_children()), 2)
        self.assertEqual(s.save(), 'saved')
        self.wait_ready()
        saved = core.Config(os.path.join(self.tmp, 'config.json'))
        self.assertEqual(saved.roots, [self.root, other])
        self.assertIn('*.jpg', saved.exclude)
        self.type('from-other-root')
        self.assertEqual(self.names(), ['from-other-root.txt'])
        self.type('report')
        self.assertEqual(self.names(), [])
        self.type('jpg')
        self.assertEqual(self.names(), [])
        self.assertIsNone(w.settings)

    def test_settings_problems_and_save_anyway(self):
        w = self.window()
        s = w.open_settings()
        while s.roots:
            s.remove('roots', 0)
        self.assertEqual(s.save(), 'blocked')
        self.assertTrue(s.problems.get_visible())
        self.assertFalse(s.anyway.get_visible())
        self.assertTrue(s.problems.get_text().startswith('Save failed'))
        missing = os.path.join(self.tmp, 'not-there')
        s.add('roots', self.root)
        s.add('roots', missing)
        s.add('exclude', '/opt-not-under-root')
        self.assertEqual(s.save(), 'warn')
        self.assertTrue(s.anyway.get_visible())
        text = s.problems.get_text()
        self.assertIn(missing, text)
        self.assertIn('/opt-not-under-root', text)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'config.json')))
        self.assertEqual(s.save(force=True), 'saved')
        self.wait_ready()
        self.assertIn(missing, core.Config(os.path.join(self.tmp, 'config.json')).roots)
        s = w.open_settings()
        s.restore_defaults()
        self.assertEqual(s.roots, core.DEFAULT_ROOTS)
        self.assertFalse(s.hidden.get_active())
        s.dialog.response(ui.Gtk.ResponseType.CANCEL)
        pump(0.05)
        self.assertIsNone(w.settings)

    def test_context_menu_exclude(self):
        w = self.window()
        asked = []
        w.confirm = lambda text, detail, ok, cb: (asked.append(text), cb(True))
        self.type('report-2019')
        w.cur = 0
        w.popup_menu(None)
        self.assertTrue(w.exclude_item.get_visible())
        self.assertEqual(w.exclude_item.get_label(), 'Exclude the containing folder')
        w.menu.popdown()
        w.exclude_current()
        self.assertEqual(asked, ['Exclude %s?' % os.path.join(self.root, 'docs', 'old')])
        self.wait_ready()
        self.assertIn(os.path.join(self.root, 'docs', 'old'),
                      [os.path.expanduser(e) for e in core.Config(os.path.join(self.tmp, 'config.json')).exclude])
        self.type('report-2019')
        self.assertEqual(self.names(), [])
        self.type('pics')
        w.cur = 0
        w.popup_menu(None)
        self.assertEqual(w.exclude_item.get_label(), 'Exclude this folder')
        w.menu.popdown()
        self.type('b.txt')
        w.cur = 0
        w.popup_menu(None)
        self.assertFalse(w.exclude_item.get_visible())     # its folder is the indexed folder itself
        w.menu.popdown()

    def accel(self, keyval, mods=0):
        """Press a window accelerator."""
        return ui.Gtk.accel_groups_activate(self.w.win, keyval, ui.Gdk.ModifierType(mods))

    def test_similar_versions(self):
        d = os.path.join(self.root, 'v')
        touch(os.path.join(d, '示例方案.docx'), b'', 1700001000)
        touch(os.path.join(d, 'a', '示例方案_v2.docx'), b'', 1700003000)
        touch(os.path.join(d, 'b', '示例方案-终稿.docx'), b'', 1700002000)
        touch(os.path.join(d, '示例方案.pdf'), b'', 1700005000)
        w = self.window()
        self.type('示例方案')
        tags = {r[1]: r[ui.COL_TAG] for r in w.store}
        self.assertEqual(tags, {'示例方案.pdf': '', '示例方案_v2.docx': 'Newest',
                                '示例方案-终稿.docx': 'Newer exists', '示例方案.docx': 'Newer exists'})
        k = self.names().index('示例方案.docx')
        tip = ui.Pango.parse_markup(w.store[k][ui.COL_TIP], -1, '\0')[2]
        self.assertEqual(tip, os.path.join(d, '示例方案.docx') + '\n3 similar versions; newest: '
                         + os.path.join(d, 'a', '示例方案_v2.docx'))
        w.columns['name'].clicked()
        pump(0.05)
        self.assertEqual({r[1]: r[ui.COL_TAG] for r in w.store}, tags)
        w.cur = w.top + self.names().index('示例方案.docx')
        w.popup_menu(None)
        self.assertTrue(w.jump_item.get_visible())
        w.menu.popdown()
        w.jump_to_newest()
        self.assertEqual(w.current_path(), os.path.join(d, 'a', '示例方案_v2.docx'))
        w.popup_menu(None)
        self.assertFalse(w.jump_item.get_visible())
        w.menu.popdown()

    def test_versions_grouped_in_background(self):
        touch(os.path.join(self.root, 'v', 'plan.txt'), b'', 1700001000)
        touch(os.path.join(self.root, 'v', 'plan_v2.txt'), b'', 1700002000)
        w = self.window()
        old = ui.VERSIONS_SYNC
        ui.VERSIONS_SYNC = 1
        try:
            self.type('plan')
            self.assertTrue(pump(until=lambda: w.versions is not None))
        finally:
            ui.VERSIONS_SYNC = old
        pump(0.05)
        self.assertEqual({r[1]: r[ui.COL_TAG] for r in w.store}, {'plan_v2.txt': 'Newest', 'plan.txt': 'Newer exists'})

    def test_too_many_results_not_grouped(self):
        w = self.window()
        old = core.VERSION_GROUP_LIMIT
        core.VERSION_GROUP_LIMIT = 3
        try:
            self.type('')
        finally:
            core.VERSION_GROUP_LIMIT = old
        self.assertTrue(w.versions.skipped)
        self.assertIn('Too many results to mark similar versions', w.status.get_text())

    def clipboard(self, target):
        Gtk, Gdk = ui.Gtk, ui.Gdk
        sd = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_contents(Gdk.Atom.intern(target, False))
        return None if sd is None else sd.get_data()

    def test_locate_button_and_copy_folder(self):
        w = self.window()
        self.type('pics')
        located = []
        w.show_in_file_manager = lambda p: located.append(p) or True
        w.tree.realize()
        pump(0.1)
        area = w.tree.get_cell_area(ui.Gtk.TreePath.new_first(), w.columns['locate'])
        ev = ui.Gdk.Event.new(ui.Gdk.EventType.BUTTON_PRESS)
        ev.button.button = 1
        ev.button.x = area.x + area.width / 2
        ev.button.y = area.y + area.height / 2
        self.assertTrue(w.on_button(w.tree, ev.button))
        self.assertEqual(located, [os.path.join(self.root, 'pics')])
        w.cur = 0
        w.copy_file()
        pump(0.05)
        self.assertEqual(self.clipboard('text/uri-list'), ui.file_uri(os.path.join(self.root, 'pics')).encode() + b'\r\n')
        self.type('notes')
        os.remove(os.path.join(self.root, 'docs', 'notes.txt'))
        w.cur = 0
        w.copy_file()
        self.assertTrue(w.status.get_text().startswith('Copy failed: the file no longer exists'))

    def test_ui_state_saved_and_restored(self):
        w = self.window()
        state = os.path.join(self.tmp, 'ui-state.json')
        self.assertEqual(w.state_path, state)
        self.type('report')                 # the list shows, so the height counts
        w.columns['name'].set_fixed_width(222)
        w.win.resize(700, 420)
        pump(0.3)
        w.columns['size'].clicked()
        pump(0.05)
        w.on_delete()
        self.assertTrue(pump(until=lambda: self.quit_called))
        import json
        with open(state, encoding='utf-8') as f:
            saved = json.load(f)
        self.assertEqual(oct(os.stat(state).st_mode & 0o777), '0o600')
        self.assertEqual(saved['columns']['name'], 222)
        self.assertEqual((saved['width'], saved['height']), (700, 420))
        self.assertEqual((saved['sort'], saved['desc']), ('size', True))
        self.assertIn('locate', saved['columns'])
        w.win.destroy()
        w2 = self.w = ui.Window(self.app, self.index, 'en')
        self.assertEqual(w2.columns['name'].get_fixed_width(), 222)
        self.assertEqual(w2.win.get_default_size(), (700, 420))
        self.assertEqual((w2.sort, w2.desc), ('size', True))
        self.assertTrue(w2.columns['size'].get_sort_indicator())

    def test_column_order_drag_settings_and_restore(self):
        w = self.window()
        self.type('report')
        titles = lambda: [c.get_title() for c in w.tree.get_columns()]  # noqa: E731
        self.assertEqual(w.column_order(), list(ui.DATA_COLUMNS))
        cols = w.columns
        self.assertTrue(all(cols[k].get_reorderable() for k in ui.DATA_COLUMNS))
        self.assertFalse(cols['locate'].get_reorderable())
        # what a header drag does; nothing may land after the locate column
        w.tree.move_column_after(cols['size'], None)
        self.assertEqual(w.column_order(), ['size', 'name', 'path', 'mtime'])
        self.assertEqual(titles(), ['Size', 'Name', 'Path', 'Modified', 'Locate'])
        self.assertFalse(w.column_drop_ok(w.tree, cols['name'], cols['locate'], None))
        self.assertFalse(w.column_drop_ok(w.tree, cols['locate'], None, cols['size']))
        self.assertTrue(w.column_drop_ok(w.tree, cols['name'], None, cols['size']))
        self.assertTrue(w.column_drop_ok(w.tree, cols['name'], cols['mtime'], cols['locate']))
        pump(0.05)
        self.assertEqual(w.store[0][1], 'Report 2024.pdf')        # cells keep their data
        # the same in Settings, by keyboard-reachable buttons; applied on Save
        s = w.open_settings()
        self.assertEqual(s.order, ['size', 'name', 'path', 'mtime'])
        rows = s.columns_box.get_children()
        self.assertEqual(len(rows), 4)
        first = [b for b in rows[0].get_child().get_children() if isinstance(b, ui.Gtk.Button)]
        self.assertFalse(first[0].get_sensitive())
        self.assertTrue(first[1].get_sensitive())
        self.assertEqual(first[1].get_accessible().get_name(), 'Move Size down')
        s.move_column(0, 1)
        self.assertEqual(s.order, ['name', 'size', 'path', 'mtime'])
        s.reset_columns()
        self.assertEqual(s.order, list(ui.DATA_COLUMNS))
        s.move_column(3, -1)
        self.assertEqual(s.order, ['name', 'path', 'mtime', 'size'])
        self.assertEqual(w.column_order(), ['size', 'name', 'path', 'mtime'])     # not before Save
        self.assertEqual(s.save(), 'saved')
        self.assertEqual(w.column_order(), ['name', 'path', 'mtime', 'size'])
        self.assertEqual(titles()[-1], 'Locate')
        w.on_delete()
        self.assertTrue(pump(until=lambda: self.quit_called))
        state = ui.load_ui_state(os.path.join(self.tmp, 'ui-state.json'))
        self.assertEqual(state['order'], ['name', 'path', 'mtime', 'size'])
        w.win.destroy()
        w2 = self.w = ui.Window(self.app, self.index, 'en')
        self.assertEqual(w2.column_order(), ['name', 'path', 'mtime', 'size'])
        self.assertIs(w2.tree.get_columns()[-1], w2.columns['locate'])

    def test_match_path_setting(self):
        w = self.window()
        self.type('old 2019')
        self.assertEqual(self.names(), ['report-2019.pdf'])
        s = w.open_settings()
        self.assertTrue(s.match_path.get_active())
        s.match_path.set_active(False)
        self.assertEqual(s.save(), 'saved')
        pump(0.05)
        self.assertEqual(self.names(), [])
        self.assertFalse(core.Config(os.path.join(self.tmp, 'config.json')).match_path())
        self.assertEqual(self.index.state, 'ready')            # no rescan for this setting
        s = w.open_settings()
        self.assertFalse(s.match_path.get_active())
        s.move_column(0, 1)
        s.restore_defaults()
        self.assertTrue(s.match_path.get_active())
        self.assertEqual(s.order, list(ui.DATA_COLUMNS))
        self.assertEqual(s.keys['toggle'], ui.DEFAULT_TOGGLE)
        s.dialog.destroy()

    def test_notice_shown_after_loading(self):
        self.w = ui.Window(self.app, self.index, 'en', notice=('Shortcut note.', 'warn'))
        self.w.quit = lambda: setattr(self, 'quit_called', True)
        self.w.start()
        w = self.w
        self.assertTrue(pump(until=lambda: self.index.state == 'ready' and not w.worker.is_alive()))
        pump(0.2)
        # kept over the searches that follow loading, until the user types
        self.assertEqual(w.hint.get_text(), 'Shortcut note.')
        self.assertIsNone(w.notice)
        self.type('report')
        self.assertTrue(w.status.get_text().startswith('3 results'))

    def test_bad_ui_state_uses_defaults(self):
        state = os.path.join(self.tmp, 'ui-state.json')
        with open(state, 'w') as f:
            f.write('{not json')
        self.assertEqual(ui.load_ui_state(state), {})
        with open(state, 'w') as f:
            f.write('[]')
        self.assertEqual(ui.load_ui_state(state), {})
        import json
        with open(state, 'w') as f:
            json.dump({'width': 'wide', 'height': 500, 'sort': 'colour', 'desc': 1, 'maximized': False,
                       'columns': {'name': 3, 'path': -5, 'bogus': 50}, 'x': 10,
                       'order': ['name', 'name', 'size', 'mtime']}, f)
        self.assertEqual(ui.load_ui_state(state), {'height': 500, 'maximized': False,
                                                   'columns': {'name': ui.MIN_COLUMN_WIDTH}, 'x': 10})
        w = self.window(start=False)
        self.assertEqual(w.win.get_default_size(), (ui.DEFAULT_SIZE[0], 500))
        self.assertEqual(w.columns['path'].get_fixed_width(), ui.COLUMN_WIDTHS['path'])
        self.assertEqual(w.sort, core.DEFAULT_SORT)
        self.assertEqual(w.column_order(), list(ui.DATA_COLUMNS))
        for bad in ('name', ['name', 'path', 'size'], ['name', 'path', 'size', 'mtime', 'locate'],
                    ['name', 'path', 'size', 'bogus'], [1, 2, 3, 4]):
            with open(state, 'w') as f:
                json.dump({'order': bad}, f)
            self.assertEqual(ui.load_ui_state(state), {}, bad)
        with open(state, 'w') as f:
            json.dump({'order': ['mtime', 'size', 'path', 'name']}, f)
        self.assertEqual(ui.load_ui_state(state), {'order': ['mtime', 'size', 'path', 'name']})
        self.assertFalse(w.can_place(-50000, -50000))
        self.assertTrue(w.can_place(0, 0))

    def test_opacity_follows_focus(self):
        w = self.window()
        w.composited = lambda: True
        w.window_active = lambda: False
        w.update_opacity()
        self.assertAlmostEqual(ui.Gtk.Widget.get_opacity(w.win), ui.UNFOCUSED_OPACITY, places=2)
        w.window_active = lambda: True
        w.update_opacity()
        self.assertAlmostEqual(ui.Gtk.Widget.get_opacity(w.win), 1.0, places=2)
        # the context menu or a dialog of the window does not count as leaving it
        self.type('report')
        w.cur = 0
        w.popup_menu(None)
        w.window_active = lambda: False
        self.assertTrue(w.own_popup_active())
        w.update_opacity()
        self.assertAlmostEqual(ui.Gtk.Widget.get_opacity(w.win), 1.0, places=2)
        w.menu.popdown()
        w.update_opacity()
        self.assertAlmostEqual(ui.Gtk.Widget.get_opacity(w.win), ui.UNFOCUSED_OPACITY, places=2)
        # without a compositor the window stays opaque
        w.composited = lambda: False
        w.update_opacity()
        self.assertAlmostEqual(ui.Gtk.Widget.get_opacity(w.win), 1.0, places=2)

    def test_rows_are_compact(self):
        w = self.window()
        self.type('')
        pump(0.2)
        Gtk = ui.Gtk
        ref = Gtk.Window()
        store = Gtk.ListStore(str)
        store.append(['report-draft.docx'])
        tv = Gtk.TreeView(model=store)
        col = Gtk.TreeViewColumn('x')
        cell = Gtk.CellRendererText()
        col.pack_start(cell, True)
        col.add_attribute(cell, 'text', 0)
        tv.append_column(col)
        ref.add(tv)
        ref.show_all()
        pump(0.2)
        default = tv.get_background_area(Gtk.TreePath.new_first(), col).height
        ref.destroy()
        self.assertGreater(w.row_height, 0)
        self.assertLess(w.row_height, default)

    def height(self):
        pump(0.3)
        return self.w.win.get_size()[1]

    def test_list_folds_under_an_empty_search_box(self):
        w = self.window()
        Gdk = ui.Gdk
        self.assertFalse(w.expanded)
        self.assertFalse(w.list_area.get_visible())
        self.assertFalse(w.bar.get_visible())
        self.assertTrue(w.hint.get_visible())
        self.assertLess(self.height(), 120)
        self.assertEqual(w.hint.get_text(), '11 items')
        self.assertIn('v' + core.VERSION, w.entry.get_tooltip_text())
        # typing unfolds to the remembered height; no match still unfolds and says so
        self.type('report')
        self.assertTrue(w.expanded and w.list_area.get_visible() and w.bar.get_visible())
        self.assertGreater(self.height(), 500)
        self.assertFalse(w.empty.get_visible())
        w.win.resize(800, 450)
        self.assertEqual(self.height(), 450)
        self.type('nothing-like-this')
        self.assertTrue(w.expanded)
        self.assertTrue(w.empty.get_visible())
        self.assertEqual(w.empty.get_text(), 'No matches')
        # Escape: clear and fold, then close; the folded height is not remembered
        w.on_entry_key(w.entry, key(Gdk.KEY_Escape))
        self.assertTrue(pump(until=lambda: w.expanded is False))
        self.assertLess(self.height(), 120)
        self.assertFalse(self.quit_called)
        self.type('report')
        self.assertEqual(self.height(), 450)
        self.type('')
        pump(0.2)
        w.on_entry_key(w.entry, key(Gdk.KEY_Escape))
        self.assertTrue(pump(until=lambda: self.quit_called))
        import json
        with open(w.state_path, encoding='utf-8') as f:
            self.assertEqual(json.load(f)['height'], 450)

    def test_messages_show_in_the_folded_box(self):
        w = self.window()
        self.assertFalse(w.expanded)
        w.show_message('Something failed: reason.', 'bad', seconds=1)
        self.assertEqual(w.hint.get_text(), 'Something failed: reason.')
        self.assertTrue(w.hint.get_style_context().has_class('error'))
        self.assertTrue(pump(until=lambda: w.hint.get_text() == '11 items'))
        self.assertFalse(w.hint.get_style_context().has_class('error'))

    def test_maximised_window_does_not_fold(self):
        w = self.window()
        w.maximized = True
        w.apply_layout()
        self.assertTrue(w.expanded)
        self.assertTrue(w.list_area.get_visible())
        w.maximized = False
        w.apply_layout()
        self.assertFalse(w.expanded)

    def press(self, widget_handler, keyval, mods=0):
        return widget_handler(None, key(keyval, ui.Gdk.ModifierType(mods)))

    def test_shortcuts_recorded_saved_and_used(self):
        import test_keys
        w = self.window()
        Gdk = ui.Gdk
        fake = test_keys.gnome()
        w.hotkey = ui.DesktopHotkey(run=fake.run, env={'XDG_CURRENT_DESKTOP': 'GNOME'}, which=fake.which)
        s = w.open_settings()
        self.assertEqual(s.key_buttons['copy_path'].get_label(), ui.Gtk.accelerator_get_label(
            *ui.Gtk.accelerator_parse('<Primary><Shift>c')))
        self.assertFalse(s.copy_command.get_visible())
        # record Alt+L for locate; a fixed key and a plain letter are refused
        s.record('locate')
        self.assertTrue(self.press(s.on_key, Gdk.KEY_Return))
        self.assertIn('cannot be a shortcut', s.problems.get_text())
        self.assertEqual(s.keys['locate'], '<Primary>Return')
        s.record('locate')
        self.press(s.on_key, Gdk.KEY_q)
        self.assertIn('would take over typing', s.problems.get_text())
        s.record('locate')
        self.press(s.on_key, Gdk.KEY_Alt_L, Gdk.ModifierType.MOD1_MASK)     # a modifier alone waits
        self.assertEqual(s.recording, 'locate')
        self.press(s.on_key, Gdk.KEY_l, Gdk.ModifierType.MOD1_MASK)
        self.assertEqual(s.keys['locate'], '<Alt>l')
        s.record('open')
        self.press(s.on_key, Gdk.KEY_Escape)                                # Esc cancels recording
        self.assertIsNone(s.recording)
        self.assertEqual(s.keys['open'], '')
        # the same keys twice cannot be saved
        s.record('rescan')
        self.press(s.on_key, Gdk.KEY_l, Gdk.ModifierType.MOD1_MASK)
        self.assertEqual(s.save(), 'blocked')
        self.assertIn('same shortcut', s.problems.get_text())
        s.set_key('rescan', 'F6')
        # a global shortcut already used by the desktop is listed first
        s.set_key('toggle', '<Super>t')
        self.assertEqual(s.save(), 'warn')
        self.assertIn('Terminal', s.problems.get_text())
        s.set_key('toggle', '<Primary><Alt>f')
        self.assertEqual(s.save(), 'saved')
        saved = core.Config(os.path.join(self.tmp, 'config.json')).other['keys']
        self.assertEqual(saved['locate'], '<Alt>l')
        self.assertEqual(saved['rescan'], 'F6')
        self.assertEqual(saved['toggle'], '<Primary><Alt>f')
        self.assertNotIn('copy_file', saved)                                # defaults are not written
        where = ui.DesktopHotkey.GNOME_ENTRY + ':' + ui.DesktopHotkey.GNOME_PATH
        self.assertEqual(fake.values[(where, 'binding')], "'<Primary><Alt>f'")
        self.assertIn('--toggle', fake.values[(where, 'command')])
        # the new keys work at once; the old ones no longer do
        self.type('report')
        located = []
        w.show_in_file_manager = lambda p: located.append(p) or True
        w.cur = 0
        self.assertTrue(w.on_tree_key(w.tree, key(Gdk.KEY_l, Gdk.ModifierType.MOD1_MASK)))
        self.assertEqual(len(located), 1)
        w.on_tree_key(w.tree, key(Gdk.KEY_Return, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(len(located), 1)
        refreshed = []
        w.start_refresh = lambda: refreshed.append(1)
        w.apply_keys(w.keys)
        self.assertTrue(self.accel(Gdk.KEY_F6))
        self.assertFalse(self.accel(Gdk.KEY_F5))
        self.assertEqual(refreshed, [1])
        # clearing the global shortcut removes it from the desktop again
        s = w.open_settings()
        s.set_key('toggle', '')
        self.assertEqual(s.save(), 'saved')
        self.assertNotIn((where, 'binding'), fake.values)

    def test_shortcuts_on_an_unknown_desktop(self):
        import test_keys
        w = self.window()
        fake = test_keys.gnome()
        w.hotkey = ui.DesktopHotkey(run=fake.run, env={'XDG_CURRENT_DESKTOP': 'XFCE'}, which=fake.which)
        s = w.open_settings()
        self.assertTrue(s.copy_command.get_visible())
        self.assertIn('--toggle', s.key_note.get_text())
        s.copy_toggle_command()
        self.assertIn('--toggle', ui.Gtk.Clipboard.get(ui.Gdk.SELECTION_CLIPBOARD).wait_for_text())
        s.set_key('toggle', '<Primary><Alt>f')
        self.assertEqual(s.save(), 'saved')
        self.assertFalse(any(c[1] == 'set' for c in fake.calls))
        self.assertEqual(core.Config(os.path.join(self.tmp, 'config.json')).other['keys']['toggle'], '<Primary><Alt>f')

    def test_toggle(self):
        w = self.window()
        active = [True]
        w.window_active = lambda: active[0]
        w.toggle()
        self.assertFalse(w.win.get_visible())               # in front: hidden
        w.entry.set_text('report')
        w.toggle()
        self.assertTrue(w.win.get_visible())                # hidden: shown with the text selected
        self.assertEqual(w.entry.get_selection_bounds(), (0, 6))
        active[0] = False
        w.toggle()
        self.assertTrue(w.win.get_visible())                # behind another window: brought forward
        self.assertFalse(self.quit_called)

    def test_toggle_action_of_the_application(self):
        app = ui.build_app(self.index, 'en')
        self.assertIsNotNone(app.lookup_action('toggle'))

    def test_open_missing_file(self):
        w = self.window()
        self.type('notes')
        os.remove(os.path.join(self.root, 'docs', 'notes.txt'))
        w.open_uri = lambda uri: self.fail('should not open')
        w.cur = 0
        w.open_current()
        self.assertTrue(w.status.get_text().startswith('Open failed'))

    def test_live_update(self):
        w = self.window()
        if self.index.watcher is None:
            self.skipTest('inotify unavailable')
        self.assertTrue(pump(until=lambda: self.index.watcher.watched() >= 4))
        self.type('fresh-file')
        self.assertEqual(len(w.store), 0)
        touch(os.path.join(self.root, 'pics', 'fresh-file.txt'))
        self.assertTrue(pump(until=lambda: self.names() == ['fresh-file.txt']))

    def test_rows_fit_the_area(self):
        w = self.window()
        self.type('')
        w.win.resize(800, 300)
        pump(0.3)
        self.assertTrue(pump(until=lambda: len(w.store) == min(w.rows, len(w.result))))
        header = w.columns['name'].get_button().get_allocated_height()
        self.assertLessEqual(header + w.rows * w.row_height, w.area_height)
        self.assertEqual(len(w.store), min(w.rows, 11))

    def test_million_entries_scroll_and_sort(self):
        import bench
        w = self.window(start=False)
        self.index.base = core.build_base(bench.synthetic_records(1000000))
        self.index._reset_overlay()
        self.index.state = 'ready'
        w.run_search()
        pump(0.3)
        n = len(w.result)
        self.assertGreater(n, 999999)
        self.assertEqual(w.adj.get_upper(), n)
        timings = {}
        t = time.perf_counter()
        w.adj.set_value(n // 2)
        timings['scroll to middle'] = time.perf_counter() - t
        self.assertEqual(w.top, n // 2)
        t = time.perf_counter()
        w.on_tree_key(w.tree, key(ui.Gdk.KEY_End))
        timings['End'] = time.perf_counter() - t
        self.assertEqual(w.cur, n - 1)
        self.assertEqual(len(w.store), w.rows)
        for col in ('name', 'size', 'path', 'mtime'):
            t = time.perf_counter()
            w.columns[col].clicked()
            timings['sort ' + col] = time.perf_counter() - t
            self.assertEqual(len(w.result), n)
        self.type('report')
        t = time.perf_counter()
        w.on_tree_key(w.tree, key(ui.Gdk.KEY_End))
        timings['End in result'] = time.perf_counter() - t
        sys.stderr.write('\n' + ', '.join('%s %.0f ms' % (k, v * 1000) for k, v in timings.items()) + '\n')
        for k, v in timings.items():
            self.assertLess(v, 0.5, k)


if __name__ == '__main__':
    unittest.main()

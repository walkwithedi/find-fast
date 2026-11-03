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
        self.assertEqual([c.get_title() for c in w.tree.get_columns()], ['名称', '路径', '大小', '修改时间'])
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
        w.on_tree_key(w.tree, key(Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK))
        pump(0.05)
        clip = ui.Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        self.assertEqual(clip, os.path.join(self.root, 'docs', 'report-draft.docx'))
        self.assertTrue(w.status.get_text().startswith('Path copied'))
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
        self.assertEqual(w.tree.get_tooltip_column(), ui.COL_TIP)
        for j, row in enumerate(w.store):
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

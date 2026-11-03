"""Tests of the shortcut settings and of writing the global shortcut into the desktop settings.
gsettings and dconf are replaced by a stand-in: the real desktop is never changed."""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import find_fast_core as core  # noqa: E402
import find_fast_gtk as ui  # noqa: E402


class FakeSettings:
    """Just enough of gsettings and dconf: values by (schema[:path], key), as text."""

    def __init__(self, schemas, values=None, dconf=True):
        self.schemas = set(schemas)
        self.values = dict(values or {})
        self.dconf = dconf
        self.calls = []

    def run(self, args):
        self.calls.append(list(args))
        tool, cmd = args[0], args[1]
        if tool == 'gsettings':
            if cmd == 'list-schemas':
                return 0, '\n'.join(sorted(self.schemas)) + '\n'
            if cmd == 'get':
                v = self.values.get((args[2], args[3]))
                if v is None:
                    return (0, "''\n") if ':' in args[2] else (1, '')
                return 0, v + '\n'
            if cmd == 'set':
                self.values[(args[2], args[3])] = args[4]
                return 0, ''
            if cmd == 'reset':
                self.values.pop((args[2], args[3]), None)
                return 0, ''
            if cmd == 'list-recursively':
                return 0, ''.join('%s %s %s\n' % (s, k, v) for (s, k), v in self.values.items() if s == args[2])
        if tool == 'dconf' and self.dconf:
            if cmd == 'list':
                subs = sorted({s.split(':', 1)[1][len(args[2]):].split('/')[0] + '/'
                               for (s, _), _v in self.values.items()
                               if ':' in s and s.split(':', 1)[1].startswith(args[2])})
                return 0, '\n'.join(subs) + '\n'
            if cmd == 'reset':
                for key in [k for k in self.values if ':' in k[0] and k[0].split(':', 1)[1].startswith(args[3])]:
                    del self.values[key]
                return 0, ''
        return 1, ''

    def which(self, name):
        return '/usr/bin/' + name if name == 'gsettings' or (name == 'dconf' and self.dconf) else None


H = ui.DesktopHotkey


def gnome():
    return FakeSettings([H.GNOME_LIST[0], H.GNOME_ENTRY, 'org.gnome.desktop.wm.keybindings'], {
        (H.GNOME_LIST[0], H.GNOME_LIST[1]): "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/']",
        (H.GNOME_ENTRY + ':/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/', 'binding'):
            "'<Super>t'",
        (H.GNOME_ENTRY + ':/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/', 'name'):
            "'Terminal'",
        ('org.gnome.desktop.wm.keybindings', 'close'): "['<Alt>F4']",
    })


def ukui():
    return FakeSettings([H.UKUI_ENTRY, 'org.ukui.SettingsDaemon.plugins.media-keys'], {
        (H.UKUI_ENTRY + ':' + H.UKUI_DIR + 'custom0/', 'binding'): "'<Primary><Alt>t'",
        (H.UKUI_ENTRY + ':' + H.UKUI_DIR + 'custom0/', 'name'): "'Example'",
        ('org.ukui.SettingsDaemon.plugins.media-keys', 'screenshot'): "'Print'",
    })


class AccelTest(unittest.TestCase):
    def test_canonical(self):
        self.assertEqual(ui.canonical_accel('<Control><shift>C'), '<Primary><Shift>c')
        self.assertEqual(ui.canonical_accel('<Shift><Primary>c'), '<Primary><Shift>c')
        self.assertEqual(ui.canonical_accel('<Ctrl><Alt>T'), ui.canonical_accel('<Primary><Mod1>t'))
        self.assertEqual(ui.canonical_accel(''), '')
        for bad in ('<Ctrl>', '<Nope>a', 'a<Ctrl>', None, 5):
            self.assertIsNone(ui.canonical_accel(bad), bad)

    def test_fixed_and_plain_keys(self):
        for key in ('Return', 'Escape', 'Up', '<Shift>Down', 'KP_Enter'):
            self.assertTrue(ui.is_fixed_key(key), key)
        for key in ('<Primary>Return', 'F5', '<Primary>c', ''):
            self.assertFalse(ui.is_fixed_key(key), key)
        for key in ('F5', 'F12', '<Primary>c', '<Alt>x', '<Super>space', ''):
            self.assertTrue(ui.plain_key_ok(key), key)
        for key in ('a', '<Shift>a', 'space', 'Delete'):
            self.assertFalse(ui.plain_key_ok(key), key)

    def test_load_keys(self):
        c = core.Config('/nonexistent-dir/config.json', {'keys': {'locate': '<Alt>l', 'copy_file': 'Return',
                                                                  'rescan': '<Bad>x', 'unknown': 'F2',
                                                                  'focus': 'q', 'toggle': 'Escape'}})
        keys = ui.load_keys(c)
        self.assertEqual(keys['focus'], ui.KEY_DEFAULTS['focus'])               # a plain letter is refused
        self.assertEqual(keys['toggle'], '')
        self.assertEqual(keys['locate'], '<Alt>l')
        self.assertEqual(keys['copy_file'], ui.KEY_DEFAULTS['copy_file'])        # a fixed key is refused
        self.assertEqual(keys['rescan'], ui.KEY_DEFAULTS['rescan'])
        self.assertNotIn('unknown', keys)
        self.assertEqual(ui.load_keys(core.Config('/nonexistent-dir/c.json', {'keys': 'x'})), ui.KEY_DEFAULTS)

    def test_defaults_do_not_clash(self):
        self.assertEqual(ui.key_clashes(ui.KEY_DEFAULTS), [])
        keys = dict(ui.KEY_DEFAULTS, rescan='<Control>c')
        self.assertEqual(ui.key_clashes(keys), [('rescan', 'copy_file')])


class HotkeyTest(unittest.TestCase):
    def hk(self, fake, desktop):
        return ui.DesktopHotkey(run=fake.run, env={'XDG_CURRENT_DESKTOP': desktop}, which=fake.which)

    def test_desktop_detection(self):
        self.assertEqual(self.hk(gnome(), 'ubuntu:GNOME').desktop(), 'gnome')
        self.assertEqual(self.hk(ukui(), 'UKUI').desktop(), 'ukui')
        self.assertIsNone(self.hk(gnome(), 'XFCE').desktop())
        no_dconf = ukui()
        no_dconf.dconf = False
        self.assertIsNone(self.hk(no_dconf, 'UKUI').desktop())
        self.assertIsNone(ui.DesktopHotkey(run=gnome().run, env={'XDG_CURRENT_DESKTOP': 'GNOME'},
                                           which=lambda n: None).desktop())

    def test_gnome_write_and_remove_only_its_own(self):
        fake = gnome()
        hk = self.hk(fake, 'GNOME')
        hk.write('<Primary><Alt>f', "python3 '/tool dir/find_fast.py' --toggle", '秒搜文件')
        paths = ui._gs_list(fake.values[H.GNOME_LIST])
        self.assertEqual(paths, ['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/',
                                 H.GNOME_PATH])
        where = H.GNOME_ENTRY + ':' + H.GNOME_PATH
        self.assertEqual(fake.values[(where, 'binding')], "'<Primary><Alt>f'")
        self.assertEqual(fake.values[(where, 'command')], "'python3 \\'/tool dir/find_fast.py\\' --toggle'")
        self.assertEqual(fake.values[(where, 'name')], "'秒搜文件'")
        hk.write('<Primary><Alt>g', 'cmd --toggle', 'x')        # updating does not add it twice
        self.assertEqual(len(ui._gs_list(fake.values[H.GNOME_LIST])), 2)
        self.assertTrue(hk.remove())
        self.assertEqual(ui._gs_list(fake.values[H.GNOME_LIST]),
                         ['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/'])
        self.assertNotIn((where, 'binding'), fake.values)
        self.assertIn((H.GNOME_ENTRY + ':/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/',
                       'binding'), fake.values)
        self.assertFalse(hk.remove())

    def test_gnome_conflicts(self):
        hk = self.hk(gnome(), 'GNOME')
        self.assertEqual(hk.taken('<Super>T'), 'Terminal')
        self.assertEqual(hk.taken('<Alt>F4'), 'close')
        self.assertIsNone(hk.taken('<Primary><Alt>f'))

    def test_ukui_write_conflicts_and_remove(self):
        fake = ukui()
        hk = self.hk(fake, 'UKUI')
        self.assertEqual(hk.taken('<Control><Alt>T'), 'Example')
        self.assertEqual(hk.taken('Print'), 'screenshot')
        hk.write('<Primary><Alt>f', 'cmd --toggle', '秒搜文件')
        where = H.UKUI_ENTRY + ':' + H.UKUI_PATH
        self.assertEqual(fake.values[(where, 'action')], "'cmd --toggle'")
        self.assertIsNone(hk.taken('<Primary><Alt>f'))           # its own entry does not count
        self.assertTrue(hk.remove())
        self.assertNotIn((where, 'binding'), fake.values)
        self.assertIn((H.UKUI_ENTRY + ':' + H.UKUI_DIR + 'custom0/', 'binding'), fake.values)
        self.assertFalse(hk.remove())

    def test_unsupported_desktop(self):
        fake = gnome()
        hk = self.hk(fake, 'XFCE')
        with self.assertRaises(OSError):
            hk.write('<Primary><Alt>f', 'cmd', 'x')
        self.assertFalse(hk.remove())
        self.assertIsNone(hk.taken('<Super>t'))
        self.assertFalse(any(c[1] == 'set' for c in fake.calls))

    def test_toggle_command(self):
        tmp = tempfile.mkdtemp(prefix='ff-keys-')
        try:
            home = os.path.join(tmp, 'home')
            installed = os.path.join(home, '.local', 'share', 'find-fast')
            os.makedirs(installed)
            os.makedirs(os.path.join(home, '.local', 'bin'))
            open(os.path.join(home, '.local', 'bin', 'find-fast'), 'w').close()
            old = os.environ.pop('XDG_DATA_HOME', None)
            try:
                cmd, inst = ui.toggle_command(here=installed, home=home)
                self.assertTrue(inst)
                self.assertEqual(cmd, os.path.join(home, '.local', 'bin', 'find-fast') + ' --toggle')
                cmd, inst = ui.toggle_command(here=os.path.join(tmp, 'unpacked dir'), home=home)
                self.assertFalse(inst)
                self.assertEqual(cmd, "python3 '%s' --toggle" % os.path.join(tmp, 'unpacked dir', 'find_fast.py'))
            finally:
                if old is not None:
                    os.environ['XDG_DATA_HOME'] = old
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class DefaultToggleTest(unittest.TestCase):
    """The default global shortcut: written once when none was ever set and the keys are free."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='ff-keys-')
        self.path = os.path.join(self.tmp, 'config.json')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def config(self, data=None):
        return core.Config(self.path, dict(data or {}, roots=[self.tmp]))

    def hk(self, fake, desktop='GNOME'):
        return ui.DesktopHotkey(run=fake.run, env={'XDG_CURRENT_DESKTOP': desktop}, which=fake.which)

    def test_accel_text(self):
        self.assertEqual(ui.accel_text(ui.DEFAULT_TOGGLE), 'Ctrl+Alt+Space')
        self.assertEqual(ui.accel_text('<Shift><Super>f5'), 'Shift+Super+F5')
        self.assertEqual(ui.accel_text(''), '')

    def test_written_once_when_free(self):
        fake = gnome()
        c = self.config()
        text, kind = ui.ensure_default_toggle(c, self.hk(fake), 'zh')
        self.assertEqual(kind, 'ok')
        self.assertIn('Ctrl+Alt+Space', text)
        where = H.GNOME_ENTRY + ':' + H.GNOME_PATH
        self.assertEqual(fake.values[(where, 'binding')], "'<Primary><Alt>space'")
        self.assertIn('--toggle', fake.values[(where, 'command')])
        saved = core.Config(self.path)
        self.assertEqual(saved.other['keys'], {'toggle': ui.DEFAULT_TOGGLE})
        self.assertTrue(saved.other['toggle_default_done'])
        self.assertEqual(ui.load_keys(saved)['toggle'], ui.DEFAULT_TOGGLE)
        # a second start does nothing, even after the user cleared the shortcut
        saved.other['keys'] = {'toggle': ''}
        fake.calls.clear()
        self.assertIsNone(ui.ensure_default_toggle(saved, self.hk(fake), 'zh'))
        self.assertFalse(any(c[1] == 'set' for c in fake.calls))

    def test_left_alone_when_set_or_cleared_before(self):
        for keys in ({'toggle': ''}, {'toggle': '<Super>f'}):
            fake = gnome()
            c = self.config({'keys': dict(keys, locate='<Alt>l')})
            self.assertIsNone(ui.ensure_default_toggle(c, self.hk(fake), 'en'))
            self.assertFalse(any(x[1] == 'set' for x in fake.calls))
            saved = core.Config(self.path)
            self.assertTrue(saved.other['toggle_default_done'])
            self.assertEqual(saved.other['keys'], dict(keys, locate='<Alt>l'))

    def test_taken_keys_not_written(self):
        fake = ukui()
        fake.values[('org.ukui.SettingsDaemon.plugins.media-keys', 'search')] = "'<Control><Alt>space'"
        c = self.config({'keys': {'locate': '<Alt>l'}})
        text, kind = ui.ensure_default_toggle(c, self.hk(fake, 'UKUI'), 'zh')
        self.assertEqual(kind, 'warn')
        self.assertTrue(text.startswith('设置默认唤起快捷键失败：Ctrl+Alt+Space 已被桌面快捷键「search」占用。'), text)
        self.assertNotIn((H.UKUI_ENTRY + ':' + H.UKUI_PATH, 'binding'), fake.values)
        saved = core.Config(self.path)
        self.assertEqual(saved.other['keys'], {'locate': '<Alt>l'})
        self.assertTrue(saved.other['toggle_default_done'])
        self.assertIsNone(ui.ensure_default_toggle(saved, self.hk(fake, 'UKUI'), 'zh'))

    def test_unknown_desktop_and_write_error(self):
        fake = gnome()
        text, kind = ui.ensure_default_toggle(self.config(), self.hk(fake, 'XFCE'), 'en')
        self.assertEqual(kind, 'warn')
        self.assertIn('--toggle', text)
        self.assertFalse(any(x[1] == 'set' for x in fake.calls))

        class Failing(FakeSettings):
            def run(self, args):
                if args[:2] == ['gsettings', 'set']:
                    return 1, ''
                return FakeSettings.run(self, args)

        os.remove(self.path)
        broken = Failing(gnome().schemas, gnome().values)
        text, kind = ui.ensure_default_toggle(self.config(), self.hk(broken), 'zh')
        self.assertEqual(kind, 'bad')
        self.assertTrue(text.startswith('设置默认唤起快捷键失败：写入系统快捷键时出错'), text)
        self.assertNotIn('toggle', core.Config(self.path).other.get('keys', {}))

    def test_refresh_rewrites_the_command(self):
        fake = gnome()
        c = self.config({'keys': {'toggle': '<Super>f'}, 'toggle_default_done': True})
        self.assertIsNone(ui.ensure_default_toggle(c, self.hk(fake), 'en'))
        self.assertFalse(any(x[1] == 'set' for x in fake.calls))
        self.assertIsNone(ui.ensure_default_toggle(c, self.hk(fake), 'en', refresh=True))
        where = H.GNOME_ENTRY + ':' + H.GNOME_PATH
        self.assertEqual(fake.values[(where, 'binding')], "'<Super>f'")
        self.assertIn('--toggle', fake.values[(where, 'command')])

    def test_default_toggle_is_a_valid_shortcut(self):
        self.assertEqual(ui.KEY_DEFAULTS['toggle'], '')
        self.assertTrue(ui.plain_key_ok(ui.DEFAULT_TOGGLE))
        self.assertFalse(ui.is_fixed_key(ui.DEFAULT_TOGGLE))


if __name__ == '__main__':
    unittest.main()

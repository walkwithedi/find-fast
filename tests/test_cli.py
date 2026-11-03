"""Tests of the command line (find_fast.py with a query)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tests'))
from test_core import make_tree  # noqa: E402


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='ff-cli-')
        self.root = os.path.join(self.tmp, 'root')
        make_tree(self.root)
        self.config = os.path.join(self.tmp, 'config.json')
        with open(self.config, 'w', encoding='utf-8') as f:
            json.dump({'roots': [self.root]}, f)
        self.cache = os.path.join(self.tmp, 'index.bin')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_ff(self, *args):
        env = dict(os.environ, LANG='en_US.UTF-8')
        return subprocess.run([sys.executable, os.path.join(ROOT, 'find_fast.py'), '--config', self.config,
                               '--cache', self.cache] + list(args), capture_output=True, text=True, env=env,
                              timeout=60)

    def test_first_run_builds_index_and_prints_paths(self):
        p = self.run_ff('report', 'pdf', '--sort', 'path', '--asc')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.splitlines(), [os.path.join(self.root, 'docs', 'Report 2024.pdf'),
                                                 os.path.join(self.root, 'docs', 'old', 'report-2019.pdf')])
        self.assertIn('building it for the first time', p.stderr)
        self.assertTrue(os.path.exists(self.cache))
        p = self.run_ff('report', 'pdf')
        self.assertNotIn('first time', p.stderr)

    def test_count_limit_null_and_no_match(self):
        self.assertEqual(self.run_ff('report', '--count').stdout.strip(), '3')
        self.assertEqual(len(self.run_ff('report', '--limit', '1').stdout.splitlines()), 1)
        out = self.run_ff('ext:txt', '-0').stdout
        self.assertEqual(out.count('\0'), 3)
        p = self.run_ff('nothing-matches-this')
        self.assertEqual((p.returncode, p.stdout), (1, ''))

    def test_bad_regex(self):
        p = self.run_ff('(', '--regex')
        self.assertEqual(p.returncode, 2)
        self.assertIn('Invalid regular expression', p.stderr)

    def test_update_and_status(self):
        self.run_ff('x', '--count')
        with open(os.path.join(self.root, 'added-later.txt'), 'w'):
            pass
        self.assertEqual(self.run_ff('added-later').stdout, '')
        self.assertEqual(self.run_ff('added-later', '--update', '--count').stdout.strip(), '1')
        st = json.loads(self.run_ff('--status').stdout)
        self.assertEqual(st['state'], 'ready')
        self.assertEqual(st['entries'], 12)

    def test_remove_hotkey_without_a_desktop(self):
        # no gsettings on PATH and no desktop: nothing to remove, nothing touched
        env = {'PATH': os.path.join(self.tmp, 'empty-bin'), 'LANG': 'en_US.UTF-8', 'HOME': self.tmp}
        p = subprocess.run([sys.executable, os.path.join(ROOT, 'find_fast.py'), '--remove-hotkey',
                            '--log-level', 'INFO'], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('global shortcut not found', p.stderr)

    def test_default_hotkey_without_a_desktop(self):
        # no desktop to write to: said once, recorded in the settings, nothing touched
        env = {'PATH': os.path.join(self.tmp, 'empty-bin'), 'LANG': 'en_US.UTF-8', 'HOME': self.tmp}
        config = os.path.join(self.tmp, 'ff-config.json')
        cmd = [sys.executable, os.path.join(ROOT, 'find_fast.py'), '--default-hotkey', '--config', config]
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('Setting the default show-or-hide shortcut failed', p.stdout)
        with open(config, encoding='utf-8') as f:
            self.assertTrue(json.load(f)['toggle_default_done'])
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual((p.returncode, p.stdout), (0, ''))

    def test_words_match_folders_unless_turned_off(self):
        self.assertEqual(self.run_ff('old', '2019').stdout.strip(), os.path.join(self.root, 'docs', 'old', 'report-2019.pdf'))
        with open(self.config, encoding='utf-8') as f:
            data = json.load(f)
        data['match_path'] = False
        with open(self.config, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        self.assertEqual(self.run_ff('old', '2019').returncode, 1)


if __name__ == '__main__':
    unittest.main()

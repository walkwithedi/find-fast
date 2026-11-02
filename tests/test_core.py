"""Tests of find_fast_core: scanning, cache, query language, search order, overlay and inotify."""
import array
import itertools
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import find_fast_core as core  # noqa: E402


def touch(path, data=b'', mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def make_tree(root):
    """A small fictional tree."""
    touch(os.path.join(root, 'docs', 'Report 2024.pdf'), b'x' * 300, 1700000300)
    touch(os.path.join(root, 'docs', 'report-draft.docx'), b'x' * 20, 1700000200)
    touch(os.path.join(root, 'docs', 'notes.txt'), b'x', 1700000100)
    touch(os.path.join(root, 'docs', 'old', 'report-2019.pdf'), b'x' * 5, 1600000000)
    touch(os.path.join(root, 'pics', 'IMG_0001.jpg'), b'x' * 1000, 1700000400)
    touch(os.path.join(root, 'pics', '项目报告.pptx'), b'x' * 50, 1700000500)
    touch(os.path.join(root, '.hidden', 'secret-report.txt'), b'x', 1700000600)
    touch(os.path.join(root, 'node_modules', 'pkg', 'report.js'), b'x', 1700000700)
    touch(os.path.join(root, 'b.txt'), b'', 1700000000)
    touch(os.path.join(root, 'A.txt'), b'', 1700000000)


class TempTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='ff-test-')
        self.root = os.path.join(self.tmp, 'root')
        make_tree(self.root)
        self.cache = os.path.join(self.tmp, 'cache', 'index.bin')
        self.config = core.Config(os.path.join(self.tmp, 'config.json'), {'roots': [self.root]})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def index(self, refresh=True):
        idx = core.Index(self.config, self.cache, mounts={})
        if refresh:
            idx.refresh()
        return idx

    def names(self, result):
        return [result.row(k)[0] for k in range(len(result))]

    def rel(self, result):
        return [os.path.relpath(result.path(k), self.root) for k in range(len(result))]


class ScanTest(TempTree):
    def test_hidden_and_excluded_names_skipped(self):
        idx = self.index()
        found = self.rel(idx.search('', 'path', desc=False))
        self.assertNotIn('.hidden', found)
        self.assertFalse(any(p.startswith('.hidden') or p.startswith('node_modules') for p in found))
        self.assertIn('docs/old/report-2019.pdf', found)

    def test_hidden_option(self):
        self.config.hidden = True
        idx = self.index()
        self.assertIn('.hidden/secret-report.txt', self.rel(idx.search('secret')))

    def test_path_exclusion(self):
        self.config.exclude = [os.path.join(self.root, 'docs', 'old')]
        idx = self.index()
        self.assertEqual(self.rel(idx.search('2019')), [])

    def test_path_order_is_depth_first_by_lower_name(self):
        idx = self.index()
        self.assertEqual(self.rel(idx.search('', 'path', desc=False)), [
            'A.txt', 'b.txt', 'docs', 'pics',
            'docs/notes.txt', 'docs/old', 'docs/Report 2024.pdf', 'docs/report-draft.docx',
            'docs/old/report-2019.pdf',
            'pics/IMG_0001.jpg', 'pics/项目报告.pptx'])

    def test_folders_are_entries_with_size_minus_one(self):
        idx = self.index()
        r = idx.search('pics')
        self.assertEqual(self.names(r), ['pics'])
        self.assertEqual(r.row(0)[2], -1)

    def test_network_and_pseudo_mounts_skipped(self):
        net = os.path.join(self.root, 'docs')
        idx = core.Index(self.config, self.cache, mounts={net: 'nfs4'})
        idx.refresh()
        self.assertEqual(self.rel(idx.search('report')), [])
        self.assertTrue(core.fs_excluded('fuse.sshfs'))
        self.assertTrue(core.fs_excluded('proc'))
        self.assertFalse(core.fs_excluded('ext4'))
        self.assertFalse(core.fs_excluded('fuseblk'))
        self.assertFalse(core.fs_excluded('fuse.ntfs-3g'))

    def test_read_mounts_unescapes(self):
        p = os.path.join(self.tmp, 'mounts')
        with open(p, 'w') as f:
            f.write('/dev/sdb1 /x/my\\040disk ext4 rw 0 0\nserver:/x /x/net nfs4 rw 0 0\n')
        self.assertEqual(core.read_mounts(p), {'/x/my disk': 'ext4', '/x/net': 'nfs4'})

    def test_nested_roots_deduplicated(self):
        self.config.roots = [self.root, os.path.join(self.root, 'docs'), os.path.join(self.tmp, 'missing')]
        self.assertEqual(self.config.resolved_roots(), [self.root])

    def test_symlink_indexed_not_followed(self):
        os.symlink(os.path.join(self.root, 'docs'), os.path.join(self.root, 'link-to-docs'))
        idx = self.index()
        self.assertEqual(self.rel(idx.search('notes')), ['docs/notes.txt'])
        self.assertEqual(self.rel(idx.search('link-to')), ['link-to-docs'])

    def test_unreadable_folder_reported(self):
        if os.geteuid() == 0:
            self.skipTest('root reads every folder')
        locked = os.path.join(self.root, 'locked')
        os.makedirs(locked)
        os.chmod(locked, 0)
        try:
            idx = self.index()
            self.assertEqual(idx.unreadable_count, 1)
        finally:
            os.chmod(locked, 0o755)


class CacheTest(TempTree):
    def test_round_trip(self):
        idx = self.index()
        before = self.rel(idx.search('', 'name', desc=False))
        idx2 = self.index(refresh=False)
        self.assertTrue(idx2.load())
        self.assertEqual(self.rel(idx2.search('', 'name', desc=False)), before)
        self.assertEqual(idx2.base.n, idx.base.n)
        self.assertEqual(oct(os.stat(self.cache).st_mode & 0o777), '0o600')

    def test_other_settings_ignore_cache(self):
        self.index()
        self.config.hidden = True
        self.assertFalse(self.index(refresh=False).load())

    def test_corrupt_cache_ignored(self):
        self.index()
        with open(self.cache, 'r+b') as f:
            f.seek(40)
            f.write(b'garbage')
        self.assertFalse(self.index(refresh=False).load())
        with open(self.cache, 'wb') as f:
            f.write(core.MAGIC + b'\x05\x00')
        self.assertFalse(self.index(refresh=False).load())

    def test_incremental_refresh_reuses_unchanged_folders(self):
        idx = self.index()
        touch(os.path.join(self.root, 'pics', 'new.png'), b'', 1700000900)
        records, errors, changed = core.scan([self.root], self.config.excluder(), {}, idx.base)
        self.assertTrue(changed)
        idx.refresh()
        self.assertEqual(self.names(idx.search('new.png')), ['new.png'])
        # folders changed within RACY_NS of a scan are listed again; older ones are reused
        _, _, changed = core.scan([self.root], self.config.excluder(), {}, idx.base)
        self.assertTrue(changed)
        for d, _, _ in os.walk(self.root):
            os.utime(d, (1700000000, 1700000000))
        idx.refresh()
        _, _, changed = core.scan([self.root], self.config.excluder(), {}, idx.base)
        self.assertFalse(changed)

    def test_change_in_the_same_tick_is_not_missed(self):
        pics = os.path.join(self.root, 'pics')
        idx = self.index()
        st = os.stat(pics)
        touch(os.path.join(pics, 'same-tick.png'))
        os.utime(pics, ns=(st.st_atime_ns, st.st_mtime_ns))     # as if the folder time had not moved
        idx.refresh()
        self.assertEqual(self.names(idx.search('same-tick')), ['same-tick.png'])

    def test_undecodable_name(self):
        raw = os.path.join(os.fsencode(self.root), b'bad-\xff.txt')
        with open(raw, 'wb'):
            pass
        idx = self.index()
        r = idx.search('bad-')
        self.assertEqual(len(r), 1)
        self.assertTrue(os.path.exists(r.path(0)))
        self.assertEqual(core.display(r.row(0)[0]), 'bad-�.txt')
        idx2 = self.index(refresh=False)
        self.assertTrue(idx2.load())
        self.assertEqual(idx2.search('bad-').path(0), r.path(0))


class QueryTest(TempTree):
    def setUp(self):
        super().setUp()
        self.idx = self.index()

    def q(self, query, sort='path', desc=False, regex=False):
        return self.rel(self.idx.search(query, sort, desc, regex))

    def test_words_all_match_any_case(self):
        self.assertEqual(self.q('REPORT pdf'), ['docs/Report 2024.pdf', 'docs/old/report-2019.pdf'])

    def test_or_and_not(self):
        self.assertEqual(self.q('report !pdf'), ['docs/report-draft.docx'])
        self.assertEqual(self.q('notes|img'), ['docs/notes.txt', 'pics/IMG_0001.jpg'])
        self.assertEqual(self.q('report !draft|2019'), ['docs/Report 2024.pdf'])

    def test_wildcards_match_whole_name(self):
        self.assertEqual(self.q('*.pdf'), ['docs/Report 2024.pdf', 'docs/old/report-2019.pdf'])
        self.assertEqual(self.q('?.txt'), ['A.txt', 'b.txt'])
        self.assertEqual(self.q('report*'), ['docs/Report 2024.pdf', 'docs/report-draft.docx',
                                             'docs/old/report-2019.pdf'])

    def test_ext(self):
        self.assertEqual(self.q('ext:pdf;DOCX'), ['docs/Report 2024.pdf', 'docs/report-draft.docx',
                                                  'docs/old/report-2019.pdf'])
        self.assertEqual(self.q('ext:pptx'), ['pics/项目报告.pptx'])

    def test_path(self):
        self.assertEqual(self.q('path:old'), ['docs/old', 'docs/old/report-2019.pdf'])
        self.assertEqual(self.q('docs/old'), ['docs/old', 'docs/old/report-2019.pdf'])
        self.assertEqual(self.q('path:pics/*.jpg'), ['pics/IMG_0001.jpg'])
        self.assertEqual(self.q('path:old !path:2019'), ['docs/old'])

    def test_quotes_keep_spaces(self):
        self.assertEqual(self.q('"report 2024"'), ['docs/Report 2024.pdf'])

    def test_regex(self):
        self.assertEqual(self.q(r'^img_\d+', regex=True), ['pics/IMG_0001.jpg'])
        self.assertEqual(self.q(r'regex:^r.*\d{4}\.pdf$'), ['docs/Report 2024.pdf', 'docs/old/report-2019.pdf'])
        self.assertEqual(self.q(r'regex:a|b'), self.q('a|b'))
        with self.assertRaises(core.QueryError):
            self.idx.search('regex:(', 'path')
        with self.assertRaises(core.QueryError):
            self.idx.search('(', 'path', regex=True)

    def test_chinese(self):
        self.assertEqual(self.q('报告'), ['pics/项目报告.pptx'])

    def test_empty_query_lists_everything(self):
        self.assertEqual(len(self.q('')), 11)

    def test_sorts(self):
        self.assertEqual(self.rel(self.idx.search('report', 'mtime', True)),
                         ['docs/Report 2024.pdf', 'docs/report-draft.docx', 'docs/old/report-2019.pdf'])
        self.assertEqual(self.rel(self.idx.search('report', 'mtime', False))[0], 'docs/old/report-2019.pdf')
        self.assertEqual(self.rel(self.idx.search('report', 'size', True))[0], 'docs/Report 2024.pdf')
        self.assertEqual(self.rel(self.idx.search('ext:txt', 'name', False)), ['A.txt', 'b.txt', 'docs/notes.txt'])
        self.assertEqual(self.rel(self.idx.search('ext:txt', 'name', True)), ['docs/notes.txt', 'b.txt', 'A.txt'])
        self.assertEqual(self.rel(self.idx.search('ext:txt', 'path', True)), ['docs/notes.txt', 'b.txt', 'A.txt'])

    def test_unknown_sort_falls_back(self):
        self.assertEqual(len(self.idx.search('report', 'bogus')), 3)


class OverlayTest(TempTree):
    def test_new_changed_and_removed_files(self):
        idx = self.index()
        docs = os.path.join(self.root, 'docs')
        touch(os.path.join(docs, 'report-new.pdf'), b'x' * 7, 1700000350)
        os.remove(os.path.join(docs, 'notes.txt'))
        idx.apply_changes({docs})
        self.assertEqual(self.rel(idx.search('report', 'mtime', True)), [
            'docs/report-new.pdf', 'docs/Report 2024.pdf', 'docs/report-draft.docx', 'docs/old/report-2019.pdf'])
        self.assertEqual(self.rel(idx.search('notes')), [])
        self.assertEqual(self.rel(idx.search('', 'path', False)), [
            'A.txt', 'b.txt', 'docs', 'pics', 'docs/old', 'docs/Report 2024.pdf', 'docs/report-draft.docx',
            'docs/report-new.pdf', 'docs/old/report-2019.pdf', 'pics/IMG_0001.jpg', 'pics/项目报告.pptx'])
        self.assertEqual(idx.count(), 11)

    def test_new_folder_tree_and_removed_folder(self):
        idx = self.index()
        touch(os.path.join(self.root, 'proj', 'sub', 'plan.md'), b'', 1700000000)
        idx.apply_changes({self.root})
        self.assertEqual(self.rel(idx.search('plan')), ['proj/sub/plan.md'])
        shutil.rmtree(os.path.join(self.root, 'docs'))
        idx.apply_changes({self.root})
        self.assertEqual(self.rel(idx.search('report')), [])
        self.assertNotIn(os.path.join(self.root, 'docs', 'old'), idx.known_dirs())

    def test_renamed_folder(self):
        idx = self.index()
        os.rename(os.path.join(self.root, 'docs'), os.path.join(self.root, 'papers'))
        idx.apply_changes({self.root})
        self.assertEqual(self.rel(idx.search('2019')), ['papers/old/report-2019.pdf'])

    def test_changes_outside_roots_ignored(self):
        idx = self.index()
        other = os.path.join(self.tmp, 'other')
        touch(os.path.join(other, 'report.txt'))
        idx.apply_changes({other})
        self.assertEqual(self.rel(idx.search('report.txt')), [])

    def test_refresh_folds_overlay_into_base(self):
        idx = self.index()
        touch(os.path.join(self.root, 'pics', 'x.png'))
        idx.apply_changes({os.path.join(self.root, 'pics')})
        self.assertTrue(idx.extra)
        idx.refresh()
        self.assertFalse(idx.extra)
        self.assertEqual(self.names(idx.search('x.png')), ['x.png'])


class WatcherTest(TempTree):
    def test_inotify_updates_index(self):
        idx = self.index()
        changed = threading.Event()
        idx.on_change = changed.set
        if not idx.start_watching():
            self.skipTest('inotify unavailable')
        try:
            deadline = time.time() + 5
            while idx.watcher.watched() < 4 and time.time() < deadline:
                time.sleep(0.05)
            changed.clear()
            touch(os.path.join(self.root, 'docs', 'old', 'live.txt'))
            deadline = time.time() + 5
            while not idx.search('live.txt').refs and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(self.rel(idx.search('live.txt')), ['docs/old/live.txt'])
            os.makedirs(os.path.join(self.root, 'fresh'))
            deadline = time.time() + 5
            while os.path.join(self.root, 'fresh') not in idx.watcher.path_wd and time.time() < deadline:
                time.sleep(0.05)
            touch(os.path.join(self.root, 'fresh', 'inner.txt'))
            deadline = time.time() + 5
            while not idx.search('inner.txt').refs and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(self.rel(idx.search('inner.txt')), ['fresh/inner.txt'])
        finally:
            idx.close()

    def test_watch_limit_sets_limited(self):
        w = core.Watcher(lambda d, o: None)
        try:
            real = w.libc.inotify_add_watch

            class Fake:
                def __call__(self, fd, path, mask):
                    import ctypes
                    ctypes.set_errno(28)  # ENOSPC
                    return -1
            w.libc = type('L', (), {'inotify_add_watch': Fake(), 'inotify_rm_watch': w.libc.inotify_rm_watch})()
            w.sync([self.root])
            self.assertTrue(w.limited)
            self.assertIsNotNone(real)
        finally:
            w.close()


class MiscTest(unittest.TestCase):
    def test_language(self):
        self.assertEqual(core.ui_language({'LANG': 'zh_CN.UTF-8'}), 'zh')
        self.assertEqual(core.ui_language({'LANG': 'en_US.UTF-8'}), 'en')
        self.assertEqual(core.ui_language({'LC_ALL': 'C', 'LANG': 'zh_CN.UTF-8'}), 'en')
        self.assertEqual(core.ui_language({}), 'en')

    def test_strings_have_same_keys(self):
        self.assertEqual(set(core.STRINGS['zh']), set(core.STRINGS['en']))

    def test_human_size(self):
        self.assertEqual(core.human_size(-1), '')
        self.assertEqual(core.human_size(10), '10 B')
        self.assertEqual(core.human_size(1536), '1.5 KB')

    def test_config_defaults_and_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'config.json')
            with open(p, 'w') as f:
                f.write('{bad')
            c = core.Config(p)
            self.assertEqual(c.roots, core.DEFAULT_ROOTS)
            c.hidden = True
            c.save()
            self.assertTrue(core.Config(p).hidden)

    def test_empty_index(self):
        idx = core.Index(core.Config('/nonexistent/config.json', {'roots': []}), '/nonexistent/x.bin', mounts={})
        self.assertEqual(len(idx.search('x')), 0)
        self.assertEqual(len(idx.search('')), 0)

    def test_search_base_orders(self):
        b = core.build_base([('/r', 0, [('a', 1, 3), ('ab', 3, 2), ('b', 2, 1)])])
        names = lambda arr: [b.name(i) for i in arr]  # noqa: E731
        self.assertEqual(names(core.search_base(b, core.parse_query('a'), 'mtime', True)), ['a', 'ab'])
        self.assertEqual(names(core.search_base(b, core.parse_query('a'), 'mtime', False)), ['ab', 'a'])
        self.assertEqual(names(core.search_base(b, core.parse_query('a'), 'size', True)), ['ab', 'a'])
        self.assertEqual(names(core.search_base(b, [], 'path', False)), ['a', 'ab', 'b'])
        self.assertEqual(names(core.search_base(b, [], 'size', False)), ['a', 'b', 'ab'])
        tomb = bytearray(b.n)
        tomb[b.orders['name'][1]] = 1
        self.assertEqual(names(core.search_base(b, [], 'name', False, tomb)), ['a', 'b'])
        self.assertIsInstance(core.search_base(b, [], 'path', True), array.array)

    def test_large_and_small_result_orders_agree(self):
        recs = [('/r', 0, [('n%03d' % i, (i * 37) % 101, (i * 53) % 97) for i in range(300)])]
        b = core.build_base(recs)
        for q in ('n0', 'n', 'n1|n2', 'n00'):
            mask = core.match_mask(b, core.parse_query(q))
            pos = list(itertools.compress(range(b.n), mask))
            for sort in ('name', 'size', 'path'):
                want = sorted(pos, key=lambda i: (b.sort_key(i, sort), b.ranks[sort][i]))
                self.assertEqual(list(core.order_mask(b, mask, sort, False)), want, (q, sort))
                self.assertEqual(list(core.order_mask(b, mask, sort, True)), want[::-1], (q, sort))
            self.assertEqual(list(core.order_mask(b, mask, 'mtime', True)), pos)
            self.assertEqual(list(core.order_mask(b, mask, 'mtime', False)), pos[::-1])

    def test_required_literal(self):
        self.assertEqual(core.required_literal(r'^img_\d+'), 'mg_')
        self.assertEqual(core.required_literal(r'report.*draft'), 'report')
        self.assertEqual(core.required_literal(r'a|b'), '')
        self.assertEqual(core.required_literal(r'(abc)?d'), '')
        r = core.parse_query(r'regex:^\u0131mg_\d', False)
        self.assertTrue(r)

    def test_narrowing(self):
        n = core.narrows
        t = core.split_tokens
        self.assertTrue(n(t('rep'), t('repo')))
        self.assertTrue(n(t('rep'), t('rep pdf')))
        self.assertTrue(n(t('a !b'), t('a !b c')))
        self.assertFalse(n(t('rep'), t('rep/x')))
        self.assertFalse(n(t('ext:pd'), t('ext:pdf')))
        self.assertFalse(n(t('*.p'), t('*.pd')))
        self.assertFalse(n(t('!a'), t('!ab')))
        self.assertFalse(n(t('a|b'), t('a|bc')))
        self.assertFalse(n(t('rep'), t('re')))
        self.assertTrue(n(t('path:do'), t('path:doc')))

    def test_narrowed_search_equals_fresh_search(self):
        recs = [('/r', 0, sorted([('report%d.pdf' % i, i, i) for i in range(50)] + [('rx%d' % i, i, i) for i in range(50)],
                                 key=lambda e: e[0]))]
        idx = core.Index(core.Config('/nonexistent/c.json', {'roots': []}), '/nonexistent/x.bin', mounts={})
        idx.base = core.build_base(recs)
        idx._reset_overlay()
        for q in ('r', 're', 'rep', 'repo', 'repo 1', 'repo 1 pdf'):
            got = [idx.search(q).path(k) for k in range(len(idx.search(q)))]
            idx.last = None
            fresh = idx.search(q)
            self.assertEqual(got, [fresh.path(k) for k in range(len(fresh))], q)

if __name__ == '__main__':
    unittest.main()

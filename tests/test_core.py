"""Tests of find_fast_core: scanning, cache, query language, search order, overlay and inotify."""
import array
import itertools
import os
import re
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
        r = idx.search('pics', path_words=False)
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

    def q(self, query, sort='path', desc=False, regex=False, path_words=None):
        return self.rel(self.idx.search(query, sort, desc, regex, path_words))

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
        self.assertEqual(self.q(r'regex:a|b'), self.q('a|b', path_words=False))
        with self.assertRaises(core.QueryError):
            self.idx.search('regex:(', 'path')
        with self.assertRaises(core.QueryError):
            self.idx.search('(', 'path', regex=True)

    def test_regex_errors_in_plain_words(self):
        def why(pattern, lang):
            try:
                re.compile(pattern)
            except re.error as e:
                return core.regex_error_text(e, lang)
        self.assertEqual(why('(', 'zh'), '正则表达式有误：括号不成对，缺少「)」（第 1 个字符）')
        self.assertEqual(why('a)', 'zh'), '正则表达式有误：多了一个「)」（第 2 个字符）')
        self.assertEqual(why('[a', 'zh'), '正则表达式有误：方括号不成对，缺少「]」（第 1 个字符）')
        self.assertEqual(why('*a', 'zh'), '正则表达式有误：「*」「+」「?」「{}」前面缺少要重复的内容（第 1 个字符）')
        self.assertEqual(why('a**', 'zh'), '正则表达式有误：「*」「+」「?」「{}」不能连用（第 3 个字符）')
        self.assertEqual(why(r'\q', 'zh'), '正则表达式有误：无效的转义「\\q」（第 1 个字符）')
        self.assertEqual(why('(', 'en'), 'Invalid regular expression: a "(" has no matching ")" (character 1)')
        self.assertTrue(why('(?P<x', 'zh').startswith('正则表达式有误：missing >'))    # others as Python says

    def test_chinese(self):
        self.assertEqual(self.q('报告'), ['pics/项目报告.pptx'])

    def test_count_under(self):
        docs = os.path.join(self.root, 'docs')
        self.assertEqual(self.idx.count_under(docs), 6)       # docs, its 3 files, old and the file in it
        self.assertEqual(self.idx.count_under(os.path.join(docs, 'old')), 2)
        self.assertEqual(self.idx.count_under(os.path.join(self.root, 'nowhere')), 0)
        touch(os.path.join(docs, 'old', 'new.txt'), b'', 1700009000)
        self.idx.refresh()
        self.assertEqual(self.idx.count_under(os.path.join(docs, 'old')), 3)

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

    def test_words_match_folder_names(self):
        self.assertEqual(self.q('pics'), ['pics', 'pics/IMG_0001.jpg', 'pics/项目报告.pptx'])
        self.assertEqual(self.q('old 2019'), ['docs/old/report-2019.pdf'])
        self.assertEqual(self.q('docs report !old'), ['docs/Report 2024.pdf', 'docs/report-draft.docx'])
        self.assertEqual(self.q('pics 报告'), ['pics/项目报告.pptx'])
        self.assertEqual(sorted(self.q('PICS|old')), ['docs/old', 'docs/old/report-2019.pdf', 'pics',
                                                       'pics/IMG_0001.jpg', 'pics/项目报告.pptx'])
        self.assertEqual(self.q('old|*.jpg'), ['docs/old', 'docs/old/report-2019.pdf', 'pics/IMG_0001.jpg'])

    def test_words_exclude_by_path(self):
        self.assertEqual(self.q('report !docs'), [])
        self.assertEqual(self.q('ext:pdf !old'), ['docs/Report 2024.pdf'])

    def test_other_terms_stay_name_only(self):
        self.assertEqual(self.q('*pics*'), ['pics'])
        self.assertEqual(self.q('pics*'), ['pics'])
        self.assertEqual(self.q('regex:^pics'), ['pics'])
        self.assertEqual(self.q('^pics', regex=True), ['pics'])
        self.assertEqual(self.q('ext:jpg'), ['pics/IMG_0001.jpg'])

    def test_path_words_off(self):
        self.assertEqual(self.q('pics', path_words=False), ['pics'])
        self.assertEqual(self.q('old 2019', path_words=False), [])
        self.config.other['match_path'] = False
        self.assertEqual(self.q('old 2019'), [])
        self.config.other['match_path'] = 'bad'
        self.assertEqual(self.q('old 2019'), ['docs/old/report-2019.pdf'])

    def test_narrowing_keeps_the_mode(self):
        self.assertEqual(self.q('pics', path_words=False), ['pics'])
        self.assertEqual(self.q('pics'), ['pics', 'pics/IMG_0001.jpg', 'pics/项目报告.pptx'])

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

    def test_overlay_words_match_folders_like_base(self):
        idx = self.index()
        touch(os.path.join(self.root, 'proj', 'sub', 'plan.md'), b'', 1700000000)
        os.rename(os.path.join(self.root, 'docs'), os.path.join(self.root, 'papers'))
        idx.apply_changes({self.root})
        self.assertTrue(idx.extra)
        got = {q: self.rel(idx.search(q, 'path', False)) for q in ('proj', 'papers 2019', 'sub md', '!papers report')}
        self.assertEqual(got['proj'], ['proj', 'proj/sub', 'proj/sub/plan.md'])
        self.assertEqual(got['papers 2019'], ['papers/old/report-2019.pdf'])
        self.assertEqual(got['sub md'], ['proj/sub/plan.md'])
        self.assertEqual(got['!papers report'], [])
        idx.refresh()
        self.assertFalse(idx.extra)
        for q, want in got.items():
            self.assertEqual(sorted(self.rel(idx.search(q, 'path', False))), sorted(want), q)

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


class SettingsTest(TempTree):
    def scope(self, roots=None, exclude=None, hidden=False):
        return self.config.with_scope([self.root] if roots is None else roots,
                                      core.DEFAULT_EXCLUDE if exclude is None else exclude, hidden)

    def all_paths(self, idx):
        return sorted(self.rel(idx.search('', 'path', desc=False)))

    def fresh(self, config):
        idx = core.Index(config, os.path.join(self.tmp, 'fresh.bin'), mounts={})
        idx.refresh()
        return idx

    def test_tidy_merges_duplicates_and_uses_tilde(self):
        home = core.HOME
        elsewhere = os.path.join(self.tmp, 'a')
        roots, exclude = core.tidy_scope(
            [home, '~', home + '/x/', ' ', elsewhere, os.path.join(elsewhere, '..', 'a')],
            ['node_modules', ' node_modules ', '~/x/y', home + '/x/y', '*.tmp', ''])
        self.assertEqual(roots, ['~', '~/x', elsewhere])
        self.assertEqual(exclude, ['node_modules', '~/x/y', '*.tmp'])
        # a sibling whose name starts like the home folder is not under it
        fake_home = os.path.join(self.tmp, 'h')
        self.assertEqual(core.to_tilde(fake_home + '2', home=fake_home), fake_home + '2')
        self.assertEqual(core.to_tilde(fake_home + '/d', home=fake_home), '~/d')

    def test_check_scope(self):
        docs = os.path.join(self.root, 'docs')
        self.assertEqual(core.check_scope([], []), [('roots', '', 'no_roots')])
        missing = os.path.join(self.tmp, 'gone')
        got = core.check_scope([self.root, docs, missing],
                               ['node_modules', os.path.join(self.tmp, 'elsewhere'), os.path.join(docs, 'old'), '/'],
                               mounts={})
        self.assertIn(('roots', docs, 'nested'), got)
        self.assertIn(('roots', missing, 'missing'), got)
        self.assertIn(('exclude', os.path.join(self.tmp, 'elsewhere'), 'missing'), got)
        self.assertIn(('exclude', '/', 'outside'), got)
        self.assertNotIn(('exclude', os.path.join(docs, 'old'), 'outside'), got)
        self.assertFalse(any(item == 'node_modules' for _, item, _ in got))
        net = core.check_scope([docs], [], mounts={self.root: 'nfs4'})
        self.assertEqual(net, [('roots', docs, 'network')])
        self.assertEqual(core.check_scope([docs], [], mounts={self.root: 'ext4'}), [])
        for code in ('no_roots', 'missing', 'network', 'nested', 'outside'):
            for lang in ('zh', 'en'):
                self.assertTrue(core.scope_problem_text('x', code, lang))

    def test_config_keeps_other_keys(self):
        path = os.path.join(self.tmp, 'c.json')
        c = core.Config(path, {'roots': ['~'], 'keys': {'locate': '<Primary>Return'}})
        c2 = c.with_scope([self.root], [], True)
        c2.save()
        c3 = core.Config(path)
        self.assertEqual(c3.roots, [self.root])
        self.assertTrue(c3.hidden)
        self.assertEqual(c3.other, {'keys': {'locate': '<Primary>Return'}})

    def test_added_exclusions_pruned_like_a_fresh_scan(self):
        idx = self.index()
        touch(os.path.join(self.root, 'docs', 'new.tmp'), b'', 1700000900)
        idx.apply_changes([os.path.join(self.root, 'docs')])
        new = self.scope(exclude=core.DEFAULT_EXCLUDE + [os.path.join(self.root, 'docs', 'old'), 'IMG_*'])
        self.assertEqual(idx.reconfigure(new), 'pruned')
        got = self.all_paths(idx)
        self.assertEqual(got, self.all_paths(self.fresh(new)))
        self.assertNotIn('docs/old', got)
        self.assertNotIn('docs/old/report-2019.pdf', got)
        self.assertNotIn('pics/IMG_0001.jpg', got)
        self.assertIn('docs/new.tmp', got)
        # the cache now belongs to the new settings
        again = core.Index(new, self.cache, mounts={})
        self.assertTrue(again.load())
        self.assertEqual(self.all_paths(again), got)

    def test_folder_name_exclusion_pruned(self):
        idx = self.index()
        new = self.scope(exclude=core.DEFAULT_EXCLUDE + ['docs'])
        self.assertEqual(idx.reconfigure(new), 'pruned')
        self.assertEqual(self.all_paths(idx), self.all_paths(self.fresh(new)))
        self.assertFalse(any(p.startswith('docs') for p in self.all_paths(idx)))

    def test_other_changes_rescan(self):
        idx = self.index()
        self.assertEqual(idx.reconfigure(self.scope()), 'same')
        new = self.scope(hidden=True)
        self.assertEqual(idx.reconfigure(new), 'rescanned')
        self.assertIn('.hidden/secret-report.txt', self.all_paths(idx))
        new = self.scope(exclude=[], hidden=True)
        self.assertEqual(idx.reconfigure(new), 'rescanned')
        self.assertIn('node_modules/pkg/report.js', self.all_paths(idx))
        other = os.path.join(self.tmp, 'other')
        touch(os.path.join(other, 'extra-file.txt'))
        new = self.scope(roots=[self.root, other], exclude=[], hidden=True)
        self.assertEqual(idx.reconfigure(new), 'rescanned')
        found = [p for p in self.rel(idx.search('extra-file'))]
        self.assertEqual(found, [os.path.join('..', 'other', 'extra-file.txt')])
        self.assertEqual(self.all_paths(idx), self.all_paths(self.fresh(new)))

    def test_reused_folders_follow_new_exclusions(self):
        idx = self.index()
        new = self.scope(roots=[self.root, os.path.join(self.tmp, 'nothing-here')],
                         exclude=core.DEFAULT_EXCLUDE + ['pics'])
        idx.config = new
        idx.refresh()
        self.assertFalse(any(p.startswith('pics') for p in self.all_paths(idx)))

    def test_waits_for_a_scan_already_running(self):
        idx = self.index()
        idx.state = 'scanning'          # as if another rescan were running
        out = []
        t = threading.Thread(target=lambda: out.append(idx.reconfigure(self.scope(hidden=True))))
        t.start()
        time.sleep(0.3)
        self.assertEqual(out, [])
        idx.state = 'ready'
        t.join(10)
        self.assertEqual(out, ['rescanned'])
        self.assertIn('.hidden/secret-report.txt', self.all_paths(idx))

    def test_stopped_rescan(self):
        idx = self.index()
        stop = threading.Event()
        stop.set()
        self.assertEqual(idx.reconfigure(self.scope(hidden=True), stop=stop), 'stopped')
        self.assertEqual(idx.state, 'ready')


class VersionTest(TempTree):
    SAME = ['示例方案.docx', '示例方案(1).docx', '示例方案（2）.docx', '【20260101】示例方案.docx',
            '2026-01-01_示例方案.docx', '示例方案_20260101.docx', '示例方案_v2.docx', '示例方案 V2.1.docx',
            '示例方案第二版.docx', '示例方案-终稿.docx', '（初稿）示例方案.docx', '示例方案 final.docx',
            '1 示例方案.docx', '02_示例方案.docx', '示例方案 - 副本.docx', '示例方案_copy.docx',
            'Copy of 示例方案.docx', '［示例方案］.docx', '示例 方案.docx', '2026-01-01_示例方案_V2.1(1).docx']

    def test_marks_group_together(self):
        keys = {core.version_key(n) for n in self.SAME}
        self.assertEqual(len(keys), 1, keys)
        self.assertIsNotNone(keys.pop())

    def test_not_grouped(self):
        k = core.version_key('示例方案.docx')
        self.assertNotEqual(core.version_key('示例方案.pdf'), k)            # another extension
        self.assertNotEqual(core.version_key('示例计划.docx'), k)            # another stem
        self.assertNotEqual(core.version_key('Report 2024.pdf'), core.version_key('Report 2025.pdf'))
        self.assertIsNone(core.version_key('1.docx'))                       # too short once marks go
        self.assertIsNone(core.version_key('v2.docx'))
        self.assertIsNone(core.version_key('a(1).txt'))
        self.assertEqual(core.version_key('Plan.DOCX'), core.version_key('plan_v3.docx'))

    def make_versions(self):
        d = os.path.join(self.root, 'v')
        touch(os.path.join(d, '示例方案.docx'), b'', 1700001000)
        touch(os.path.join(d, 'a', '示例方案_v2.docx'), b'', 1700003000)           # newest
        touch(os.path.join(d, 'b', '示例方案-终稿.docx'), b'', 1700002000)
        touch(os.path.join(d, '示例方案(1)', 'x.txt'), b'', 1700004000)              # a folder: not grouped
        touch(os.path.join(d, 'c', '示例方案.pdf'), b'', 1700005000)                 # other extension
        touch(os.path.join(d, 'tie', 'ab', '同时.txt'), b'', 1700006000)
        touch(os.path.join(d, 'tie', '同时(1).txt'), b'', 1700006000)               # same time, shorter path wins
        return self.index()

    def test_groups_in_a_result(self):
        idx = self.make_versions()
        for sort, desc in (('mtime', True), ('name', False), ('path', False)):
            res = idx.search('示例方案', sort, desc)
            g = core.VersionGroups(res)
            marks = {os.path.relpath(res.path(k), self.root): g.mark(k) for k in range(len(res))}
            self.assertEqual(marks['v/a/示例方案_v2.docx'], 'newest')
            self.assertEqual(marks['v/示例方案.docx'], 'older')
            self.assertEqual(marks['v/b/示例方案-终稿.docx'], 'older')
            self.assertIsNone(marks['v/示例方案(1)'])
            self.assertIsNone(marks['v/c/示例方案.pdf'])
            k = [k for k in range(len(res)) if res.path(k).endswith('示例方案.docx')][0]
            self.assertEqual(res.path(g.newest(k)), os.path.join(self.root, 'v', 'a', '示例方案_v2.docx'))
            self.assertEqual(g.size(k), 3)
        res = idx.search('同时')
        g = core.VersionGroups(res)
        self.assertEqual(res.path(g.newest(0)), os.path.join(self.root, 'v', 'tie', '同时(1).txt'))

    def test_same_time_later_draft_is_newest(self):
        d = os.path.join(self.root, 'w')
        touch(os.path.join(d, '计划.docx'), b'', 1700007000)
        touch(os.path.join(d, 'x', '计划-初稿.docx'), b'', 1700007000)
        touch(os.path.join(d, 'x', 'y', '计划终稿.docx'), b'', 1700007000)
        res = self.index().search('计划')
        g = core.VersionGroups(res)
        self.assertEqual(res.path(g.newest(0)), os.path.join(d, 'x', 'y', '计划终稿.docx'))
        self.assertEqual([core.draft_rank(n) for n in ('a终稿.doc', 'a 修订版.doc', 'a二稿.doc', 'a_Draft.doc', 'a.doc')],
                         [5, 4, 2, 1, 0])

    def test_limit_and_stop(self):
        idx = self.make_versions()
        res = idx.search('示例方案')
        self.assertTrue(core.VersionGroups(res, limit=2).skipped)
        g = core.VersionGroups(res, stop=lambda: True)
        self.assertTrue(g.skipped)
        self.assertIsNone(g.mark(0))

    def test_grouping_100k_rows_is_quick(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
        import bench
        idx = core.Index(self.config, self.cache, mounts={})
        idx.base = core.build_base(bench.synthetic_records(core.VERSION_GROUP_LIMIT - 1000))
        idx._reset_overlay()
        res = idx.search('')
        self.assertLessEqual(len(res), core.VERSION_GROUP_LIMIT)
        t = time.perf_counter()
        g = core.VersionGroups(res)
        took = time.perf_counter() - t
        sys.stderr.write('\ngrouping %d rows: %.2f s\n' % (len(res), took))
        self.assertFalse(g.skipped)
        self.assertLess(took, 5.0)


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

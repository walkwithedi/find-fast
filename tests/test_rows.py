"""Tests of how result rows are shown: short times, short folders, types, filters and folder
suggestions (find_fast_core)."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import find_fast_core as core  # noqa: E402

NOW = time.mktime((2026, 11, 17, 12, 0, 0, 0, 0, -1))
D = 86400


def ts(year, month, day, hour=0, minute=0):
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


def short(when, lang='zh'):
    return core.human_time_short(when, now=NOW, lang=lang)


class ShortTimeTest(unittest.TestCase):
    def test_relative(self):
        for delta, zh, en in [
                (0, '刚刚', 'just now'), (30, '刚刚', 'just now'), (59, '刚刚', 'just now'),
                (60, '1 分钟前', '1 min ago'), (300, '5 分钟前', '5 min ago'), (3599, '59 分钟前', '59 min ago'),
                (3600, '1 小时前', '1 h ago'), (3 * 3600, '3 小时前', '3 h ago'), (86399, '23 小时前', '23 h ago'),
                (D, '1 天前', '1 day ago'), (6 * D, '6 天前', '6 days ago')]:
            with self.subTest(delta=delta):
                self.assertEqual(short(NOW - delta, 'zh'), zh)
                self.assertEqual(short(NOW - delta, 'en'), en)

    def test_absolute_this_year(self):
        self.assertEqual(short(ts(2026, 10, 8, 9, 30)), '10-08')
        self.assertEqual(short(ts(2026, 1, 2, 0, 0)), '01-02')

    def test_absolute_other_year(self):
        self.assertEqual(short(ts(2025, 12, 31, 23, 0)), '2025-12-31')

    def test_future_clock_skew(self):
        self.assertEqual(short(NOW + 10), '刚刚')
        self.assertEqual(short(NOW + 3 * D), '2026-11-20')

    def test_seven_days_is_absolute(self):
        self.assertEqual(short(NOW - 7 * D), '11-10')


class ShortDirTest(unittest.TestCase):
    def test_examples(self):
        home = '/u/zs'
        self.assertEqual(core.short_dir(home + '/文档/项目甲', home=home), '~/文档/项目甲')
        self.assertEqual(core.short_dir(home + '/文档/项目甲/2026', home=home), '…/项目甲/2026')
        self.assertEqual(core.short_dir('/a/b/c/d', home=home), '…/c/d')
        self.assertEqual(core.short_dir('/v/u/U盘备份', home=home), '…/u/U盘备份')
        self.assertEqual(core.short_dir('/v/a', home=home), '/v/a')
        self.assertEqual(core.short_dir('/', home=home), '/')
        self.assertEqual(core.short_dir(home, home=home), '~')
        self.assertEqual(core.short_dir('/u/zs2', home=home), '/u/zs2')


class CategoryTest(unittest.TestCase):
    def test_categories(self):
        self.assertEqual(core.category('a.PDF'), 'doc')
        self.assertEqual(core.category('a.pdf', True), 'folder')
        self.assertEqual(core.category('README'), 'other')
        self.assertEqual(core.category('.bashrc'), 'other')
        self.assertEqual(core.category('x.tar.gz'), 'archive')
        self.assertEqual(core.category('v.mp4'), 'video')
        self.assertEqual(core.category_group('video'), 'audio')
        self.assertEqual(core.category_group('doc'), 'doc')


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def row(self, k):
        return self.rows[k]


HOME = core.HOME.rstrip('/')
ROWS = [('a.jpg', HOME + '/图片/截图', 10, 0), ('b.png', HOME + '/图片', 10, 0), ('c.pdf', HOME + '/文档', 10, 0),
        ('项目', HOME + '/文档', -1, 0), ('d.mp4', '/v/u/盘/影片', 10, 0), ('e', HOME + '/图片/截图', 1, 0)]


class ViewTest(unittest.TestCase):
    def test_facets_cover_every_row(self):
        f = core.facets_of(FakeResult(ROWS))
        self.assertEqual(set(f), set(core.FILTER_KEYS))
        self.assertEqual(f, {'all': 6, 'folder': 1, 'doc': 1, 'image': 2, 'archive': 0, 'code': 0, 'audio': 1,
                             'other': 1})
        self.assertEqual(sum(v for k, v in f.items() if k != 'all'), f['all'])

    def test_view_by_type_keeps_order(self):
        res = FakeResult(ROWS)
        self.assertIsNone(core.build_view(res))
        self.assertIsNone(core.build_view(res, 'nonsense'))
        self.assertEqual(core.build_view(res, 'image'), [0, 1])
        self.assertEqual(core.build_view(res, 'audio'), [4])

    def test_view_by_scope_includes_the_folder_itself(self):
        res = FakeResult(ROWS)
        self.assertEqual(core.build_view(res, 'all', HOME + '/图片'), [0, 1, 5])
        self.assertEqual(core.build_view(res, 'all', HOME + '/文档/项目'), [3])
        self.assertEqual(core.build_view(res, 'image', HOME + '/图片/'), [0, 1])
        self.assertEqual(core.build_view(res, 'all', HOME + '/图'), [])

    def test_scope_suggestions(self):
        got = core.scope_suggest_of(FakeResult(ROWS))
        self.assertEqual(got, [(HOME + '/图片', 3), (HOME + '/文档', 2)])

    def test_scope_suggestions_go_deeper_when_one_folder_holds_all(self):
        rows = [('a', HOME + '/图片/甲', 1, 0)] * 3 + [('b', HOME + '/图片/乙', 1, 0)]
        self.assertEqual(core.scope_suggest_of(FakeResult(rows)), [(HOME + '/图片/甲', 3), (HOME + '/图片/乙', 1)])
        self.assertEqual(core.scope_suggest_of(FakeResult([('a', '/x', 1, 0)])), [])

    def test_stop(self):
        self.assertIsNone(core.facets_of(FakeResult(ROWS), stop=lambda: True))
        self.assertIsNone(core.scope_suggest_of(FakeResult(ROWS), stop=lambda: True))


class StringsTest(unittest.TestCase):
    def test_sort_labels_match_choices(self):
        for lang in ('zh', 'en'):
            self.assertEqual(len(core.sort_labels(lang)), len(core.SORT_CHOICES))


if __name__ == '__main__':
    unittest.main()

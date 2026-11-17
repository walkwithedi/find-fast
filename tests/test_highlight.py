"""Tests of core.highlight and core.highlight_row: which parts of a name or folder are marked."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import find_fast_core as core  # noqa: E402


def hl(text, query, mode='html', **kw):
    return core.highlight(text, core.parse_query(query), mode, **kw)


class HighlightTest(unittest.TestCase):
    def test_plain_chinese(self):
        self.assertEqual(hl('报告（第27期）.pdf', '报告'), '<mark>报告</mark>（第27期）.pdf')

    def test_case_insensitive_all_occurrences(self):
        self.assertEqual(hl('Report.PDF', 'pdf'), 'Report.<mark>PDF</mark>')
        self.assertEqual(hl('报告-报告.pdf', '报告'), '<mark>报告</mark>-<mark>报告</mark>.pdf')

    def test_overlapping_terms_merge(self):
        self.assertEqual(hl('报告（第27期）.pdf', '报告 报告（'), '<mark>报告（</mark>第27期）.pdf')

    def test_adjacent_spans_merge(self):
        self.assertEqual(hl('abcd', 'ab cd'), '<mark>abcd</mark>')

    def test_negated_term_not_marked(self):
        out = hl('报告-草稿.pdf', '!pdf 报告')
        self.assertIn('<mark>报告</mark>', out)
        self.assertEqual(out.count('<mark>'), 1)

    def test_alternatives_all_marked(self):
        self.assertEqual(hl('周报与月报', '周报|月报'), '<mark>周报</mark>与<mark>月报</mark>')

    def test_glob_marks_suffix(self):
        self.assertEqual(hl('a.pdf', '*.pdf'), 'a<mark>.pdf</mark>')
        self.assertEqual(hl('report-2026.txt', 'report*'), '<mark>report</mark>-2026.txt')
        self.assertEqual(hl('a-z', 'a*z'), '<mark>a-z</mark>')

    def test_ext_marks_suffix_case_insensitive(self):
        self.assertEqual(hl('a.PDF', 'ext:pdf'), 'a<mark>.PDF</mark>')
        self.assertEqual(hl('a.docx', 'ext:pdf;docx'), 'a<mark>.docx</mark>')

    def test_regex_marks_every_match(self):
        self.assertEqual(hl('IMG_12 IMG_3', 'regex:img_\\d+'), '<mark>IMG_12</mark> <mark>IMG_3</mark>')
        self.assertEqual(core.highlight('ab-ab', core.parse_query('ab', regex=True)),
                         '<mark>ab</mark>-<mark>ab</mark>')

    def test_escaping_before_marking(self):
        self.assertEqual(hl('<a&b>.txt', 'a'), '&lt;<mark>a</mark>&amp;b&gt;.txt')
        self.assertEqual(hl('"q".txt', 'q'), '&quot;<mark>q</mark>&quot;.txt')

    def test_pango_mode(self):
        self.assertEqual(hl('<a&b>.txt', 'a', 'pango'), '&lt;<span background="#ffe9a8">a</span>&amp;b&gt;.txt')

    def test_pango_mode_custom_colours(self):
        out = hl('abc', 'b', 'pango', mark_bg='#3a3320', mark_fg='#ffd98a')
        self.assertEqual(out, 'a<span background="#3a3320" foreground="#ffd98a">b</span>c')

    def test_no_matches_returns_escaped_text(self):
        self.assertEqual(hl('abc', 'zzz'), 'abc')
        self.assertEqual(hl('a<b', ''), 'a&lt;b')
        self.assertEqual(hl('', 'a'), '')

    def test_marks_are_capped(self):
        self.assertEqual(hl('a-' * 30, 'a').count('<mark>'), 24)

    def test_zero_width_regex_does_not_hang(self):
        self.assertEqual(hl('bbb', 'regex:a*'), 'bbb')

    def test_path_term_marks_path(self):
        self.assertEqual(hl('~/项目/甲', 'path:项目'), '~/<mark>项目</mark>/甲')

    def test_size_like_and_wildcard_path_terms_ignored(self):
        self.assertEqual(hl('~/a/b', 'path:a*b'), '~/a/b')

    def test_emoji_names(self):
        self.assertEqual(hl('😀报告.txt', '报告'), '😀<mark>报告</mark>.txt')

    def test_highlight_row_does_not_repeat_name_hits_in_path(self):
        name_html, dir_html = core.highlight_row('报告.pdf', '~/报告', core.parse_query('报告'))
        self.assertIn('<mark>报告</mark>', name_html)
        self.assertNotIn('<mark>', dir_html)

    def test_highlight_row_marks_path_hits(self):
        name_html, dir_html = core.highlight_row('报表.xlsx', '~/项目/预算', core.parse_query('预算'))
        self.assertNotIn('<mark>', name_html)
        self.assertIn('<mark>预算</mark>', dir_html)

    def test_highlight_row_pango(self):
        name, folder = core.highlight_row('a&b', '~/x', core.parse_query('x b'), 'pango', mark_bg='#000000')
        self.assertEqual(name, 'a&amp;<span background="#000000">b</span>')
        self.assertEqual(folder, '~/<span background="#000000">x</span>')


if __name__ == '__main__':
    unittest.main()

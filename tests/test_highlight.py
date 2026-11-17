"""T02 的验收测试：core.highlight / core.highlight_row。

设计意图：先写测试再实现。跑不通是预期的——这些用例把「什么算命中」钉死，
避免实现时各自发挥。
"""

import sys

import pytest

import find_fast_core as core  # noqa: E402  （路径由 conftest.py 注入）


def need(name):
    fn = getattr(core, name, None)
    if fn is None:
        pytest.fail('find_fast_core.%s 尚未实现（见 docs/06 6.1）' % name, pytrace=False)
    return fn


def hl(text, query, mode='html', **kw):
    return need('highlight')(text, core.parse_query(query), mode, **kw)


def test_plain_chinese():
    assert hl('报告（第27期）.pdf', '报告') == '<mark>报告</mark>（第27期）.pdf'


def test_case_insensitive_all_occurrences():
    assert hl('Report.PDF', 'pdf') == 'Report.<mark>PDF</mark>'
    assert hl('报告-报告.pdf', '报告') == '<mark>报告</mark>-<mark>报告</mark>.pdf'


def test_overlapping_terms_merge():
    assert hl('报告（第27期）.pdf', '报告 报告（') == '<mark>报告（</mark>第27期）.pdf'


def test_negated_term_not_marked():
    out = hl('报告-草稿.pdf', '!pdf 报告')
    assert '<mark>报告</mark>' in out
    assert out.count('<mark>') == 1


def test_glob_marks_suffix():
    assert hl('a.pdf', '*.pdf') == 'a<mark>.pdf</mark>'
    assert hl('report-2026.txt', 'report*') == '<mark>report</mark>-2026.txt'


def test_ext_marks_suffix_case_insensitive():
    assert hl('a.PDF', 'ext:pdf') == 'a<mark>.PDF</mark>'


def test_escaping_before_marking():
    assert hl('<a&b>.txt', 'a') == '&lt;<mark>a</mark>&amp;b&gt;.txt'


def test_pango_mode():
    out = hl('<a&b>.txt', 'a', 'pango')
    assert out == '&lt;<span background="#ffe9a8">a</span>&amp;b&gt;.txt'


def test_pango_mode_custom_colours():
    out = hl('abc', 'b', 'pango', mark_bg='#3a3320', mark_fg='#ffd98a')
    assert out == 'a<span background="#3a3320" foreground="#ffd98a">b</span>c'


def test_no_matches_returns_escaped_text():
    assert hl('abc', 'zzz') == 'abc'
    assert hl('a<b', '') == 'a&lt;b'


def test_marks_are_capped():
    out = hl('a-' * 30, 'a')
    assert out.count('<mark>') == 24


def test_zero_width_regex_does_not_hang():
    assert hl('bbb', 'regex:a*') == 'bbb'


def test_path_term_marks_path():
    assert hl('~/项目/甲', 'path:项目') == '~/<mark>项目</mark>/甲'


def test_highlight_row_does_not_repeat_name_hits_in_path():
    name_html, dir_html = need('highlight_row')('报告.pdf', '~/报告', core.parse_query('报告'))
    assert '<mark>报告</mark>' in name_html
    assert '<mark>' not in dir_html


def test_highlight_row_marks_path_hits():
    name_html, dir_html = need('highlight_row')('报表.xlsx', '~/项目/预算', core.parse_query('预算'))
    assert '<mark>' not in name_html
    assert '<mark>预算</mark>' in dir_html

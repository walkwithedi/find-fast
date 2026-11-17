"""T02 的验收测试：core.human_time_short。

列表里的时间是「扫一眼」用的，必须比 YYYY-MM-DD HH:MM 更好认；但超过一周就该给绝对日期，
否则「37 天前」反而难算。
"""

import sys
import time

import pytest

import find_fast_core as core  # noqa: E402  （路径由 conftest.py 注入）

NOW = time.mktime((2026, 11, 17, 12, 0, 0, 0, 0, -1))
D = 86400


def ts(year, month, day, hour=0, minute=0):
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


def short(when, lang='zh'):
    fn = getattr(core, 'human_time_short', None)
    if fn is None:
        pytest.fail('find_fast_core.human_time_short 尚未实现（见 docs/06 6.1）', pytrace=False)
    return fn(when, now=NOW, lang=lang)


@pytest.mark.parametrize('delta,zh,en', [
    (0, '刚刚', 'just now'),
    (30, '刚刚', 'just now'),
    (59, '刚刚', 'just now'),
    (60, '1 分钟前', '1 min ago'),
    (300, '5 分钟前', '5 min ago'),
    (3599, '59 分钟前', '59 min ago'),
    (3600, '1 小时前', '1 h ago'),
    (3 * 3600, '3 小时前', '3 h ago'),
    (86399, '23 小时前', '23 h ago'),
    (D, '1 天前', '1 day ago'),
    (6 * D, '6 天前', '6 days ago'),
])
def test_relative(delta, zh, en):
    assert short(NOW - delta, 'zh') == zh
    assert short(NOW - delta, 'en') == en


def test_absolute_this_year():
    assert short(ts(2026, 10, 8, 9, 30)) == '10-08'
    assert short(ts(2026, 1, 2, 0, 0)) == '01-02'


def test_absolute_other_year():
    assert short(ts(2025, 12, 31, 23, 0)) == '2025-12-31'


def test_future_clock_skew():
    assert short(NOW + 10) == '刚刚'
    assert short(NOW + 3 * D) == '2026-11-20'


def test_seven_days_is_absolute():
    # 第 7 天起不再说「天前」，避免「12 天前」这种要心算的表述
    assert short(NOW - 7 * D) == '11-10'

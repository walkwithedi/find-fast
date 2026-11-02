#!/usr/bin/env python3
"""Benchmark find-fast on a synthetic index.

Builds an index of fictional entries (no files are created), writes the cache, then starts a
fresh Python process that loads it and runs a set of queries. Reports:
  build      seconds to build the index in memory (the cost after a rescan)
  cold       seconds from starting the process to a searchable index (interpreter start included)
  queries    milliseconds per query until its first 100 rows are ready (median of five runs),
             and for reference the time to produce every row
  typing     milliseconds per keystroke while typing a query letter by letter
  rss        peak resident memory of the searching process (VmHWM), MB
With --check, exits 1 when cold > 1 s, any query > 100 ms or rss > 300 MB.

Usage: python3 scripts/bench.py [--entries 1000000] [--check] [--json] [--log-level LEVEL]
"""
import argparse
import json
import logging
import os
import random
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import find_fast_core as core  # noqa: E402

log = logging.getLogger('bench')
LIMITS = {'cold': 1.0, 'query_ms': 100.0, 'rss_mb': 300.0}
QUERIES = [
    ('report', 'mtime'), ('e', 'mtime'), ('2024 pdf', 'mtime'), ('*.pdf', 'mtime'), ('ext:pdf;docx', 'name'),
    ('report !draft', 'mtime'), ('photo|scan', 'size'), ('path:project', 'mtime'), ('regex:^img_\\d+', 'mtime'),
    ('报告', 'mtime'), ('', 'mtime'), ('', 'name'), ('a', 'path'), ('docs/2023', 'mtime'),
]
WORDS = ['report', 'draft', 'final', 'notes', 'photo', 'scan', 'invoice', 'plan', 'budget', 'meeting', 'design',
         'backup', 'archive', 'summary', 'data', 'img', 'video', 'music', 'test', 'build', 'src', 'docs', 'project',
         '报告', '方案', '会议', '纪要', '预算', '照片', '合同', '总结', 'alpha', 'beta', 'gamma', 'delta', 'omega']
EXTS = ['pdf', 'docx', 'xlsx', 'pptx', 'txt', 'md', 'jpg', 'png', 'mp4', 'py', 'js', 'html', 'zip', 'csv', 'json']


def synthetic_records(n, seed=1):
    """About n entries in folders of about ten, as depth-first records."""
    rnd = random.Random(seed)
    records, count = [], 0

    def name(folder):
        k = rnd.randint(1, 3)
        stem = '_'.join(rnd.choice(WORDS) for _ in range(k))
        if rnd.random() < 0.5:
            stem += '_%d' % rnd.randint(2015, 2026)
        if folder:
            return stem
        if stem.startswith('img') or rnd.random() < 0.1:
            stem = 'img_%04d' % rnd.randint(0, 9999)
        return '%s.%s' % (stem, rnd.choice(EXTS))

    stack = [('/home/user', 0)]
    while stack and count < n:
        d, depth = stack.pop()
        entries, subs = [], []
        nfiles = rnd.randint(4, 14)
        nsub = rnd.randint(0, 3) if depth < 7 else 0
        if depth < 2:
            nsub = 6
        for _ in range(nsub):
            nm = name(True)
            entries.append((nm, -1, rnd.randint(1500000000, 1780000000)))
            subs.append(nm)
        for _ in range(nfiles):
            entries.append((name(False), rnd.randint(0, 50000000), rnd.randint(1500000000, 1780000000)))
        seen, uniq = set(), []
        for e in sorted(entries, key=lambda x: x[0].lower()):
            if e[0] not in seen:
                seen.add(e[0])
                uniq.append(e)
        records.append((d, 0, uniq))
        count += len(uniq)
        sub_names = sorted({s for s in subs}, key=str.lower)
        stack.extend((d + '/' + s, depth + 1) for s in reversed(sub_names))
        if not stack and count < n:
            stack.append(('/home/user/more%d' % len(records), 1))
    return records


CHILD = r'''
import json, os, sys, time
t0 = float(sys.argv[3])
sys.path.insert(0, sys.argv[1])
import find_fast_core as core
idx = core.Index(core.Config('/nonexistent/config.json', {'roots': []}), sys.argv[2])
idx.config.signature = lambda: 'bench'
assert idx.load()
idx.search('x').row(0)
cold = time.time() - t0
out = {'cold': round(cold, 3), 'entries': idx.base.n, 'queries': []}
for q, sort in json.loads(sys.argv[4]):
    times, full = [], []
    for _ in range(5):
        idx.last = None
        t = time.perf_counter()
        r = idx.search(q, sort, True)
        for k in range(min(100, len(r))):
            r.row(k)
        times.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        list(r.refs)
        full.append((time.perf_counter() - t) * 1000)
    times.sort()
    full.sort()
    out['queries'].append({'query': q, 'sort': sort, 'ms': round(times[2], 1), 'all_rows_ms': round(full[2], 1),
                           'hits': len(r)})
typing = []
for q in ('r', 're', 'rep', 'repo', 'repor', 'report', 'report 2', 'report 20', 'report 202'):
    t = time.perf_counter()
    r = idx.search(q)
    for k in range(min(100, len(r))):
        r.row(k)
    typing.append(round((time.perf_counter() - t) * 1000, 1))
out['typing_ms'] = typing
with open('/proc/self/status') as f:
    hwm = [l for l in f if l.startswith('VmHWM:')][0].split()[1]
out['rss_mb'] = round(int(hwm) / 1024.0, 1)
print(json.dumps(out))
'''

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--entries', type=int, default=1000000)
    ap.add_argument('--check', action='store_true', help='exit 1 when a limit is exceeded')
    ap.add_argument('--json', action='store_true', help='print the report as JSON')
    ap.add_argument('--log-level', default=core.default_log_level(), choices=core.LOG_LEVELS)
    a = ap.parse_args()
    core.setup_logging(a.log_level)
    records = synthetic_records(a.entries)
    t = time.monotonic()
    base = core.build_base(records)
    build = round(time.monotonic() - t, 2)
    del records
    with tempfile.TemporaryDirectory(prefix='ff-bench-') as tmp:
        cache = os.path.join(tmp, 'index.bin')
        core.save_base(base, cache, 'bench')
        size_mb = round(os.path.getsize(cache) / 1048576.0, 1)
        del base
        p = subprocess.run([sys.executable, '-c', CHILD, ROOT, cache, repr(time.time()), json.dumps(QUERIES)],
                           capture_output=True, text=True)
        if p.returncode:
            print(p.stderr, file=sys.stderr)
            sys.exit(2)
    rep = json.loads(p.stdout)
    rep.update({'build': build, 'cache_mb': size_mb})
    fails = []
    if rep['cold'] > LIMITS['cold']:
        fails.append('cold start %.2fs > %.1fs' % (rep['cold'], LIMITS['cold']))
    for q in rep['queries'] + [{'query': 'typing', 'sort': 'mtime', 'ms': max(rep['typing_ms'])}]:
        if q['ms'] > LIMITS['query_ms']:
            fails.append('query %r (%s) %.0fms > %.0fms' % (q['query'], q['sort'], q['ms'], LIMITS['query_ms']))
    if rep['rss_mb'] > LIMITS['rss_mb']:
        fails.append('memory %.0fMB > %.0fMB' % (rep['rss_mb'], LIMITS['rss_mb']))
    rep['fails'] = fails
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print('entries   %d' % rep['entries'])
        print('build     %.2f s   cache %.1f MB' % (rep['build'], rep['cache_mb']))
        print('cold      %.2f s   (limit %.1f s)' % (rep['cold'], LIMITS['cold']))
        print('rss       %.1f MB  (limit %.0f MB)' % (rep['rss_mb'], LIMITS['rss_mb']))
        for q in rep['queries']:
            print('query     %7.1f ms  %8d hits  %-6s %-16s (all rows %.0f ms)' % (
                q['ms'], q['hits'], q['sort'], q['query'] or '(all)', q['all_rows_ms']))
        print('typing    ' + ' '.join('%.0f' % x for x in rep['typing_ms']) + ' ms')
        print('result: ' + ('; '.join(fails) if fails else 'all within limits'))
    sys.exit(1 if a.check and fails else 0)


if __name__ == '__main__':
    main()

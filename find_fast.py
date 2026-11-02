#!/usr/bin/env python3
"""find-fast: instant file-name search for the Linux desktop.

Without a query it opens the search window (GTK3 through the system's python3-gi, or the browser
page when that is missing); with a query it prints matching paths, newest first.

  find_fast.py                         open the window (a second start brings the open one forward)
  find_fast.py QUERY...                print matching paths
  find_fast.py --update QUERY...       rescan changed folders first
  find_fast.py --rebuild               rescan everything, then exit
Query syntax: words must all appear in the name (any case); "a|b" either; "!a" not; "*" and "?"
match a whole name; ext:pdf;docx; path:part matches the whole path (so does any word with a /);
regex:pattern, or --regex for the whole query.
"""
import argparse
import logging
import os
import sys

import find_fast_core as core

log = logging.getLogger('find_fast')


def build_parser():
    ap = argparse.ArgumentParser(prog='find-fast', description=__doc__.split('\n')[0],
                                 epilog=__doc__[__doc__.index('Query syntax'):],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('query', nargs='*', help='search words; none opens the window')
    ap.add_argument('--sort', choices=core.SORTS, default=core.DEFAULT_SORT,
                    help='mtime (default), name, path or size')
    order = ap.add_mutually_exclusive_group()
    order.add_argument('--asc', dest='desc', action='store_false', help='ascending')
    order.add_argument('--desc', dest='desc', action='store_true', help='descending (default)')
    ap.set_defaults(desc=True)
    ap.add_argument('--regex', action='store_true', help='the whole query is one regular expression')
    ap.add_argument('--limit', type=int, default=0, help='print at most this many paths (0: all)')
    ap.add_argument('--count', action='store_true', help='print only the number of matches')
    ap.add_argument('-0', '--null', action='store_true', help='end each path with NUL instead of a newline')
    ap.add_argument('--update', action='store_true', help='rescan changed folders before searching')
    ap.add_argument('--rebuild', action='store_true', help='rescan every folder')
    ap.add_argument('--status', action='store_true', help='print the index status as JSON')
    ap.add_argument('--gtk', action='store_true', help='open the GTK window (the default when available)')
    ap.add_argument('--web', action='store_true', help='open the browser page instead of the GTK window')
    ap.add_argument('--no-browser', action='store_true', help='with --web: print the address only')
    ap.add_argument('--config', default=core.CONFIG_FILE, help=argparse.SUPPRESS)
    ap.add_argument('--cache', default=core.CACHE_FILE, help=argparse.SUPPRESS)
    ap.add_argument('--version', action='version', version='find-fast ' + core.VERSION)
    ap.add_argument('--log-level', default=core.default_log_level(), choices=core.LOG_LEVELS,
                    help='log level on standard error (default WARNING, or LOG_LEVEL)')
    return ap


def open_index(args):
    index = core.Index(core.Config(args.config), args.cache)
    if args.rebuild:
        refresh(index, full=True)
    elif not index.load():
        print(core.text('no_cache'), file=sys.stderr)
        refresh(index)
    elif args.update:
        refresh(index)
    return index


def refresh(index, full=False):
    tty = sys.stderr.isatty()

    def show():
        if tty and index.state == 'scanning':
            dirs, files = index.progress
            sys.stderr.write('\r' + core.text('scan_progress', dirs=dirs, files=files) + '\033[K')
            sys.stderr.flush()
    index.on_change = show
    index.refresh(full=full)
    index.on_change = None
    if tty:
        sys.stderr.write('\r\033[K')
    if index.unreadable_count:
        print(core.text('unreadable', count=index.unreadable_count), file=sys.stderr)


def run_cli(args):
    import json
    index = open_index(args)
    if args.status:
        print(json.dumps(index.status(), ensure_ascii=False))
        return 0
    if args.rebuild and not args.query:
        return 0
    try:
        result = index.search(' '.join(args.query), args.sort, args.desc, args.regex)
    except core.QueryError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.count:
        print(len(result))
        return 0
    n = len(result) if args.limit <= 0 else min(args.limit, len(result))
    end = '\0' if args.null else '\n'
    out = sys.stdout
    try:
        for k in range(n):
            out.write(core.display(result.path(k)) + end)
        out.flush()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())     # no second error at exit
        return 0
    return 0 if len(result) else 1


def run_ui(args):
    if not args.web:
        try:
            import find_fast_gtk
        except ImportError as e:
            log.info('GTK window unavailable: %s', e)
            find_fast_gtk = None
        if find_fast_gtk is not None and find_fast_gtk.available():
            return find_fast_gtk.main(args)
        if args.gtk:
            print('find-fast: python3-gi (GTK 3) is not installed', file=sys.stderr)
            return 1
        try:
            import find_fast_web
        except ImportError:
            print('find-fast: python3-gi (GTK 3) is not installed', file=sys.stderr)
            return 1
        find_fast_web.notify_fallback()
    import find_fast_web
    return find_fast_web.main(args)


def main(argv=None):
    args = build_parser().parse_args(argv)
    core.setup_logging(args.log_level)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors='replace')
        except (AttributeError, ValueError):
            pass
    cli = bool(args.query) or args.count or args.status or args.rebuild or args.update
    if cli:
        return run_cli(args)
    return run_ui(args)


if __name__ == '__main__':
    sys.exit(main())

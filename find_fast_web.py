#!/usr/bin/env python3
"""find-fast browser page: used when python3-gi (GTK 3) is missing, or with --web.

A local web server on a random port of 127.0.0.1 serves find_fast.html. The address carries a
token made at start and valid until the process exits; Host and Origin are checked. Pages say
hello, beat every 30 seconds and say bye (sendBeacon) when closed or reloaded; a few seconds
after the last page is gone the server exits. A page silent for 10 minutes counts as closed, so
a page left in a background tab is not. A scan in progress is stopped on exit; a cache being
written is finished first.
"""
import hmac
import json
import logging
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import find_fast_core as core

log = logging.getLogger('find_fast_web')
HERE = os.path.dirname(os.path.abspath(__file__))
PAGE_FILE = os.path.join(HERE, 'find_fast.html')
PING_TIMEOUT = 600      # seconds without a beat before a page counts as closed
OPEN_TIMEOUT = 120      # seconds to wait for the first page before exiting
BYE_GRACE = 4           # seconds after the last page closed (a reload registers again meanwhile)
RESCAN_EVERY = 300      # seconds between rescans when inotify cannot watch every folder
ROWS_MAX = 500          # rows per request
VERSIONS_SYNC = 5000    # results up to this size are grouped before answering, larger ones in the background
MAX_BODY = 65536       # bytes; a settings list is the largest body

MESSAGES = {
    'zh': {
        'no_gi': '没有找到 python3-gi（GTK 3），已改用浏览器页面。安装 python3-gi 后可使用窗口版。',
        'no_page': '找不到页面文件 {path}，请重新解压完整的工具目录。',
        'no_browser': '未能自动打开浏览器，请在浏览器中打开：{url}',
        'denied': '拒绝访问',
        'not_found': '没有这个地址',
        'bad_request': '请求内容不完整',
        'stale': '结果已过期，请重新搜索',
        'gone': '文件已不存在',
        'choose_folder': '选择文件夹',
        'save_failed': '保存失败：{error}。请检查设置文件夹是否可写。',
        'cannot_exclude': '这个文件夹就是索引的文件夹，不能排除；请在「设置」里删除它。',
    },
    'en': {
        'no_gi': 'python3-gi (GTK 3) was not found, so the browser page is used. Install python3-gi for the window.',
        'no_page': 'The page file {path} is missing; unpack the whole tool folder again.',
        'no_browser': 'Could not open a browser; open this address in one: {url}',
        'denied': 'Access denied',
        'not_found': 'No such address',
        'bad_request': 'Incomplete request',
        'stale': 'The result is out of date; search again',
        'gone': 'The file no longer exists',
        'choose_folder': 'Choose a folder',
        'save_failed': 'Save failed: {error}. Check that the settings folder is writable.',
        'cannot_exclude': 'This is an indexed folder itself and cannot be excluded; remove it in Settings.',
    },
}


def msg(key, **kw):
    lang = core.ui_language()
    return MESSAGES[lang][key].format(**kw)


def tell_user(text):
    """No terminal when started by double-click: zenity or notify-send, else only the log."""
    log.warning('%s', text)
    print(text, flush=True)
    if sys.stdout.isatty():
        return
    for cmd in (['zenity', '--info', '--no-wrap', '--text=' + text], ['notify-send', text]):
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError as e:
            log.debug('%s failed: %s', cmd[0], e)


def notify_fallback():
    tell_user(msg('no_gi'))


def file_uri(path):
    return 'file://' + urllib.parse.quote(os.fsencode(path))


def open_path(path):
    """Open with the desktop's default application."""
    subprocess.Popen(['xdg-open', path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def show_in_folder(path):
    """Show the item selected in the file manager (FileManager1 through gdbus), else open its
    folder. True when the item could be selected."""
    if shutil.which('gdbus'):
        try:
            p = subprocess.run(['gdbus', 'call', '--session', '--dest', 'org.freedesktop.FileManager1',
                                '--object-path', '/org/freedesktop/FileManager1',
                                '--method', 'org.freedesktop.FileManager1.ShowItems',
                                json.dumps([file_uri(path)]).replace('"', "'"), ''],
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=5)
            if p.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired) as e:
            log.debug('gdbus failed: %s', e)
    open_path(os.path.dirname(path))
    return False


class WebState:
    def __init__(self, index, port, token):
        self.index = index
        self.port = port
        self.token = token
        self.origin = 'http://127.0.0.1:%d' % port
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.pages = {}             # page id -> last beat
        self.results = {}           # page id -> (search id, Result, {'groups': VersionGroups or None})
        self.seen = False
        self.empty_since = None
        self.quit = threading.Event()
        self.stop = threading.Event()   # stops a scan in progress
        self.worker = None
        self.opener = open_path
        self.folder_opener = show_in_folder

    def ping(self, page):
        with self.lock:
            self.pages[page] = time.monotonic()
            self.seen = True
            self.empty_since = None

    def bye(self, page):
        with self.lock:
            self.pages.pop(page, None)
            self.results.pop(page, None)
            if self.seen and not self.pages and self.empty_since is None:
                self.empty_since = time.monotonic()

    def should_exit(self):
        now = time.monotonic()
        with self.lock:
            for page, t in list(self.pages.items()):
                if now - t > PING_TIMEOUT:
                    log.info('page %s heartbeat lost', page)
                    del self.pages[page]
                    self.results.pop(page, None)
                    if not self.pages:
                        self.empty_since = now - BYE_GRACE
            if not self.seen:
                return 'page never opened' if now - self.started > OPEN_TIMEOUT else None
            if not self.pages and self.empty_since is not None and now - self.empty_since >= BYE_GRACE:
                return 'all pages closed'
        return None

    # index work in the background

    def start_index(self):
        def run():
            self.index.load()
            if self.stop.is_set():
                return
            self.index.refresh(stop=self.stop)
            if self.stop.is_set():
                return
            watching = self.index.start_watching()
            limited = not watching or (self.index.watcher is not None and self.index.watcher.limited)
            while limited and not self.stop.wait(RESCAN_EVERY):
                self.index.refresh_and_watch(stop=self.stop)
        self.worker = threading.Thread(target=run, name='index', daemon=True)
        self.worker.start()

    def rescan(self):
        if self.index.state == 'scanning':
            return False
        threading.Thread(target=self.index.refresh_and_watch, kwargs={'stop': self.stop}, daemon=True).start()
        return True

    # settings

    def settings(self):
        c = self.index.config
        return {'roots': c.roots, 'exclude': c.exclude, 'hidden': c.hidden,
                'defaults': {'roots': core.DEFAULT_ROOTS, 'exclude': core.DEFAULT_EXCLUDE, 'hidden': False},
                'can_pick': bool(shutil.which('zenity'))}

    def save_settings(self, roots, exclude, hidden, force=False):
        """{'saved': True} or {'saved': False, 'problems': [...], 'blocked': bool}."""
        roots, exclude = core.tidy_scope(roots, exclude)
        problems = core.check_scope(roots, exclude, self.index.mounts)
        blocked = any(code == 'no_roots' for _, _, code in problems)
        if blocked or (problems and not force):
            lang = core.ui_language()
            return {'saved': False, 'blocked': blocked,
                    'problems': [core.scope_problem_text(item, code, lang) for _, item, code in problems]}
        c = self.index.config
        self.apply_scope(c.with_scope(roots, exclude, hidden))
        return {'saved': True}

    def exclude(self, page, sid, k):
        """Exclude the folder of result row k (the row itself when it is a folder)."""
        with self.lock:
            got = self.results.get(page)
        if got is None or got[0] != sid or not 0 <= k < len(got[1]):
            return None
        name, folder, size, _ = got[1].row(k)
        target = os.path.join(folder, name) if size < 0 else folder
        roots = self.index.config.resolved_roots()
        if target in roots or not any(core.under(target, r) for r in roots):
            return ''
        c = self.index.config
        r, e = core.tidy_scope(c.roots, c.exclude + [core.to_tilde(target)])
        self.apply_scope(c.with_scope(r, e, c.hidden))
        return target

    def apply_scope(self, config):
        """Save the settings, stop a scan in progress, then use them in the background. Raises
        OSError when the settings cannot be written."""
        config.save()
        with self.lock:
            self.stop.set()
            old, stop = self.worker, threading.Event()
            self.stop = stop

        def run():
            if old is not None:
                old.join()
            if stop.is_set():
                return
            mode = self.index.reconfigure(config, stop=stop)
            if mode != 'stopped' and self.index.watcher is None:
                self.index.start_watching()
        self.worker = self.applying = threading.Thread(target=run, name='index', daemon=True)
        self.worker.start()

    def is_applying(self):
        t = getattr(self, 'applying', None)
        return t is not None and t.is_alive()

    def pick_folder(self, title):
        """A folder chosen in zenity's folder chooser: (path or None, available)."""
        if not shutil.which('zenity'):
            return None, False
        try:
            p = subprocess.run(['zenity', '--file-selection', '--directory', '--title=' + title,
                                '--filename=' + core.HOME + '/'],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.info('zenity failed: %s', e)
            return None, True
        path = p.stdout.strip()
        return (path if p.returncode == 0 and path else None), True

    def search(self, page, query, sort, desc, regex):
        res = self.index.search(query, sort, desc, regex)
        sid = secrets.token_hex(4)
        holder = {'groups': None}
        sync = len(res) <= VERSIONS_SYNC or len(res) > core.VERSION_GROUP_LIMIT
        if sync:
            holder['groups'] = core.VersionGroups(res)
        with self.lock:
            self.results[page] = (sid, res, holder)
        if not sync:
            def work():
                g = core.VersionGroups(res, stop=lambda: self.results.get(page, (None,))[0] != sid)
                if not g.skipped:
                    holder['groups'] = g
            threading.Thread(target=work, name='versions', daemon=True).start()
        return sid, res

    def versions_state(self, page, sid):
        """'ready', 'pending' or 'skipped' for the grouping of a search."""
        with self.lock:
            got = self.results.get(page)
        if got is None or got[0] != sid:
            return 'skipped'
        g = got[2]['groups']
        if g is None:
            return 'pending'
        return 'too_many' if g.skipped else 'ready'

    def rows(self, page, sid, offset, limit):
        with self.lock:
            got = self.results.get(page)
        if got is None or got[0] != sid:
            return None
        res, groups = got[1], got[2]['groups']
        roots = self.index.config.resolved_roots()
        out = []
        for k in range(max(0, offset), min(len(res), offset + max(0, min(limit, ROWS_MAX)))):
            name, folder, size, mtime = res.row(k)
            target = os.path.join(folder, name) if size < 0 else folder
            out.append({'k': k, 'name': core.display(name), 'dir': core.display(folder),
                        'path': core.display(os.path.join(folder, name)), 'size': size,
                        'size_text': core.human_size(size), 'mtime': mtime, 'time': core.human_time(mtime),
                        'folder': size < 0,
                        'can_exclude': target not in roots and any(core.under(target, r) for r in roots)})
            mark = groups.mark(k) if groups is not None else None
            if mark:
                newest = groups.newest(k)
                out[-1].update({'ver': mark, 'ver_count': groups.size(k), 'ver_newest': newest,
                                'ver_newest_path': core.display(res.path(newest))})
        return out

    def path_of(self, page, sid, k):
        with self.lock:
            got = self.results.get(page)
        if got is None or got[0] != sid or not 0 <= k < len(got[1]):
            return None
        return got[1].path(k)

    def close(self):
        """Stop a scan and wait for the index thread (a cache being written is finished)."""
        self.stop.set()
        for t in (self.worker,):
            if t is not None:
                t.join(timeout=60)
        self.index.close()


class Handler(BaseHTTPRequestHandler):
    state = None
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        log.debug('%s - %s', self.address_string(), fmt % args)

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def allowed(self, api, token=None):
        """Host and Origin; API calls also need the token (X-Token header). Sends 403 on failure."""
        st = self.state
        ok = self.headers.get('Host') == '127.0.0.1:%d' % st.port
        origin = self.headers.get('Origin')
        if ok and origin is not None:
            ok = origin == st.origin
        if ok and api:
            if token is None:
                token = self.headers.get('X-Token', '')
            ok = isinstance(token, str) and hmac.compare_digest(token, st.token)
        if not ok:
            log.warning('rejected %s %s', self.command, urllib.parse.urlsplit(self.path).path)
            self.send_json(403, {'error': msg('denied')})
        return ok

    def read_json(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            self.close_connection = True        # the body is not read; the connection cannot be reused
            return {}
        if n <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n).decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        api = url.path.startswith('/api/')
        if not self.allowed(api):
            return
        st = self.state
        q = urllib.parse.parse_qs(url.query)

        def arg(name, default=''):
            return (q.get(name) or [default])[0]

        if url.path in ('/', '/index.html'):
            try:
                with open(PAGE_FILE, 'rb') as f:
                    body = f.read()
            except OSError as e:
                log.error('page missing: %s', e)
                self.send_json(500, {'error': msg('no_page', path=PAGE_FILE)})
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
            self.end_headers()
            self.wfile.write(body)
        elif url.path == '/api/status':
            status = st.index.status()
            status['lang'] = core.ui_language()
            status['applying'] = st.is_applying()
            self.send_json(200, status)
        elif url.path == '/api/search':
            try:
                sid, res = st.search(arg('page'), arg('q'), arg('sort', core.DEFAULT_SORT), arg('desc', '1') == '1',
                                     arg('regex') == '1')
            except core.QueryError as e:
                self.send_json(200, {'error': str(e), 'count': 0, 'rows': []})
                return
            try:
                limit = int(arg('limit', '100'))
            except ValueError:
                limit = 100
            self.send_json(200, {'sid': sid, 'count': len(res), 'ms': res.ms,
                                 'rows': st.rows(arg('page'), sid, 0, limit),
                                 'versions': st.versions_state(arg('page'), sid)})
        elif url.path == '/api/settings':
            self.send_json(200, st.settings())
        elif url.path == '/api/rows':
            try:
                offset, limit = int(arg('offset', '0')), int(arg('limit', '100'))
            except ValueError:
                offset, limit = 0, 0
            rows = st.rows(arg('page'), arg('sid'), offset, limit)
            if rows is None:
                self.send_json(409, {'error': msg('stale')})
            else:
                self.send_json(200, {'rows': rows, 'versions': st.versions_state(arg('page'), arg('sid'))})
        else:
            self.send_json(404, {'error': msg('not_found')})

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        st = self.state
        if url.path == '/api/bye':
            # sent with sendBeacon, which cannot add headers: the token is in the body
            data = self.read_json()
            if not self.allowed(True, data.get('t')):
                return
            log.info('page %s closed', data.get('page'))
            st.bye(str(data.get('page')))
            self.send_json(200, {'ok': True})
            return
        if not self.allowed(True):
            return
        data = self.read_json()
        if url.path == '/api/ping':
            st.ping(str(data.get('page')))
            self.send_json(200, {'ok': True})
        elif url.path in ('/api/open', '/api/open_folder'):
            try:
                k = int(data.get('k'))
            except (TypeError, ValueError):
                k = -1
            path = st.path_of(str(data.get('page')), str(data.get('sid')), k)
            if path is None:
                self.send_json(409, {'error': msg('stale')})
                return
            if not os.path.lexists(path):
                self.send_json(410, {'error': msg('gone')})
                return
            try:
                done = (st.opener if url.path == '/api/open' else st.folder_opener)(path)
            except OSError as e:
                self.send_json(500, {'error': str(e)})
                return
            self.send_json(200, {'ok': True, 'selected': done is not False})
        elif url.path == '/api/settings':
            roots, exclude = data.get('roots'), data.get('exclude')
            if not isinstance(roots, list) or not isinstance(exclude, list):
                self.send_json(400, {'error': msg('bad_request')})
                return
            try:
                out = st.save_settings([r for r in roots if isinstance(r, str)],
                                       [e for e in exclude if isinstance(e, str)],
                                       bool(data.get('hidden')), bool(data.get('force')))
            except OSError as e:
                self.send_json(500, {'error': msg('save_failed', error=e.strerror or e)})
                return
            self.send_json(200, out)
        elif url.path == '/api/pick_folder':
            path, available = st.pick_folder(msg('choose_folder'))
            self.send_json(200, {'path': path, 'available': available})
        elif url.path == '/api/exclude':
            try:
                k = int(data.get('k'))
            except (TypeError, ValueError):
                k = -1
            try:
                target = st.exclude(str(data.get('page')), str(data.get('sid')), k)
            except OSError as e:
                self.send_json(500, {'error': msg('save_failed', error=e.strerror or e)})
                return
            if target is None:
                self.send_json(409, {'error': msg('stale')})
            elif not target:
                self.send_json(400, {'error': msg('cannot_exclude')})
            else:
                self.send_json(200, {'excluded': core.display(target)})
        elif url.path == '/api/rescan':
            self.send_json(200, {'started': st.rescan()})
        elif url.path == '/api/quit':
            log.info('quit requested by page')
            st.quit.set()       # before the reply, so a caller that sees the reply sees the flag
            self.send_json(200, {'ok': True})
        else:
            self.send_json(404, {'error': msg('not_found')})


def watchdog(server, st, interval=1.0):
    while not st.quit.wait(interval):
        reason = st.should_exit()
        if reason:
            log.info('%s, exiting', reason)
            break
    server.shutdown()


def make_server(index):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    st = WebState(index, server.server_address[1], secrets.token_urlsafe(24))
    Handler.state = st
    return server, st


def main(args=None):
    if not os.path.isfile(PAGE_FILE):
        tell_user(msg('no_page', path=PAGE_FILE))
        return 1
    config = core.Config(getattr(args, 'config', core.CONFIG_FILE))
    index = core.Index(config, getattr(args, 'cache', core.CACHE_FILE))
    server, st = make_server(index)
    url = '%s/?t=%s' % (st.origin, st.token)
    log.info('serving on %s', st.origin)
    print('find-fast: ' + url, flush=True)
    st.start_index()
    threading.Thread(target=watchdog, args=(server, st), daemon=True).start()
    if not getattr(args, 'no_browser', False) and not webbrowser.open(url):
        tell_user(msg('no_browser', url=url))
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        st.close()
    log.info('server stopped')
    return 0


if __name__ == '__main__':
    import find_fast
    sys.exit(find_fast.main(['--web'] + sys.argv[1:]))

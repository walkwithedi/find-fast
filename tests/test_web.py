"""Tests of the local web server of the browser page (find_fast_web.py)."""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))
import find_fast_core as core  # noqa: E402
import find_fast_web as web  # noqa: E402
from test_core import make_tree  # noqa: E402


class WebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='ff-web-')
        self.root = os.path.join(self.tmp, 'root')
        make_tree(self.root)
        config = core.Config(os.path.join(self.tmp, 'config.json'), {'roots': [self.root]})
        self.index = core.Index(config, os.path.join(self.tmp, 'index.bin'), mounts={})
        self.server, self.st = web.make_server(self.index)
        self.opened = []
        self.st.opener = lambda p: self.opened.append(('open', p))
        self.st.folder_opener = lambda p: self.opened.append(('folder', p))
        self.st.start_index()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()
        deadline = time.time() + 10
        while (self.index.state != 'ready' or self.st.worker.is_alive()) and time.time() < deadline:
            time.sleep(0.02)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.st.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, method, path, body=None, token=True, host=None, origin=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.st.port, timeout=10)
        h = {'Host': host or '127.0.0.1:%d' % self.st.port}
        if token:
            h['X-Token'] = self.st.token if token is True else token
        if origin:
            h['Origin'] = origin
        if body is not None:
            h['Content-Type'] = 'application/json'
            body = json.dumps(body)
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        try:
            return r.status, json.loads(data)
        except ValueError:
            return r.status, data

    def search(self, q, **kw):
        p = dict(page='p1', q=q, sort='path', desc='0')
        p.update(kw)
        return self.req('GET', '/api/search?' + urllib.parse.urlencode(p))

    def test_page_needs_host_and_origin_api_needs_token(self):
        self.assertEqual(self.req('GET', '/', token=False)[0], 200)
        self.assertEqual(self.req('GET', '/', token=False, host='localhost:%d' % self.st.port)[0], 403)
        self.assertEqual(self.req('GET', '/', token=False, host='evil.example')[0], 403)
        self.assertEqual(self.req('GET', '/api/status', token=False)[0], 403)
        self.assertEqual(self.req('GET', '/api/status', token='wrong')[0], 403)
        self.assertEqual(self.req('GET', '/api/status', origin='http://evil.example')[0], 403)
        code, st = self.req('GET', '/api/status', origin=self.st.origin)
        self.assertEqual(code, 200)
        self.assertEqual(st['state'], 'ready')
        self.assertEqual(st['version'], core.VERSION)
        self.assertEqual(self.req('GET', '/nothing')[0], 404)

    def test_search_rows_and_errors(self):
        code, j = self.search('report')
        self.assertEqual((code, j['count']), (200, 3))
        self.assertEqual([r['name'] for r in j['rows']], ['Report 2024.pdf', 'report-draft.docx', 'report-2019.pdf'])
        self.assertEqual(j['rows'][0]['path'], os.path.join(self.root, 'docs', 'Report 2024.pdf'))
        code, j2 = self.req('GET', '/api/rows?' + urllib.parse.urlencode(dict(page='p1', sid=j['sid'], offset=1, limit=1)))
        self.assertEqual([r['name'] for r in j2['rows']], ['report-draft.docx'])
        self.assertEqual(self.req('GET', '/api/rows?page=p1&sid=stale&offset=0&limit=5')[0], 409)
        code, j3 = self.search('regex:(')
        self.assertIn('error', j3)
        code, j4 = self.search('', limit=2)
        self.assertEqual((j4['count'], len(j4['rows'])), (11, 2))

    def test_open_only_result_rows(self):
        code, j = self.search('notes')
        self.assertEqual(self.req('POST', '/api/open', {'page': 'p1', 'sid': j['sid'], 'k': 0})[0], 200)
        self.assertEqual(self.req('POST', '/api/open_folder', {'page': 'p1', 'sid': j['sid'], 'k': 0})[0], 200)
        p = os.path.join(self.root, 'docs', 'notes.txt')
        self.assertEqual(self.opened, [('open', p), ('folder', p)])
        self.assertEqual(self.req('POST', '/api/open', {'page': 'p1', 'sid': j['sid'], 'k': 5})[0], 409)
        self.assertEqual(self.req('POST', '/api/open', {'page': 'p2', 'sid': j['sid'], 'k': 0})[0], 409)
        self.assertEqual(self.req('POST', '/api/open', {'page': 'p1', 'sid': j['sid'], 'k': 0}, token=False)[0], 403)
        os.remove(p)
        self.assertEqual(self.req('POST', '/api/open', {'page': 'p1', 'sid': j['sid'], 'k': 0})[0], 410)
        self.assertEqual(len(self.opened), 2)

    def test_page_lifecycle(self):
        self.assertIsNone(self.st.should_exit())
        self.req('POST', '/api/ping', {'page': 'a'})
        self.req('POST', '/api/ping', {'page': 'b'})
        self.assertEqual(self.req('POST', '/api/bye', {'t': 'wrong', 'page': 'a'}, token=False)[0], 403)
        self.assertEqual(self.req('POST', '/api/bye', {'t': self.st.token, 'page': 'a'}, token=False)[0], 200)
        self.assertIsNone(self.st.should_exit())
        self.req('POST', '/api/bye', {'t': self.st.token, 'page': 'b'}, token=False)
        self.assertIsNone(self.st.should_exit())          # within the grace time a reload registers again
        self.st.empty_since -= web.BYE_GRACE
        self.assertEqual(self.st.should_exit(), 'all pages closed')
        self.req('POST', '/api/ping', {'page': 'c'})
        self.assertIsNone(self.st.should_exit())
        self.st.pages['c'] -= web.PING_TIMEOUT + 1
        self.assertEqual(self.st.should_exit(), 'all pages closed')

    def test_page_never_opened(self):
        self.st.started -= web.OPEN_TIMEOUT + 1
        self.assertEqual(self.st.should_exit(), 'page never opened')

    def test_quit_and_rescan(self):
        code, j = self.req('POST', '/api/rescan')
        self.assertEqual(code, 200)
        self.assertIn('started', j)
        self.assertEqual(self.req('POST', '/api/quit')[0], 200)
        self.assertTrue(self.st.quit.is_set())

    def test_oversized_body_ignored(self):
        code, _ = self.req('POST', '/api/ping', headers={'Content-Length': '9999999'}, body=None)
        self.assertIn(code, (200, 400))

    def test_messages_have_same_keys(self):
        self.assertEqual(set(web.MESSAGES['zh']), set(web.MESSAGES['en']))


if __name__ == '__main__':
    unittest.main()

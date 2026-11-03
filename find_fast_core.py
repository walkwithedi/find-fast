#!/usr/bin/env python3
"""find-fast core: file-name index, cache, query language and search. No user interface here.

Index layout (class Base). Entries are the files and folders found under the roots, in
depth-first order with the children of every folder sorted by lower-case name, so the natural
order is the "path" sort. Per entry: its folder (file_dir), its name (names_blob, NUL-separated
UTF-8 with surrogateescape, offsets in name_off), size (-1 for a folder) and modification time
in seconds. Searching works on `low`, the list of lower-case names, through C-level map/compress
calls; the name, size and time sorts are precomputed permutations.

Changes seen while running (inotify, class Watcher) go to an overlay instead of rebuilding the
base: the old entries of a re-listed folder are tombstoned and its new listing kept in `extra`,
which is searched entry by entry and merged into the sorted result.

Standard library only. Python 3.8+.
"""
import array
import collections
import ctypes
import errno
import fnmatch
import itertools
import json
import logging
import operator
import os
import re
import select
import stat
import struct
import sys
import threading
import time

log = logging.getLogger('find_fast_core')
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s.%(funcName)s:%(lineno)d - %(message)s'
LOG_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR')

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser('~')


def _read_version():
    try:
        with open(os.path.join(HERE, 'VERSION'), encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return '0.0.0'


VERSION = _read_version()
CONFIG_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.join(HOME, '.config'), 'find-fast')
CACHE_DIR = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.join(HOME, '.cache'), 'find-fast')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
CACHE_FILE = os.path.join(CACHE_DIR, 'index.bin')

DEFAULT_ROOTS = ['~', '/media', '/mnt']
DEFAULT_EXCLUDE = ['node_modules', '__pycache__', 'lost+found', '$RECYCLE.BIN', 'System Volume Information']
SORTS = ('mtime', 'name', 'path', 'size')
DEFAULT_SORT = 'mtime'

# File systems never indexed: network mounts and kernel pseudo file systems.
NETWORK_FS = {'nfs', 'nfs4', 'cifs', 'smb', 'smb3', 'smbfs', 'ncpfs', 'afs', 'ceph', 'glusterfs',
              'lustre', 'gpfs', 'davfs', '9p', 'virtiofs', 'sshfs', 'ftpfs', 'curlftpfs'}
PSEUDO_FS = {'proc', 'sysfs', 'devtmpfs', 'devpts', 'cgroup', 'cgroup2', 'debugfs', 'tracefs',
             'securityfs', 'pstore', 'bpf', 'autofs', 'mqueue', 'hugetlbfs', 'configfs', 'fusectl',
             'binfmt_misc', 'efivarfs', 'rpc_pipefs', 'nsfs', 'selinuxfs', 'ramfs'}
# FUSE file systems that hold local data; every other fuse.* type is treated as remote.
LOCAL_FUSE = {'fuse.ntfs-3g', 'fuse.exfat', 'fuse.ext4fuse', 'fuse.fuse-ext2', 'fuse.bindfs'}

PROGRESS_EVERY = 0.5        # seconds between progress reports while scanning
RACY_NS = 2 * 10 ** 9       # a folder changed this close to its listing is listed again next time
EXTRA_LIMIT = 200000        # overlay entries before a full rebuild is asked for
UNREADABLE_SHOWN = 5


# ---------------------------------------------------------------- text

STRINGS = {
    'zh': {
        'app_name': '秒搜文件',
        'bad_regex': '正则表达式有误：{error}',
        'no_cache': '还没有索引，正在首次建立……',
        'scan_progress': '正在建立索引：{dirs} 个文件夹，{files} 个条目',
        'scan_done': '索引已更新：{files} 个条目，用时 {seconds} 秒',
        'unreadable': '有 {count} 个文件夹无法读取，已跳过',
        'results': '{count} 个结果',
        'watch_on': '实时更新',
        'watch_limited': '部分文件夹定时更新（监听数已达系统上限）',
        'watch_off': '定时更新',
        'scope_no_roots': '至少要有一个索引的文件夹',
        'scope_missing': '{item}：文件夹不存在',
        'scope_network': '{item}：在网络挂载或系统伪文件系统上，不会被索引',
        'scope_nested': '{item}：包含在另一个索引的文件夹里，只按外层的算',
        'scope_outside': '{item}：不在任何索引的文件夹里，这条排除不起作用',
    },
    'en': {
        'app_name': 'find-fast',
        'bad_regex': 'Invalid regular expression: {error}',
        'no_cache': 'No index yet; building it for the first time...',
        'scan_progress': 'Indexing: {dirs} folders, {files} entries',
        'scan_done': 'Index updated: {files} entries in {seconds} s',
        'unreadable': '{count} folders could not be read and were skipped',
        'results': '{count} results',
        'watch_on': 'live updates',
        'watch_limited': 'some folders updated periodically (system watch limit reached)',
        'watch_off': 'periodic updates',
        'scope_no_roots': 'At least one folder must be indexed',
        'scope_missing': '{item}: the folder does not exist',
        'scope_network': '{item}: on a network mount or system pseudo file system, so it is not indexed',
        'scope_nested': '{item}: inside another indexed folder; only the outer one counts',
        'scope_outside': '{item}: not inside any indexed folder, so this exclusion has no effect',
    },
}


def ui_language(env=None):
    """'zh' when the first of LC_ALL, LC_MESSAGES, LANGUAGE, LANG that is set starts with zh, else 'en'."""
    env = os.environ if env is None else env
    for key in ('LC_ALL', 'LC_MESSAGES', 'LANGUAGE', 'LANG'):
        value = env.get(key)
        if value:
            return 'zh' if value.lower().startswith('zh') else 'en'
    return 'en'


def text(key, lang=None, **kw):
    table = STRINGS.get(lang or ui_language(), STRINGS['en'])
    return table.get(key, STRINGS['en'].get(key, key)).format(**kw)


# ---------------------------------------------------------------- configuration

def write_private(path, data):
    """Write bytes atomically with mode 600: the index lists private file names."""
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = '%s.%d.tmp' % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Config:
    """roots: folders to index (~ allowed); exclude: names (wildcards allowed) or paths (with /)
    to skip; hidden: also index names that start with a dot."""

    def __init__(self, path=CONFIG_FILE, data=None):
        self.path = path
        if data is None:
            data = {}
            try:
                with open(path, encoding='utf-8') as f:
                    data = json.load(f)
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as e:
                log.warning('cannot read %s, using defaults: %s', path, e)
                data = {}
        if not isinstance(data, dict):
            data = {}
        self.roots = self._strings(data.get('roots'), DEFAULT_ROOTS)
        self.exclude = self._strings(data.get('exclude'), DEFAULT_EXCLUDE)
        self.hidden = bool(data.get('hidden', False))
        # other keys (interface settings) are kept as they are and written back on save
        self.other = {k: v for k, v in data.items() if k not in ('roots', 'exclude', 'hidden')}

    @staticmethod
    def _strings(value, default):
        if not isinstance(value, list):
            return list(default)
        return [v for v in value if isinstance(v, str) and v.strip()]

    def data(self):
        out = dict(self.other)
        out.update({'roots': self.roots, 'exclude': self.exclude, 'hidden': self.hidden})
        return out

    def with_scope(self, roots, exclude, hidden):
        """A copy of this configuration (same file, same other keys) with a new index scope."""
        data = self.data()
        data.update({'roots': list(roots), 'exclude': list(exclude), 'hidden': bool(hidden)})
        return Config(self.path, data)

    def save(self):
        write_private(self.path, json.dumps(self.data(), ensure_ascii=False, indent=2).encode('utf-8'))

    def resolved_roots(self):
        """Absolute, existing roots; a root inside another root is dropped."""
        out = []
        for r in self.roots:
            p = os.path.normpath(os.path.expanduser(r.strip()))
            if os.path.isabs(p) and os.path.isdir(p):
                out.append(p)
        out = sorted(set(out))
        kept = []
        for p in out:
            if not any(p == k or p.startswith(k.rstrip('/') + '/') for k in kept):
                kept.append(p)
        return kept

    def signature(self):
        """Identifies the index a cache belongs to; another signature means a full rescan."""
        return json.dumps({'roots': self.resolved_roots(), 'exclude': self.exclude, 'hidden': self.hidden},
                          sort_keys=True, ensure_ascii=False)

    def excluder(self):
        return Excluder(self.exclude, self.hidden)


# ---------------------------------------------------------------- settings checks

def is_path_rule(rule):
    """An exclusion that names a folder (has / or starts with ~) rather than a name pattern."""
    rule = rule.strip()
    return '/' in rule or rule.startswith('~')


def expand(path):
    return os.path.normpath(os.path.expanduser(path.strip()))


def to_tilde(path, home=None):
    """Write a folder under the home folder as ~ or ~/..., others as they are (normalised)."""
    home = (home or HOME).rstrip('/') or '/'
    p = expand(path)
    if p == home:
        return '~'
    if home != '/' and p.startswith(home + '/'):
        return '~/' + p[len(home) + 1:]
    return p


def tidy_scope(roots, exclude):
    """(roots, exclude) without blanks and duplicates (the same folder written two ways counts
    once; the first spelling is kept), folders under home written with ~."""
    out_r, seen = [], set()
    for r in roots:
        if not isinstance(r, str) or not r.strip():
            continue
        key = expand(r)
        if key not in seen:
            seen.add(key)
            out_r.append(to_tilde(r))
    out_e, seen = [], set()
    for e in exclude:
        if not isinstance(e, str) or not e.strip():
            continue
        e = e.strip()
        key = ('p', expand(e)) if is_path_rule(e) else ('n', e)
        if key not in seen:
            seen.add(key)
            out_e.append(to_tilde(e) if is_path_rule(e) else e)
    return out_r, out_e


def fs_type_of(path, mounts):
    """File system type of the mount that holds path (longest mount point prefix), or None."""
    best, kind = '', None
    for point, fstype in mounts.items():
        p = point.rstrip('/') or '/'
        if (path == p or p == '/' or path.startswith(p + '/')) and len(p) > len(best):
            best, kind = p, fstype
    return kind


def under(path, folder):
    return path == folder or path.startswith(folder.rstrip('/') + '/')


def check_scope(roots, exclude, mounts=None):
    """Problems with an index scope, as (list, item, code) tuples: list is 'roots' or 'exclude';
    code is 'no_roots' (nothing to index: may not be saved), 'missing', 'network', 'nested' or
    'outside' (worth a warning; saving anyway is allowed)."""
    mounts = read_mounts() if mounts is None else mounts
    if not roots:
        return [('roots', '', 'no_roots')]
    out = []
    paths = [(r, expand(r)) for r in roots]
    for r, p in paths:
        if not os.path.isdir(p):
            out.append(('roots', r, 'missing'))
            continue
        kind = fs_type_of(p, mounts)
        if kind is not None and fs_excluded(kind):
            out.append(('roots', r, 'network'))
        if any(q != p and under(p, q) for _, q in paths):
            out.append(('roots', r, 'nested'))
    for e in exclude:
        if not is_path_rule(e):
            continue
        p = expand(e)
        if not os.path.exists(p):
            out.append(('exclude', e, 'missing'))
        elif not any(under(p, q) for _, q in paths):
            out.append(('exclude', e, 'outside'))
    return out


def scope_problem_text(item, code, lang=None):
    return text('scope_' + code, lang, item=display(item))


class Excluder:
    def __init__(self, patterns, hidden=False):
        self.hidden = hidden
        self.paths, self.names, self.globs = [], set(), []
        for p in patterns:
            p = p.strip()
            if '/' in p or p.startswith('~'):
                self.paths.append(os.path.normpath(os.path.expanduser(p)))
            elif any(c in p for c in '*?['):
                self.globs.append(re.compile(fnmatch.translate(p)))
            else:
                self.names.add(p)

    def skip_name(self, name):
        if not self.hidden and name.startswith('.'):
            return True
        if name in self.names:
            return True
        return any(g.match(name) for g in self.globs)

    def skip_path(self, path):
        return any(path == p or path.startswith(p.rstrip('/') + '/') for p in self.paths)


# ---------------------------------------------------------------- mounts

def _unescape_mount(s):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), s)


def read_mounts(path='/proc/self/mounts'):
    """{mount point: file system type}; empty when the table cannot be read."""
    out = {}
    try:
        with open(path, encoding='utf-8', errors='surrogateescape') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    out[_unescape_mount(parts[1])] = parts[2]
    except OSError as e:
        log.warning('cannot read %s: %s', path, e)
    return out


def fs_excluded(fstype):
    if fstype in NETWORK_FS or fstype in PSEUDO_FS:
        return True
    return fstype.startswith('fuse.') and fstype not in LOCAL_FUSE


# ---------------------------------------------------------------- the index

LOWER_CHUNK = 65536             # names lower-cased per step while loading (bounds the peak memory)


def lower_split(blob, off=None):
    """Lower-case names from a NUL-terminated name blob, one string per entry, built in steps
    so that no copy of the whole blob is held as text. The strings are created in entry order,
    which keeps a scan over them cache friendly."""
    if not blob:
        return []
    if off is None:
        return blob.decode('utf-8', 'surrogateescape').lower().split('\0')[:-1]
    out = []
    n = len(off) - 1
    for a in range(0, n, LOWER_CHUNK):
        b = min(n, a + LOWER_CHUNK)
        out.extend(blob[off[a]:off[b] - 1].decode('utf-8', 'surrogateescape').lower().split('\0'))
    return out


def encode_name(s):
    return s.encode('utf-8', 'surrogateescape')


def decode_name(b):
    return b.decode('utf-8', 'surrogateescape')


def display(s):
    """A name or path that may hold undecodable bytes, made printable (U+FFFD for bad bytes)."""
    return s.encode('utf-8', 'surrogateescape').decode('utf-8', 'replace')


def inverse(order):
    """rank[order[j]] = j."""
    rank = array.array('I', [0]) * len(order)
    collections.deque(map(rank.__setitem__, order, range(len(order))), maxlen=0)
    return rank


class Base:
    """An immutable snapshot of the index. Entry numbers run from the newest modification time
    to the oldest; see the module docstring."""

    def __init__(self, dirs, dir_mtime, dir_start, names_blob, name_off, sizes, mtimes, file_dir, orders, ranks,
                 low=None):
        self.dirs = dirs
        self.dir_mtime = dir_mtime
        self.dir_start = dir_start      # entries of folder d: orders['path'][dir_start[d]:dir_start[d + 1]]
        self.names_blob = names_blob
        self.name_off = name_off
        self.sizes = sizes
        self.mtimes = mtimes
        self.file_dir = file_dir
        self.orders = orders            # 'name', 'size', 'path': entry numbers in ascending order
        self.ranks = ranks              # position of each entry in the matching order
        self.low = lower_split(names_blob, name_off) if low is None else low
        self.n = len(sizes)
        self._dirs_slash = None
        self._dir_index = None
        self._dir_keys = {}

    @property
    def dirs_slash(self):
        """Lower-case folder paths ending in /."""
        if self._dirs_slash is None:
            self._dirs_slash = [d if d.endswith('/') else d + '/' for d in map(str.lower, self.dirs)]
        return self._dirs_slash

    def name(self, i):
        return decode_name(self.names_blob[self.name_off[i]:self.name_off[i + 1] - 1])

    def path(self, i):
        return os.path.join(self.dirs[self.file_dir[i]], self.name(i))

    def dir_index(self):
        """{folder path: folder number}, built on first use."""
        if self._dir_index is None:
            self._dir_index = {d: i for i, d in enumerate(self.dirs)}
        return self._dir_index

    def dir_entries(self, di):
        """Entry numbers of folder di, in name order."""
        return self.orders['path'][self.dir_start[di]:self.dir_start[di + 1]]

    def entries_of(self, di):
        """[(name, size, mtime)] of folder number di, in name order."""
        return [(self.name(i), self.sizes[i], self.mtimes[i]) for i in self.dir_entries(di)]

    def dir_key(self, di):
        key = self._dir_keys.get(di)
        if key is None:
            key = self._dir_keys[di] = path_key(self.dirs_slash[di])
        return key

    def sort_key(self, i, sort):
        if sort == 'mtime':
            return self.mtimes[i]
        if sort == 'size':
            return self.sizes[i]
        if sort == 'name':
            return self.low[i]
        return (self.dir_key(self.file_dir[i]), self.low[i])


def path_key(dir_low):
    return tuple(p for p in dir_low.split('/') if p)


def build_base(records):
    """records: [(folder, folder mtime_ns, [(name, size, mtime), ...])] in path order (depth
    first, children by lower-case name). Entries are renumbered newest first."""
    dirs, dir_mtime, dir_start = [], array.array('q'), array.array('I')
    names, p_sizes, p_mtimes, p_dir = [], array.array('q'), array.array('q'), array.array('I')
    for di, (d, m, entries) in enumerate(records):
        dirs.append(d)
        dir_mtime.append(m)
        dir_start.append(len(names))
        for name, size, mtime in entries:
            names.append(name)
            p_sizes.append(size)
            p_mtimes.append(mtime)
        p_dir.extend(itertools.repeat(di, len(entries)))
    dir_start.append(len(names))
    n = len(names)
    # perm[i]: path position of entry i; newest first, ties in path order
    neg = array.array('q', map(operator.neg, p_mtimes))
    perm = sorted(range(n), key=neg.__getitem__)
    del neg
    encoded = [encode_name(names[p]) for p in perm]
    del names
    names_blob = b'\0'.join(encoded) + (b'\0' if encoded else b'')
    name_off = array.array('I', itertools.accumulate(itertools.chain((0,), (len(e) + 1 for e in encoded))))
    del encoded
    sizes = array.array('q', map(p_sizes.__getitem__, perm))
    mtimes = array.array('q', map(p_mtimes.__getitem__, perm))
    file_dir = array.array('I', map(p_dir.__getitem__, perm))
    del p_sizes, p_mtimes, p_dir
    perm = array.array('I', perm)
    order_path = inverse(perm)
    del perm
    low = lower_split(names_blob, name_off)
    orders = {
        'path': order_path,
        'name': array.array('I', sorted(range(n), key=low.__getitem__)),
        'size': array.array('I', sorted(range(n), key=sizes.__getitem__)),
    }
    ranks = {k: inverse(v) for k, v in orders.items()}
    return Base(dirs, dir_mtime, dir_start, names_blob, name_off, sizes, mtimes, file_dir, orders, ranks, low)


def empty_base():
    return build_base([])


# ---------------------------------------------------------------- cache file

MAGIC = b'FINDFAST-INDEX\n'
CACHE_FORMAT = 2
SECTIONS = [('dirs', None), ('dir_mtime', 'q'), ('dir_start', 'I'), ('names_blob', None), ('name_off', 'I'),
            ('sizes', 'q'), ('mtimes', 'q'), ('file_dir', 'I'),
            ('order_path', 'I'), ('order_name', 'I'), ('order_size', 'I'),
            ('rank_path', 'I'), ('rank_name', 'I'), ('rank_size', 'I')]


def _section_bytes(base, name):
    if name == 'dirs':
        return b'\0'.join(encode_name(d) for d in base.dirs)
    if name == 'names_blob':
        return base.names_blob
    if name.startswith('order_'):
        return base.orders[name[6:]].tobytes()
    if name.startswith('rank_'):
        return base.ranks[name[5:]].tobytes()
    return getattr(base, name).tobytes()


def save_base(base, path, signature, meta=None):
    parts = [(name, _section_bytes(base, name)) for name, _ in SECTIONS]
    header = {'format': CACHE_FORMAT, 'byteorder': sys.byteorder, 'signature': signature,
              'itemsize': {'I': array.array('I').itemsize, 'q': array.array('q').itemsize},
              'sections': [[name, len(data)] for name, data in parts], 'meta': meta or {}}
    head = json.dumps(header, ensure_ascii=False).encode('utf-8')
    data = b''.join([MAGIC, struct.pack('<I', len(head)), head] + [d for _, d in parts])
    del parts
    write_private(path, data)
    log.info('cache written: %s, %d entries, %d bytes', path, base.n, len(data))


def load_base(path, signature):
    """(Base, meta) from the cache, or (None, None) when it is missing, stale or unreadable.
    Sections are read straight into their arrays, so the file is never held twice."""
    try:
        f = open(path, 'rb')
    except FileNotFoundError:
        return None, None
    except OSError as e:
        log.warning('cannot read cache %s: %s', path, e)
        return None, None
    try:
        with f:
            if f.read(len(MAGIC)) != MAGIC:
                raise ValueError('not a find-fast cache')
            (hlen,) = struct.unpack('<I', f.read(4))
            header = json.loads(f.read(hlen).decode('utf-8'))
            if header.get('format') != CACHE_FORMAT or header.get('byteorder') != sys.byteorder:
                raise ValueError('another cache format')
            if header.get('itemsize') != {'I': array.array('I').itemsize, 'q': array.array('q').itemsize}:
                raise ValueError('another item size')
            if header.get('signature') != signature:
                log.info('cache belongs to other settings; rescanning')
                return None, None
            types = dict(SECTIONS)
            if [s[0] for s in header['sections']] != [s[0] for s in SECTIONS]:
                raise ValueError('other sections')
            out = {}
            for name, size in header['sections']:
                tc = types[name]
                if tc is None:
                    chunk = f.read(size)
                    if len(chunk) != size:
                        raise ValueError('truncated')
                    out[name] = chunk
                else:
                    a = array.array(tc)
                    if size % a.itemsize:
                        raise ValueError('bad section size')
                    try:
                        a.fromfile(f, size // a.itemsize)
                    except EOFError:
                        raise ValueError('truncated')
                    out[name] = a
        dirs = [decode_name(d) for d in out['dirs'].split(b'\0')] if out['dir_mtime'] else []
        del out['dirs']
        n = len(out['sizes'])
        if not (len(out['dir_start']) == len(dirs) + 1 and len(out['name_off']) == n + 1
                and len(out['file_dir']) == n and len(out['mtimes']) == n
                and all(len(out[k]) == n for k in out if k.startswith(('order_', 'rank_')))
                and (n == 0 or out['name_off'][n] == len(out['names_blob']))):
            raise ValueError('inconsistent sections')
        base = Base(dirs, out['dir_mtime'], out['dir_start'], out['names_blob'], out['name_off'], out['sizes'],
                    out['mtimes'], out['file_dir'],
                    {k: out['order_' + k] for k in ('path', 'name', 'size')},
                    {k: out['rank_' + k] for k in ('path', 'name', 'size')})
        if len(base.low) != n:
            raise ValueError('inconsistent names')
        return base, header.get('meta') or {}
    except (ValueError, KeyError, TypeError, struct.error, UnicodeDecodeError, OSError) as e:
        log.warning('cache %s unusable (%s); rescanning', path, e)
        return None, None


# ---------------------------------------------------------------- scanning

class ScanAborted(Exception):
    pass


def list_dir(d, excluder):
    """(entries [(name, size, mtime)] sorted by lower-case name, subfolder names). Raises OSError."""
    entries, subs = [], []
    with os.scandir(d) as it:
        for e in it:
            name = e.name
            if excluder.skip_name(name):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if excluder.skip_path(os.path.join(d, name)):
                        continue
                    st = e.stat(follow_symlinks=False)
                    entries.append((name, -1, int(st.st_mtime)))
                    subs.append(name)
                else:
                    st = e.stat(follow_symlinks=False)
                    entries.append((name, st.st_size, int(st.st_mtime)))
            except OSError:
                continue
    entries.sort(key=lambda x: x[0].lower())
    subs.sort(key=str.lower)
    return entries, subs


def keep_entry(folder, entry, excluder):
    """True when an entry (name, size, mtime) of folder passes the exclusions, as list_dir judges."""
    name, size, _ = entry
    if excluder.skip_name(name):
        return False
    return not (size == -1 and excluder.skip_path(os.path.join(folder, name)))


def prune_records(base, extra_dirs, dead, roots, excluder):
    """Records (as scan returns them) of the index as it is now (base plus overlay), less what
    the exclusions skip, without touching the disk. Folders only in the overlay are not included
    (their parents keep them as entries); returns (records, overlay folders to list again)."""
    records, skipped = [], set()
    roots = [r.rstrip('/') or '/' for r in roots]
    for di, d in enumerate(base.dirs):
        if not any(under(d, r) for r in roots) or excluder.skip_path(d):
            skipped.add(d)
            continue
        if d not in roots and (d in skipped or os.path.dirname(d) in skipped):
            skipped.add(d)
            continue
        if d in extra_dirs:
            entries = extra_dirs[d]
        elif di in dead:
            continue
        else:
            entries = base.entries_of(di)
        kept = [e for e in entries if keep_entry(d, e, excluder)]
        names = {n for n, s, _ in kept if s == -1}
        for n, s, _ in entries:
            if s == -1 and n not in names:
                skipped.add(os.path.join(d, n))
        records.append((d, base.dir_mtime[di], kept))
    have = {r[0] for r in records}
    relist = [d for d in extra_dirs if d not in have and d not in skipped
              and not any(under(d, s) for s in skipped)]
    return records, relist


def scan(roots, excluder, mounts=None, old=None, progress=None, stop=None):
    """Walk roots depth first. Folders whose mtime is unchanged since `old` (a Base) are reused
    without listing them. Returns (records, unreadable folders, changed)."""
    mounts = read_mounts() if mounts is None else mounts
    old_index = old.dir_index() if old is not None else {}
    records, errors = [], []
    changed = old is None
    files = 0
    last = time.monotonic()
    for root in roots:
        if excluder.skip_path(root):
            continue
        stack = [root]
        while stack:
            if stop is not None and stop.is_set():
                raise ScanAborted()
            d = stack.pop()
            fstype = mounts.get(d)
            if fstype is not None and fs_excluded(fstype):
                log.debug('skipping %s (%s)', d, fstype)
                continue
            try:
                st = os.stat(d, follow_symlinks=False)
            except OSError:
                errors.append(d)
                continue
            if not stat.S_ISDIR(st.st_mode):
                continue
            oi = old_index.get(d)
            if oi is not None and old.dir_mtime[oi] == st.st_mtime_ns:
                # reused without listing; the exclusions may be newer than the listing
                entries = [e for e in old.entries_of(oi) if keep_entry(d, e, excluder)]
                subs = [os.path.join(d, name) for name, size, _ in entries if size == -1]
            else:
                changed = True
                try:
                    entries, names = list_dir(d, excluder)
                except OSError as e:
                    log.debug('cannot list %s: %s', d, e)
                    errors.append(d)
                    continue
                subs = [os.path.join(d, name) for name in names]
            # Folder times have a coarse resolution: a change in the same tick as the listing
            # would leave the time unchanged, so a folder this recent is not trusted next time.
            mtime = 0 if st.st_mtime_ns >= time.time_ns() - RACY_NS else st.st_mtime_ns
            records.append((d, mtime, entries))
            files += len(entries)
            stack.extend(reversed(subs))
            if progress is not None and time.monotonic() - last >= PROGRESS_EVERY:
                last = time.monotonic()
                progress(len(records), files)
    if old is not None and len(records) != len(old.dirs):
        changed = True
    return records, errors, changed


# ---------------------------------------------------------------- queries
#
# A query is a list of clauses (AND); a clause is a list of terms (OR), possibly negated.
# Over the base every clause yields a mask: bytes with one 0/1 per entry. Clauses whose terms
# need only the name are compiled together into one list comprehension over the lower-case
# names (literals enter the generated code only through repr(), patterns as named arguments);
# path terms are worked out per folder first. Masks are combined as big integers. Overlay
# entries are tested with Term.match.

class QueryError(ValueError):
    pass


class Term:
    kind = 'name'               # 'name': an expression over s; 'path': a mask of its own

    def expr(self, env, k):
        """Expression for one entry name s; may add patterns to env (names end with k)."""
        raise NotImplementedError


class NameTerm(Term):
    def __init__(self, s):
        self.s = s

    def expr(self, env, k):
        return '%r in s' % self.s

    def match(self, low, dir_slash):
        return self.s in low


class AffixTerm(Term):
    """A wildcard pattern that is only a prefix, a suffix or both (report*, *.pdf, a*z)."""

    def __init__(self, head, tail):
        self.head, self.tail = head, tail

    def expr(self, env, k):
        parts = []
        if self.head:
            parts.append('s.startswith(%r)' % self.head)
        if self.tail:
            parts.append('s.endswith(%r)' % self.tail)
        if self.head and self.tail:
            parts.append('len(s) >= %d' % (len(self.head) + len(self.tail)))
        return ' and '.join(parts) or 'True'

    def match(self, low, dir_slash):
        return (low.startswith(self.head) and low.endswith(self.tail)
                and len(low) >= len(self.head) + len(self.tail))


try:
    import re._parser as _sre_parse     # Python 3.11+
except ImportError:                     # pragma: no cover - older Pythons
    import sre_parse as _sre_parse


def required_literal(pattern, flags=0):
    """A lower-case substring every match must contain, or ''. Taken from the top level of the
    pattern only; the letters i and s are left out because case-insensitive matching also lets
    them match characters whose lower case is different (U+0131, U+0130, U+017F)."""
    try:
        parsed = _sre_parse.parse(pattern, flags)
        literal = getattr(_sre_parse, 'LITERAL', None) or _sre_parse.LITERAL
    except Exception:
        return ''
    runs, cur = [], []
    try:
        items = list(parsed)
    except Exception:
        return ''
    for op, arg in items:
        if op == literal:
            cur.append(chr(arg).lower())
        else:
            runs.append(''.join(cur))
            cur = []
    runs.append(''.join(cur))
    best = ''
    for run in runs:
        for piece in re.split('[is]', run):
            if len(piece) > len(best):
                best = piece
    return best if len(best) >= 2 else ''


class PatternTerm(Term):
    """Other wildcards (whole name) or a regular expression (anywhere in the name)."""

    def __init__(self, rx, hint=''):
        self.rx = rx
        self.hint = hint if hint is not None else ''

    def expr(self, env, k):
        env['R%d' % k] = self.rx.search
        if self.hint:
            return '%r in s and R%d(s) is not None' % (self.hint, k)
        return 'R%d(s) is not None' % k

    def match(self, low, dir_slash):
        return self.rx.search(low) is not None


class ExtTerm(Term):
    def __init__(self, exts):
        self.suffixes = tuple('.' + e for e in exts)

    def expr(self, env, k):
        return 's.endswith(%r)' % (self.suffixes,)

    def match(self, low, dir_slash):
        return low.endswith(self.suffixes)


def _entries_of_dirs(base, dir_mask):
    """Entry numbers of the folders set in dir_mask (an iterator)."""
    order, start = base.orders['path'], base.dir_start
    return itertools.chain.from_iterable(order[start[d]:start[d + 1]]
                                         for d in itertools.compress(range(len(base.dirs)), dir_mask))


def _count_dir_entries(base, dir_mask):
    start = base.dir_start
    return sum(start[d + 1] - start[d] for d in itertools.compress(range(len(base.dirs)), dir_mask))


class PathTerm(Term):
    """Substring of the whole lower-case path; with rx, a wildcard pattern for the whole path."""
    kind = 'path'

    def __init__(self, s, rx=None):
        self.s = s
        self.rx = rx

    def mask(self, base):
        n = base.n
        ds = base.dirs_slash
        if self.rx is not None:
            m = self.rx.match
            return bytes(m(d + s) is not None for d, s in zip(map(ds.__getitem__, base.file_dir), base.low))
        s = self.s
        out = bytearray(n)
        if '/' not in s:
            out = bytearray(compile_names([Clause([NameTerm(s)])])(base.low))
        hit = bytearray(map(str.__contains__, ds, itertools.repeat(s)))
        if _count_dir_entries(base, hit) * 4 < n:
            _consume(map(out.__setitem__, _entries_of_dirs(base, hit), itertools.repeat(1)))
        else:
            out = bytearray(and_masks(n, [bytes(out), bytes(map(hit.__getitem__, base.file_dir))], ors=2))
        if '/' in s:
            cut = s.rindex('/') + 1
            head, tail = s[:cut], s[cut:]
            ends = bytearray(map(str.endswith, ds, itertools.repeat(head)))
            low = base.low
            if not tail:
                _consume(map(out.__setitem__, _entries_of_dirs(base, ends), itertools.repeat(1)))
            elif _count_dir_entries(base, ends) * 4 < n:
                for i in _entries_of_dirs(base, ends):
                    if low[i].startswith(tail):
                        out[i] = 1
            else:
                starts = bytes(map(str.startswith, low, itertools.repeat(tail)))
                in_dirs = bytes(map(ends.__getitem__, base.file_dir))
                both = and_masks(n, [starts, in_dirs])
                out = bytearray(and_masks(n, [bytes(out), both], ors=2))
        return bytes(out)

    def match(self, low, dir_slash):
        full = dir_slash + low
        if self.rx is not None:
            return self.rx.match(full) is not None
        return self.s in full


class Clause:
    """Alternatives joined by |, possibly negated with a leading !."""

    def __init__(self, alts, negate=False):
        self.alts = alts
        self.negate = negate

    @property
    def names_only(self):
        return all(t.kind == 'name' for t in self.alts)

    def match(self, low, dir_slash):
        hit = any(t.match(low, dir_slash) for t in self.alts)
        return not hit if self.negate else hit


TOKEN_RE = re.compile(r'(?:[^\s"]+|"[^"]*")+')


def _compile(pattern, flags=re.IGNORECASE):
    try:
        return re.compile(pattern, flags)
    except re.error as e:
        raise QueryError(text('bad_regex', error=e))


def _wild(s):
    return any(c in s for c in '*?[')


def wildcard_term(low):
    """Wildcards matched against the whole name; plain prefix/suffix forms avoid a regex."""
    if '?' not in low and '[' not in low:
        parts = low.split('*')
        if len(parts) == 2:
            return AffixTerm(parts[0], parts[1])
        if len(parts) == 3 and not parts[0] and not parts[2]:
            return NameTerm(parts[1])
    pieces = [x for p in re.split(r'\[[^\]]*\]|[*?]', low) for x in re.split('[is]', p)]
    hint = max(pieces, key=len) if pieces else ''
    return PatternTerm(_compile(r'\A' + fnmatch.translate(low)), hint if len(hint) >= 2 else '')


def regex_term(pattern):
    rx = _compile(pattern)
    return PatternTerm(rx, required_literal(pattern, re.IGNORECASE))


def parse_term(t):
    """One alternative: ext:, path:, regex:, a path (contains /), wildcards, or a name part."""
    low = t.lower()
    if low.startswith('ext:'):
        exts = [e.strip().lstrip('.').lower() for e in re.split(r'[;,]', t[4:]) if e.strip().lstrip('.')]
        return ExtTerm(exts) if exts else None
    if low.startswith('regex:'):
        return regex_term(t[6:]) if t[6:] else None
    if low.startswith('path:'):
        s = low[5:]
        if not s:
            return None
    elif '/' in low:
        s = low
    elif _wild(low):
        return wildcard_term(low)
    else:
        return NameTerm(low)
    if _wild(s):
        return PathTerm(s, _compile(fnmatch.translate(s if s.startswith('/') else '*' + s)))
    return PathTerm(s)


def split_tokens(q):
    return TOKEN_RE.findall((q or '').strip())


def parse_token(tok):
    negate = tok.startswith('!') and len(tok) > 1
    if negate:
        tok = tok[1:]
    parts = [tok] if tok.lower().startswith('regex:') else tok.split('|')
    alts = []
    for p in parts:
        p = p.replace('"', '')
        if p:
            t = parse_term(p)
            if t is not None:
                alts.append(t)
    return Clause(alts, negate) if alts else None


def parse_query(q, regex=False):
    """[Clause]; an empty list matches everything. With regex the whole text is one regular
    expression matched against names."""
    q = (q or '').strip()
    if not q:
        return []
    if regex:
        return [Clause([regex_term(q)])]
    return [c for c in map(parse_token, split_tokens(q)) if c is not None]


def compile_names(clauses):
    """function(names) -> list of truth values, for clauses whose terms need only the name."""
    env = {}
    exprs = []
    k = 0
    for c in clauses:
        alts = []
        for t in c.alts:
            alts.append('(%s)' % t.expr(env, k))
            k += 1
        e = ' or '.join(alts)
        exprs.append('not (%s)' % e if c.negate else '(%s)' % e)
    cond = ' and '.join(exprs) or 'True'
    args = ''.join(', ' + a for a in sorted(env))
    fn = eval(compile('lambda L%s: [%s for s in L]' % (args, cond), '<query>', 'eval'),
              {'__builtins__': {'len': len}})
    return lambda names: fn(names, **env)


# ---------------------------------------------------------------- search

SMALL_SORT = 64                 # sort matches by rank when fewer than n / SMALL_SORT
NARROW_LIMIT = 16               # search within the last result when it has fewer than n / NARROW_LIMIT


def _consume(it):
    collections.deque(it, maxlen=0)


def and_masks(n, masks, ors=0):
    """AND of 0/1 masks (bytes of length n) as big integers; with ors, the first `ors` masks are
    first ORed together and the result ANDed with the rest."""
    if ors:
        acc = 0
        for m in masks[:ors]:
            acc |= int.from_bytes(m, 'little')
        masks = masks[ors:]
    else:
        acc = int.from_bytes(masks[0], 'little')
        masks = masks[1:]
    for m in masks:
        acc &= int.from_bytes(m, 'little')
    return acc.to_bytes(n, 'little')


def not_mask(n, m):
    ones = int.from_bytes(b'\1' * n, 'little')
    return (ones ^ int.from_bytes(m, 'little')).to_bytes(n, 'little')


def clause_mask(base, c):
    n = base.n
    masks = [t.mask(base) for t in c.alts if t.kind == 'path']
    names = [t for t in c.alts if t.kind != 'path']
    if names:
        masks.append(bytes(compile_names([Clause(names)])(base.low)))
    m = masks[0] if len(masks) == 1 else and_masks(n, masks, ors=len(masks))
    return not_mask(n, m) if c.negate else m


def _lead(clauses):
    """The plain positive name word to scan first (the longest), or None."""
    words = [c for c in clauses if not c.negate and len(c.alts) == 1 and type(c.alts[0]) is NameTerm]
    return max(words, key=lambda c: len(c.alts[0].s)) if words else None


def positions(mask, count=None, n=None):
    """Entry numbers set in a 0/1 mask, ascending."""
    count = mask.count(1) if count is None else count
    if count * 32 < len(mask):
        out = []
        add, find = out.append, mask.find
        i = find(1)
        while i >= 0:
            add(i)
            i = find(1, i + 1)
        return out
    return list(itertools.compress(range(len(mask)), mask))


def match_mask(base, clauses):
    """0/1 mask of the matching entries, or None for all. Name conditions are tested in one
    pass; when path conditions are present and a plain word keeps few entries, the path
    conditions are tested on those entries only."""
    if not clauses:
        return None
    n = base.n
    lead = _lead(clauses) if any(not c.names_only for c in clauses) else None
    if lead is not None:
        first = bytes(compile_names([lead])(base.low))
        k = first.count(1)
        if k * SMALL_SORT < n:
            return match_within(base, [c for c in clauses if c is not lead], positions(first, k))
    named = [c for c in clauses if c.names_only]
    masks = [bytes(compile_names(named)(base.low))] if named else []
    masks.extend(clause_mask(base, c) for c in clauses if not c.names_only)
    return masks[0] if len(masks) == 1 else and_masks(base.n, masks)


def match_within(base, clauses, within):
    """Mask of the entries in `within` (entry numbers) that match."""
    low, ds, fd = base.low, base.dirs_slash, base.file_dir
    named = [c for c in clauses if c.names_only]
    other = [c for c in clauses if not c.names_only]
    pos = within
    if named:
        pos = list(itertools.compress(pos, compile_names(named)(map(low.__getitem__, pos))))
    if other:
        pos = [i for i in pos if all(c.match(low[i], ds[fd[i]]) for c in other)]
    mask = bytearray(base.n)
    _consume(map(mask.__setitem__, pos, itertools.repeat(1)))
    return bytes(mask)


class LazyRefs:
    """Entry numbers produced on demand from an iterator; the length is known in advance."""

    def __init__(self, it, count):
        self._it = it
        self._items = array.array('I')
        self._count = count

    def __len__(self):
        return self._count

    def _fill(self, k):
        need = k + 1 - len(self._items)
        if need > 0:
            self._items.extend(itertools.islice(self._it, max(need, 4096)))

    def __getitem__(self, k):
        if k < 0:
            k += self._count
        if not 0 <= k < self._count:
            raise IndexError(k)
        self._fill(k)
        return self._items[k]

    def __iter__(self):
        self._fill(self._count - 1)
        return iter(self._items)


def order_mask(base, mask, sort, desc, tomb=None):
    """Entry numbers of the mask (None: all) in the requested order, as a LazyRefs."""
    n = base.n
    if tomb is not None and any_set(tomb):
        live = not_mask(n, bytes(tomb))
        mask = live if mask is None else and_masks(n, [mask, live])
    count = n if mask is None else mask.count(1)
    if mask is None:
        if sort == 'mtime':
            it = iter(range(n)) if desc else reversed(range(n))
        else:
            order = base.orders[sort]
            it = reversed(order) if desc else iter(order)
        return LazyRefs(it, count)
    if sort == 'mtime':
        rng = range(n)
        it = itertools.compress(rng, mask) if desc else itertools.compress(reversed(rng), reversed(mask))
        return LazyRefs(it, count)
    if count * SMALL_SORT < n:
        pos = sorted(positions(mask, count), key=base.ranks[sort].__getitem__, reverse=desc)
        return LazyRefs(iter(pos), count)
    order = base.orders[sort]
    seq = reversed(order) if desc else order
    return LazyRefs(itertools.compress(seq, map(mask.__getitem__, reversed(order) if desc else order)), count)


def any_set(b):
    return b.find(1) >= 0


def search_base(base, clauses, sort=DEFAULT_SORT, desc=True, tomb=None):
    """Matching entry numbers of base in the requested order (an array)."""
    return array.array('I', order_mask(base, match_mask(base, clauses), sort, desc, tomb))


def match_positions(base, clauses):
    """Matching entry numbers, newest first."""
    m = match_mask(base, clauses)
    return list(range(base.n)) if m is None else list(itertools.compress(range(base.n), m))


def narrows(prev_tokens, tokens):
    """True when every match of tokens is also a match of prev_tokens, judged from the text:
    tokens only add words, or extend the last word of a plain name or path part."""
    if not prev_tokens or len(tokens) < len(prev_tokens):
        return False
    if tokens[:len(prev_tokens) - 1] != prev_tokens[:-1]:
        return False
    old, new = prev_tokens[-1], tokens[len(prev_tokens) - 1]
    if old == new:
        return True
    if not new.startswith(old):
        return False
    a, b = parse_token(old), parse_token(new)
    if a is None or b is None or a.negate or b.negate or len(a.alts) != 1 or len(b.alts) != 1:
        return False
    ta, tb = a.alts[0], b.alts[0]
    if type(ta) is NameTerm and type(tb) is NameTerm:
        return ta.s in tb.s
    if type(ta) is PathTerm and type(tb) is PathTerm and ta.rx is None and tb.rx is None:
        return ta.s in tb.s
    return False


class Result:
    """Search result: refs >= 0 are base entries, refs < 0 are overlay entries (-1 - j)."""

    def __init__(self, base, extra, refs, total_ms):
        self.base = base
        self.extra = extra
        self.refs = refs
        self.ms = total_ms

    def __len__(self):
        return len(self.refs)

    def row(self, k):
        """(name, folder, size, mtime); size is -1 for a folder."""
        r = self.refs[k]
        if r >= 0:
            b = self.base
            return b.name(r), b.dirs[b.file_dir[r]], b.sizes[r], b.mtimes[r]
        e = self.extra[-1 - r]
        return e.name, e.dir, e.size, e.mtime

    def path(self, k):
        name, d, _, _ = self.row(k)
        return os.path.join(d, name)


ExtraEntry = collections.namedtuple('ExtraEntry', 'dir name low size mtime dir_slash dir_key')


def _extra_key(e, sort):
    if sort == 'mtime':
        return e.mtime
    if sort == 'size':
        return e.size
    if sort == 'name':
        return e.low
    return (e.dir_key, e.low)


def merge_extra(base, ordered, extra, hits, sort, desc):
    """Insert overlay hits (indices into extra) into the ordered base result."""
    if not hits:
        return ordered
    refs = list(ordered)
    hits = sorted(hits, key=lambda j: _extra_key(extra[j], sort), reverse=desc)
    keys_cache = {}

    def key_at(pos):
        r = refs[pos]
        k = keys_cache.get(r)
        if k is None:
            k = keys_cache[r] = (base.sort_key(r, sort) if r >= 0 else _extra_key(extra[-1 - r], sort))
        return k

    lo = 0
    for j in hits:
        k = _extra_key(extra[j], sort)
        hi = len(refs)
        a = lo
        while a < hi:
            mid = (a + hi) // 2
            km = key_at(mid)
            if (km >= k) if desc else (km <= k):
                a = mid + 1
            else:
                hi = mid
        refs.insert(a, -1 - j)
        lo = a + 1
    return refs


# ---------------------------------------------------------------- the live index

class Index:
    """The index in use: a Base, an overlay of changes, a cache file, background refresh."""

    def __init__(self, config=None, cache_path=CACHE_FILE, mounts=None):
        self.config = config or Config()
        self.cache_path = cache_path
        self.mounts = mounts
        self.lock = threading.RLock()
        self.base = empty_base()
        self._reset_overlay()
        self.state = 'empty'            # empty, ready, scanning
        self.progress = (0, 0)
        self.unreadable = []
        self.unreadable_count = 0
        self.scanned_at = None
        self.last_scan_seconds = None
        self.touched = None             # folders changed while a refresh runs
        self.on_change = None           # called (without arguments) after the index changed
        self.watcher = None

    def _reset_overlay(self):
        self.generation = getattr(self, 'generation', 0) + 1
        self.last = None                # (generation, tokens, regex, positions) of the last search
        self.tomb = bytearray(self.base.n)
        self.dead = set()               # base folder numbers whose entries are tombstoned
        self.extra_dirs = {}            # folder -> [(name, size, mtime)] (current listing)
        self.extra = []                 # flattened ExtraEntry list

    # loading and refreshing

    def load(self):
        """Read the cache; True when the index is usable at once."""
        t = time.monotonic()
        base, meta = load_base(self.cache_path, self.config.signature())
        if base is None:
            return False
        with self.lock:
            self.base = base
            self._reset_overlay()
            self.state = 'ready'
            self.scanned_at = meta.get('scanned_at')
            self.unreadable_count = meta.get('unreadable', 0)
        log.info('cache loaded: %d entries in %.2fs', base.n, time.monotonic() - t)
        return True

    def refresh(self, full=False, stop=None):
        """Rescan (reusing unchanged folders unless full), rebuild, write the cache."""
        with self.lock:
            if self.state == 'scanning':
                return False
            self.state = 'scanning'
            self.progress = (0, 0)
            self.touched = set()
            old = None if full or self.base.n == 0 and not self.base.dirs else self.base
        t = time.monotonic()
        try:
            def progress(dirs, files):
                self.progress = (dirs, files)
                self._notify()
            records, errors, changed = scan(self.config.resolved_roots(), self.config.excluder(),
                                            self.mounts, old, progress, stop)
            if changed:
                base = build_base(records)
                del records
                meta = {'scanned_at': int(time.time()), 'unreadable': len(errors)}
                try:
                    save_base(base, self.cache_path, self.config.signature(), meta)
                except OSError as e:
                    log.warning('cannot write cache %s: %s', self.cache_path, e)
            with self.lock:
                if changed:
                    self.base = base
                    self._reset_overlay()
                self.unreadable = errors[:UNREADABLE_SHOWN]
                self.unreadable_count = len(errors)
                self.scanned_at = int(time.time())
                self.last_scan_seconds = round(time.monotonic() - t, 1)
                touched, self.touched = self.touched, None
                self.state = 'ready'
            if changed and touched:
                self.apply_changes(touched)
            log.info('refresh done in %.1fs: %d entries, %d unreadable, changed=%s',
                     time.monotonic() - t, self.base.n, len(errors), changed)
            return True
        except ScanAborted:
            log.info('refresh stopped')
            return False
        finally:
            with self.lock:
                if self.state == 'scanning':
                    self.state = 'ready' if self.base.n or self.scanned_at else 'empty'
                self.touched = None
            self._notify()

    def reconfigure(self, config, stop=None):
        """Use a new index scope. When only exclusions were added (same folders, same hidden
        setting) the excluded entries are dropped from the index without touching the disk;
        otherwise the folders are rescanned, from scratch when hidden entries or dropped
        exclusions need folders listed again. Returns 'same', 'pruned' or 'rescanned' (or
        'stopped' when stop was set)."""
        with self.lock:
            old = self.config
            self.config = config
            ready = self.state == 'ready'
        same_roots = old.resolved_roots() == config.resolved_roots()
        added_only = set(old.exclude) <= set(config.exclude)
        if same_roots and old.hidden == config.hidden and added_only and ready:
            if set(old.exclude) == set(config.exclude):
                if old.signature() != config.signature():
                    self._save_current()
                return 'same'
            self._prune()
            return 'pruned'
        full = (config.hidden and not old.hidden) or not added_only
        done = self.refresh_and_watch(full=full, stop=stop)
        return 'rescanned' if done else 'stopped'

    def _save_current(self):
        with self.lock:
            base, meta = self.base, {'scanned_at': self.scanned_at, 'unreadable': self.unreadable_count}
        try:
            save_base(base, self.cache_path, self.config.signature(), meta)
        except OSError as e:
            log.warning('cannot write cache %s: %s', self.cache_path, e)

    def _prune(self):
        """Drop excluded entries; the new base is built outside the lock so searches go on."""
        t = time.monotonic()
        with self.lock:
            old, extra_dirs, dead = self.base, dict(self.extra_dirs), set(self.dead)
            roots, exc = self.config.resolved_roots(), self.config.excluder()
        records, relist = prune_records(old, extra_dirs, dead, roots, exc)
        base = build_base(records)
        del records
        with self.lock:
            # folders that changed while the base was built are listed again below
            later = [d for d, v in self.extra_dirs.items() if extra_dirs.get(d) is not v]
            self.base = base
            self._reset_overlay()
        relist = sorted(set(relist) | set(later))
        self._save_current()
        if relist:
            self.apply_changes(relist)
        if self.watcher is not None:
            self.watcher.sync(self.known_dirs())
        log.info('exclusions applied in %.2fs: %d entries', time.monotonic() - t, self.base.n)
        self._notify()

    def _notify(self):
        cb = self.on_change
        if cb is not None:
            try:
                cb()
            except Exception:
                log.exception('change callback failed')

    # overlay

    def known_dirs(self):
        with self.lock:
            out = [d for i, d in enumerate(self.base.dirs) if i not in self.dead]
            out.extend(self.extra_dirs)
            return out

    def _children(self, d):
        """Subfolder paths of d as the index has them now."""
        if d in self.extra_dirs:
            return {os.path.join(d, n) for n, s, _ in self.extra_dirs[d] if s == -1}
        di = self.base.dir_index().get(d)
        if di is None or di in self.dead:
            return set()
        return {os.path.join(d, n) for n, s, _ in self.base.entries_of(di) if s == -1}

    def _drop_dir(self, d):
        """Tombstone base entries of folder d (only its own entries)."""
        di = self.base.dir_index().get(d)
        if di is not None and di not in self.dead:
            self.dead.add(di)
            _consume(map(self.tomb.__setitem__, self.base.dir_entries(di), itertools.repeat(1)))

    def _remove_tree(self, d):
        prefix = d.rstrip('/') + '/'
        for i, path in enumerate(self.base.dirs):
            if path == d or path.startswith(prefix):
                self._drop_dir(path)
        for path in [p for p in self.extra_dirs if p == d or p.startswith(prefix)]:
            del self.extra_dirs[path]
        if self.watcher is not None:
            self.watcher.remove_tree(d)

    def _covered(self, d):
        roots = self.config.resolved_roots()
        exc = self.config.excluder()
        if not any(d == r or d.startswith(r.rstrip('/') + '/') for r in roots):
            return False
        if exc.skip_path(d):
            return False
        for r in roots:
            if d.startswith(r.rstrip('/') + '/'):
                rel = d[len(r.rstrip('/')) + 1:].split('/')
                if any(exc.skip_name(p) for p in rel):
                    return False
        return True

    def apply_changes(self, dirs):
        """Re-list each changed folder; add or remove subtrees whose folders appeared or vanished."""
        mounts = read_mounts() if self.mounts is None else self.mounts
        exc = self.config.excluder()
        added = []
        with self.lock:
            if self.touched is not None:
                self.touched.update(dirs)
            for d in sorted(set(dirs), key=len):
                if not self._covered(d):
                    continue
                try:
                    entries, names = list_dir(d, exc)
                except OSError:
                    self._remove_tree(d)
                    continue
                before = self._children(d)
                self._drop_dir(d)
                self.extra_dirs[d] = entries
                now = {os.path.join(d, n) for n in names}
                for gone in before - now:
                    self._remove_tree(gone)
                for new in sorted(now - before):
                    records, _, _ = scan([new], exc, mounts)
                    for path, _, ents in records:
                        self._drop_dir(path)
                        self.extra_dirs[path] = ents
                        added.append(path)
            self._flatten()
            self.generation += 1
            big = len(self.extra) > EXTRA_LIMIT
        if self.watcher is not None:
            for path in added:
                self.watcher.add(path)
        self._notify()
        return big

    def _flatten(self):
        out = []
        for d, entries in self.extra_dirs.items():
            dl = d.lower()
            ds = dl if dl.endswith('/') else dl + '/'
            dk = path_key(dl)
            for name, size, mtime in entries:
                out.append(ExtraEntry(d, name, name.lower(), size, mtime, ds, dk))
        self.extra = out

    # search

    def search(self, query, sort=DEFAULT_SORT, desc=True, regex=False):
        """Result for query; raises QueryError for a bad pattern. While typing, a query that only
        narrows the previous one is matched within the previous result when that is small."""
        if sort not in SORTS:
            sort = DEFAULT_SORT
        t = time.monotonic()
        clauses = parse_query(query, regex)
        tokens = [query.strip()] if regex else split_tokens(query)
        with self.lock:
            base, tomb, extra, gen, last = self.base, self.tomb, self.extra, self.generation, self.last
        if (clauses and not regex and last is not None and last[0] == gen and last[1] is base
                and last[4] * NARROW_LIMIT < base.n and narrows(last[2], tokens)):
            mask = match_within(base, clauses, positions(last[3], last[4]))
        else:
            mask = match_mask(base, clauses)
        with self.lock:
            if self.generation == gen and mask is not None and not regex:
                self.last = (gen, base, tokens, mask, mask.count(1))
        ordered = order_mask(base, mask, sort, desc, tomb)
        if extra:
            hits = [j for j, e in enumerate(extra) if all(c.match(e.low, e.dir_slash) for c in clauses)]
            ordered = merge_extra(base, ordered, extra, hits, sort, desc)
        return Result(base, extra, ordered, round((time.monotonic() - t) * 1000, 1))

    def count(self):
        with self.lock:
            return self.base.n - self.tomb.count(1) + len(self.extra)

    def status(self, lang=None):
        with self.lock:
            st = {'state': self.state, 'entries': self.count(), 'progress': list(self.progress),
                  'unreadable': list(self.unreadable), 'unreadable_count': self.unreadable_count,
                  'scanned_at': self.scanned_at, 'version': VERSION}
        w = self.watcher
        st['watch'] = 'off' if w is None else ('limited' if w.limited else 'on')
        return st

    # watching

    def start_watching(self):
        """Watch every indexed folder with inotify in the background; False when unavailable."""
        if self.watcher is None:
            try:
                self.watcher = Watcher(self._on_dirty)
            except OSError as e:
                log.warning('inotify unavailable: %s', e)
                return False
        threading.Thread(target=self.watcher.sync, args=(self.known_dirs(),), daemon=True).start()
        return True

    def _on_dirty(self, dirs, overflow):
        if overflow:
            log.info('inotify queue overflow; full refresh')
            threading.Thread(target=self.refresh_and_watch, daemon=True).start()
            return
        if self.apply_changes(dirs):
            threading.Thread(target=self.refresh_and_watch, daemon=True).start()

    def refresh_and_watch(self, full=False, stop=None):
        done = self.refresh(full, stop)
        if self.watcher is not None:
            self.watcher.sync(self.known_dirs())
        return done

    def close(self):
        if self.watcher is not None:
            self.watcher.close()
            self.watcher = None


# ---------------------------------------------------------------- inotify

IN_MODIFY = 0x2
IN_ATTRIB = 0x4
IN_CLOSE_WRITE = 0x8
IN_MOVED_FROM = 0x40
IN_MOVED_TO = 0x80
IN_CREATE = 0x100
IN_DELETE = 0x200
IN_DELETE_SELF = 0x400
IN_MOVE_SELF = 0x800
IN_Q_OVERFLOW = 0x4000
IN_IGNORED = 0x8000
IN_ONLYDIR = 0x1000000
IN_DONT_FOLLOW = 0x2000000
IN_EXCL_UNLINK = 0x4000000
IN_NONBLOCK = 0o4000
IN_CLOEXEC = 0o2000000
WATCH_MASK = (IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE | IN_DELETE_SELF
              | IN_MOVE_SELF | IN_ONLYDIR | IN_DONT_FOLLOW | IN_EXCL_UNLINK)
EVENT = struct.Struct('iIII')
DEBOUNCE = 0.3                  # quiet time before changed folders are handed over
DEBOUNCE_MAX = 1.5              # longest delay under a steady stream of events


class Watcher:
    """inotify on every indexed folder (ctypes). Changed folders are handed to on_dirty(set,
    overflow) from the watcher thread. When the system watch limit is reached, `limited` is set
    and the rest of the folders are left to periodic rescans."""

    def __init__(self, on_dirty):
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.inotify_init1.argtypes = [ctypes.c_int]
        self.libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.libc.inotify_rm_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        fd = self.libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if fd < 0:
            e = ctypes.get_errno()
            raise OSError(e, os.strerror(e))
        self.fd = fd
        self.on_dirty = on_dirty
        self.lock = threading.Lock()
        self.wd_path = {}
        self.path_wd = {}
        self.limited = False
        self.closed = False
        self.thread = threading.Thread(target=self._run, name='inotify', daemon=True)
        self.thread.start()

    def add(self, path):
        with self.lock:
            if self.closed or path in self.path_wd:
                return True
            wd = self.libc.inotify_add_watch(self.fd, encode_name(path), WATCH_MASK)
            if wd < 0:
                e = ctypes.get_errno()
                if e == errno.ENOSPC:
                    if not self.limited:
                        log.warning('inotify watch limit reached after %d folders', len(self.path_wd))
                    self.limited = True
                elif e not in (errno.ENOENT, errno.ENOTDIR, errno.EACCES):
                    log.debug('inotify_add_watch %s: %s', path, os.strerror(e))
                return False
            old = self.wd_path.get(wd)
            if old is not None and old != path:
                self.path_wd.pop(old, None)
            self.wd_path[wd] = path
            self.path_wd[path] = wd
            return True

    def remove_tree(self, path):
        prefix = path.rstrip('/') + '/'
        with self.lock:
            for p in [p for p in self.path_wd if p == path or p.startswith(prefix)]:
                wd = self.path_wd.pop(p)
                self.wd_path.pop(wd, None)
                if not self.closed:
                    self.libc.inotify_rm_watch(self.fd, wd)

    def sync(self, paths):
        """Watch exactly these folders."""
        want = set(paths)
        with self.lock:
            stale = [p for p in self.path_wd if p not in want]
        for p in stale:
            with self.lock:
                wd = self.path_wd.pop(p, None)
                if wd is not None:
                    self.wd_path.pop(wd, None)
                    if not self.closed:
                        self.libc.inotify_rm_watch(self.fd, wd)
        self.limited = False
        for p in paths:
            if self.closed:
                return
            if not self.add(p) and self.limited:
                return
        log.info('watching %d folders', len(self.path_wd))

    def watched(self):
        with self.lock:
            return len(self.path_wd)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self.thread.join(timeout=2)
        os.close(self.fd)

    def _run(self):
        dirty, overflow = set(), False
        first = last = 0.0
        while not self.closed:
            try:
                r, _, _ = select.select([self.fd], [], [], 0.1)
            except (OSError, ValueError):
                return
            now = time.monotonic()
            if r:
                try:
                    data = os.read(self.fd, 65536)
                except BlockingIOError:
                    data = b''
                except OSError:
                    return
                pos = 0
                while pos + EVENT.size <= len(data):
                    wd, mask, _cookie, length = EVENT.unpack_from(data, pos)
                    pos += EVENT.size + length
                    if mask & IN_Q_OVERFLOW:
                        overflow = True
                        continue
                    with self.lock:
                        path = self.wd_path.get(wd)
                        if mask & IN_IGNORED:
                            self.wd_path.pop(wd, None)
                            if path is not None and self.path_wd.get(path) == wd:
                                self.path_wd.pop(path, None)
                            continue
                    if path is None:
                        continue
                    if mask & (IN_DELETE_SELF | IN_MOVE_SELF):
                        parent = os.path.dirname(path)
                        if parent != path:
                            dirty.add(parent)
                        continue
                    dirty.add(path)
                if dirty or overflow:
                    if not first:
                        first = now
                    last = now
            if (dirty or overflow) and (now - last >= DEBOUNCE or now - first >= DEBOUNCE_MAX):
                batch, dirty = dirty, set()
                flag, overflow = overflow, False
                first = last = 0.0
                try:
                    self.on_dirty(batch, flag)
                except Exception:
                    log.exception('handling changes failed')


# ---------------------------------------------------------------- helpers for the interfaces

def setup_logging(level):
    logging.basicConfig(level=level, format=LOG_FORMAT, stream=sys.stderr)


def default_log_level():
    v = os.environ.get('LOG_LEVEL', 'WARNING').upper()
    return v if v in LOG_LEVELS else 'WARNING'


def human_size(size):
    if size < 0:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return ('%d %s' % (size, unit)) if unit == 'B' else ('%.1f %s' % (size, unit))
        size /= 1024.0
    return ''


def human_time(ts):
    try:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return ''

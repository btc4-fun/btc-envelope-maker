"""Stdlib-only tag gate and bounded, process-safe JSONL audit (Linux/POSIX).

Public API
----------
TagLimiter(state_file=None, secret=None, clock=time.time)
    admit(client_ip) -> int: 0 admits, otherwise ceil(seconds until the original
    admission +20). Denied requests do not refresh that admission. Canonical IPv6
    and IPv4-mapped IPv6 aliases share the same per-client quota; no tag is keyed.
    Invalid IP raises ValueError('Invalid client IP'); config/storage/clock errors
    raise TagAccessUnavailable('Tag access temporarily unavailable').
    Defaults: TAG_LOOKUP_STATE_FILE=/var/lib/btc4fun/tag-lookup.sqlite3 and the
    existing CONTACT_SECRET (bytes or UTF-8 str, >=32 bytes, nonblank). Explicit
    arguments override environment values. State paths must be absolute. The
    service-owned private parent directory must already exist. No envfiles read.
    All workers must share the file and stable secret. BEGIN IMMEDIATE commits
    before return, with a 0.5-second busy timeout, <=10000 live HMAC IP rows and
    one persistent high-water clock row. Expiry equality admits; clock rollback
    (including after restart) fails closed until the high-water mark is reached.
    Cleanup happens on admission, not a timer. Only digests/timestamps persist.

TagAudit(log_dir=None, max_bytes=None, backup_count=None)
    record(*, client_ip, method, path, status, duration_ms, headers) -> None.
    Synchronously appends one ASCII-escaped JSON line to tag-access.jsonl; errors
    raise the same fixed TagAccessUnavailable. No body argument is accepted and
    query/fragment suffixes are always removed. Callers supply trusted resolved
    IP provenance and a path, NOT a full URL or a path carrying secret material.
    Unlike limiter state, audit records intentionally retain the client IP.
    Fields: timestamp (Unix seconds), client_ip (45 chars), method (16), path
    (256), status (integer 100..599), duration_ms (finite 0..86400000), headers
    (mapping), headers_truncated (boolean). Each line is bounded to 8192 bytes by
    field budgets. All controls/non-ASCII characters are JSON escaped.
    At most 32 header entries, names <=64 chars, total encoded header budget
    <=4096 bytes. Values are '[REDACTED]' unless an exact value is in
    _SAFE_HEADER_VALUES below or Content-Length is 1..10 ASCII digits. Thus
    credentials/cookies/security tokens, unknown values, UA and referrer values
    never persist. Header names remain diagnostic metadata; do not put secrets
    in names. Overflow entries are omitted and headers_truncated is true.
    Defaults: TAG_AUDIT_DIR=/var/lib/btc4fun/tag-audit,
    TAG_AUDIT_MAX_BYTES=1048576 (8192..104857600),
    TAG_AUDIT_BACKUP_COUNT=5 (0..100). Explicit args override env; integers or
    decimal integer strings accepted, booleans/floats rejected. Absolute log dir
    is created 0700 under an existing trusted parent; files are 0600. Symlinks,
    non-regular files and hardlinks are refused. Keep all ancestor directories
    trusted; these checks are not a sandbox against the service's own UID.
    Workers must share configuration and a local filesystem with flock/SQLite
    locking. A stable .tag-access.lock (never rotate/remove it) serializes size
    checks, deletion, rotation and fsynced appends, with a 0.5-second lock wait.
    .1 is newest backup; oldest is overwritten. Zero backups discards the old
    current file on rotation (NOT unbounded stdlib RotatingFileHandler behavior).
    On the next record, reducing retention deletes excess generations and
    reducing max_bytes deletes oversized generations, including current. Idle
    files are not time-expired. Bound: (backup_count + 1) * max_bytes, plus empty
    lock file. Process-safe rotation is not a crash-atomic multi-file journal;
    I/O failure may have appended a line, so callers must not blindly retry.

Neither constructor performs disk/network I/O. No website limiter is changed.
"""
import hashlib
import fcntl
import hmac
import math
import os
import ipaddress
import json
import re
from pathlib import Path
import sqlite3
import stat
import time
from contextlib import closing

MAX_ENTRIES = 10000


class TagAccessUnavailable(Exception):
    """Admission or audit storage cannot safely complete."""


def _private_open(path, flags):
    fd = os.open(path, flags | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise ValueError
        os.fchmod(fd, 0o600)
        return fd
    except Exception:
        os.close(fd)
        raise


class TagLimiter:
    """admit(client_ip) returns 0 or integer Retry-After seconds; denies do not refresh."""

    def __init__(self, state_file=None, secret=None, clock=time.time):
        try:
            path = os.fspath(state_file if state_file is not None else os.environ.get(
                'TAG_LOOKUP_STATE_FILE', '/var/lib/btc4fun/tag-lookup.sqlite3'))
            key = secret if secret is not None else os.environ.get('CONTACT_SECRET')
            if isinstance(key, str):
                key = key.encode('utf-8')
            if (not isinstance(path, str) or not os.path.isabs(path) or '\0' in path
                    or not isinstance(key, bytes) or len(key) < 32 or not key.strip()
                    or not callable(clock)):
                raise ValueError
            self.state_file, self.secret, self.clock = path, key, clock
        except Exception:
            raise TagAccessUnavailable('Tag access temporarily unavailable') from None

    def admit(self, client_ip):
        try:
            if not isinstance(client_ip, str) or not 1 <= len(client_ip) <= 45 or '%' in client_ip:
                raise ValueError
            address = ipaddress.ip_address(client_ip)
        except ValueError:
            raise ValueError('Invalid client IP') from None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        client_ip = str(address)
        ip_hash = hmac.new(self.secret, b'tag-ip\0' + client_ip.encode(), hashlib.sha256).hexdigest()
        try:
            return self._admit(ip_hash)
        except Exception:
            raise TagAccessUnavailable('Tag access temporarily unavailable') from None

    def _admit(self, ip_hash):
        os.close(_private_open(self.state_file, os.O_RDWR))
        with closing(sqlite3.connect(self.state_file, timeout=0.5)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS tag_admissions ('
                       'ip_hash TEXT PRIMARY KEY, admitted_at REAL NOT NULL) WITHOUT ROWID')
            db.execute('CREATE TABLE IF NOT EXISTS tag_clock ('
                       'id INTEGER PRIMARY KEY CHECK(id = 1), last_seen REAL NOT NULL)')
            now = self.clock()
            if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now) or now < 0:
                raise ValueError
            previous = db.execute('SELECT last_seen FROM tag_clock WHERE id = 1').fetchone()
            if previous is not None and now < previous[0]:
                raise TagAccessUnavailable('Tag access temporarily unavailable')
            db.execute('INSERT OR REPLACE INTO tag_clock VALUES (1, ?)', (now,))
            db.execute('DELETE FROM tag_admissions WHERE admitted_at <= ?', (now - 20,))
            row = db.execute('SELECT admitted_at FROM tag_admissions WHERE ip_hash = ?', (ip_hash,)).fetchone()
            if row is not None:
                return math.ceil(row[0] + 20 - now)
            if db.execute('SELECT count(*) FROM tag_admissions').fetchone()[0] >= MAX_ENTRIES:
                raise TagAccessUnavailable('Tag access temporarily unavailable')
            db.execute('INSERT INTO tag_admissions VALUES (?, ?)', (ip_hash, now))
            return 0


_SAFE_HEADER_VALUES = {
    'content-type': frozenset({'application/json', 'application/x-www-form-urlencoded', 'text/plain'}),
    'accept': frozenset({'application/json', 'text/html', '*/*'}),
    'sec-fetch-mode': frozenset({'navigate', 'same-origin', 'no-cors', 'cors', 'websocket'}),
}


def _audit_headers(headers):
    result, budget, truncated = {}, 0, False
    for index, (name, value) in enumerate(headers.items()):
        if index >= 32:
            truncated = True
            break
        bounded_name = name[:64].lower()[:64]
        safe = (len(name) <= 64 and isinstance(value, str) and len(value) <= 64
                and value in _SAFE_HEADER_VALUES.get(bounded_name, ()))
        if len(name) <= 64 and bounded_name == 'content-length':
            safe = isinstance(value, str) and re.fullmatch(r'[0-9]{1,10}', value) is not None
        value = value if safe else '[REDACTED]'
        cost = len(json.dumps({bounded_name: value}, ensure_ascii=True))
        if budget + cost > 4096:
            truncated = True
            break
        result[bounded_name] = value
        budget += cost
        truncated = truncated or len(name) > 64
    return result, truncated


def _config_integer(value, env, default, low, high):
    if value is None:
        value = os.environ.get(env, str(default))
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,9}', value):
        value = int(value)
    if type(value) is not int or not low <= value <= high:
        raise ValueError
    return value


class TagAudit:
    """record(*, client_ip, method, path, status, duration_ms, headers) appends JSONL."""

    def __init__(self, log_dir=None, max_bytes=None, backup_count=None):
        try:
            path = os.fspath(log_dir if log_dir is not None else os.environ.get(
                'TAG_AUDIT_DIR', '/var/lib/btc4fun/tag-audit'))
            if not isinstance(path, str) or not os.path.isabs(path) or '\0' in path:
                raise ValueError
            self.log_dir = Path(path)
            self.max_bytes = _config_integer(max_bytes, 'TAG_AUDIT_MAX_BYTES', 1048576, 8192, 104857600)
            self.backup_count = _config_integer(backup_count, 'TAG_AUDIT_BACKUP_COUNT', 5, 0, 100)
        except Exception:
            raise TagAccessUnavailable('Tag access temporarily unavailable') from None

    def record(self, *, client_ip, method, path, status, duration_ms, headers):
        try:
            self._record(client_ip, method, path, status, duration_ms, headers)
        except Exception:
            raise TagAccessUnavailable('Tag access temporarily unavailable') from None

    def _record(self, client_ip, method, path, status, duration_ms, headers):
        if (not all(isinstance(value, str) for value in (client_ip, method, path))
                or type(status) is not int or not 100 <= status <= 599
                or isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float))
                or not math.isfinite(duration_ms) or not 0 <= duration_ms <= 86400000):
            raise ValueError
        safe_headers, truncated = _audit_headers(headers)
        row = dict(client_ip=client_ip[:45], method=method[:16],
                   path=path[:256].split('?', 1)[0].split('#', 1)[0], status=status,
                   duration_ms=duration_ms, headers=safe_headers, headers_truncated=truncated,
                   timestamp=time.time())
        data = (json.dumps(row, ensure_ascii=True) + '\n').encode('ascii')
        self.log_dir.mkdir(mode=0o700, exist_ok=True)
        info = self.log_dir.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError
        self.log_dir.chmod(0o700)
        with os.fdopen(_private_open(self.log_dir / '.tag-access.lock', os.O_RDWR), 'rb') as lock:
            deadline = time.monotonic() + 0.5
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TagAccessUnavailable('Tag access temporarily unavailable') from None
                    time.sleep(0.005)
            current = self.log_dir / 'tag-access.jsonl'
            for index in range(101):
                file = current if index == 0 else self.log_dir / f'tag-access.jsonl.{index}'
                try:
                    info = file.lstat()
                except FileNotFoundError:
                    continue
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_uid != os.geteuid()):
                    raise ValueError
                if index > self.backup_count or info.st_size > self.max_bytes:
                    file.unlink()
                else:
                    file.chmod(0o600)
            if current.exists() and current.stat().st_size + len(data) > self.max_bytes:
                for index in range(self.backup_count, 0, -1):
                    source = current if index == 1 else self.log_dir / f'tag-access.jsonl.{index - 1}'
                    if source.exists():
                        source.replace(self.log_dir / f'tag-access.jsonl.{index}')
                if self.backup_count == 0:
                    current.unlink()
            with os.fdopen(_private_open(current, os.O_WRONLY | os.O_APPEND), 'ab') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())

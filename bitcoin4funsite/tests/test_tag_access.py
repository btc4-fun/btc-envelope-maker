"""Offline tag gate/audit proofs using only synthetic scratch state."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing
import sqlite3
import multiprocessing
import time
import json
import stat

PATH = Path(__file__).resolve().parents[1] / 'tag_access.py'
SECRET = b'synthetic-tag-secret-for-offline-tests-only'


def load_module():
    if not PATH.is_file():
        raise AssertionError('tag access implementation missing')
    spec = importlib.util.spec_from_file_location('btc4fun_tag_access', PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def process_admission(path, now, barrier, output):
    module = load_module()
    barrier.wait(timeout=10)
    for attempt in range(5):
        try:
            result = module.TagLimiter(path, SECRET, lambda: now).admit('192.0.2.1')
            output.put(result)
            return
        except module.TagAccessUnavailable:
            if attempt == 4:
                raise


def process_hold_audit_lock(log_dir, ready, output):
    import fcntl
    with open(Path(log_dir) / '.tag-access.lock', 'rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ready.set()
        time.sleep(2)
    output.put('released')


def process_audit(log_dir, max_bytes, backup_count, records, barrier, output):
    module = load_module()
    audit = module.TagAudit(log_dir, max_bytes, backup_count)
    barrier.wait(timeout=10)
    for index in range(records):
        # Busy acquisition is a closed result; retry only in this synthetic stress proof.
        for attempt in range(5):
            try:
                audit.record(client_ip='192.0.2.1', method='GET', path=f'/{os.getpid()}/{index}',
                             status=200, duration_ms=1, headers={'X-Test': 'SYNTHETIC_ROTATION_SECRET'})
                break
            except module.TagAccessUnavailable:
                if attempt == 4:
                    raise
    output.put(records)


class TagAccessContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='tag-access-tests-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / 'tag.sqlite3'
        self.now = [1000.0]
        self.module = load_module()

    def limiter(self, **kwargs):
        return self.module.TagLimiter(kwargs.pop('state_file', self.db),
                                      kwargs.pop('secret', SECRET),
                                      kwargs.pop('clock', lambda: self.now[0]), **kwargs)

    def audit(self, **kwargs):
        return self.module.TagAudit(log_dir=kwargs.pop('log_dir', self.root / 'audit'), **kwargs)

    def record(self, audit=None, **kwargs):
        arguments = dict(client_ip='192.0.2.1', method='GET', path='/tag-inquiry',
                         status=200, duration_ms=1.25, headers={})
        arguments.update(kwargs)
        (audit or self.audit()).record(**arguments)

    def audit_rows(self):
        return [json.loads(line) for file in (self.root / 'audit').glob('tag-access.jsonl*')
                for line in file.read_text().splitlines()]

    def test_smaller_rotation_size_removes_oversized_existing_generations(self):
        audit = self.audit(max_bytes=16384, backup_count=2)
        for _ in range(60):
            self.record(audit, path='/' + 'x' * 250)
        self.assertTrue(any(file.stat().st_size > 8192 for file in audit.log_dir.glob('tag-access.jsonl*')))
        self.record(self.audit(max_bytes=8192, backup_count=2))
        self.assertTrue(all(file.stat().st_size <= 8192 for file in audit.log_dir.glob('tag-access.jsonl*')))

    def test_audit_unicode_expansion_respects_names_and_whole_record_bound(self):
        self.record(client_ip='\U0001f600' * 100, method='\U0001f600' * 100,
                    path='/' + '\U0001f600' * 1000,
                    headers={str(i) + '\u0130' * 100: 'private' for i in range(32)})
        raw = (self.root / 'audit' / 'tag-access.jsonl').read_bytes()
        self.assertLessEqual(len(raw), 8192)
        self.assertTrue(all(len(name) <= 64 for name in json.loads(raw)['headers']))

    def test_audit_lock_timeout_is_fail_closed_and_bounded(self):
        self.record()
        context = multiprocessing.get_context('spawn')
        ready, output = context.Event(), context.Queue()
        worker = context.Process(target=process_hold_audit_lock, args=(str(self.root / 'audit'), ready, output))
        try:
            worker.start()
            self.assertTrue(ready.wait(timeout=5))
            started = time.monotonic()
            with self.assertRaises(self.module.TagAccessUnavailable):
                self.record()
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertEqual(len(self.audit_rows()), 1)
        finally:
            worker.join(timeout=5)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=5)
            worker.close()
            output.close()
            output.join_thread()

    def test_audit_rejects_symlink_directory_and_hardlinked_files(self):
        target = self.root / 'outside'
        target.mkdir()
        link = self.root / 'audit'
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(self.module.TagAccessUnavailable):
            self.record()
        self.assertEqual(list(target.iterdir()), [])
        link.unlink()
        link.mkdir(mode=0o755)
        self.record()
        self.assertEqual(stat.S_IMODE(link.stat().st_mode), 0o700)
        current = link / 'tag-access.jsonl'
        current.unlink()
        private = target / 'private'
        private.write_text('SYNTHETIC_PRIVATE_FILE')
        os.link(private, current)
        with self.assertRaises(self.module.TagAccessUnavailable):
            self.record()
        self.assertEqual(private.read_text(), 'SYNTHETIC_PRIVATE_FILE')
        current.unlink()
        current.symlink_to(private)
        with self.assertRaises(self.module.TagAccessUnavailable):
            self.record()
        self.assertEqual(private.read_text(), 'SYNTHETIC_PRIVATE_FILE')

    def test_audit_prunes_old_backups_when_retention_is_reduced(self):
        audit = self.audit(max_bytes=8192, backup_count=3)
        for index in range(100):
            self.record(audit, path=f'/{index}/' + 'x' * 250)
        self.assertEqual(len(list(audit.log_dir.glob('tag-access.jsonl*'))), 4)
        oldest = (audit.log_dir / 'tag-access.jsonl.3').read_bytes()
        self.assertNotIn(b'"path": "/0/', oldest)
        self.record(self.audit(max_bytes=8192, backup_count=1))
        self.assertEqual(len(list(audit.log_dir.glob('tag-access.jsonl*'))), 2)
        self.record(self.audit(max_bytes=8192, backup_count=0), path='/newest')
        self.assertEqual(len(list(audit.log_dir.glob('tag-access.jsonl*'))), 1)
        self.assertLessEqual((audit.log_dir / 'tag-access.jsonl').stat().st_size, 8192)
        for index in range(50):
            self.record(self.audit(max_bytes=8192, backup_count=0), path='/' + 'z' * 250)
        self.assertEqual(len(list(audit.log_dir.glob('tag-access.jsonl*'))), 1)
        self.assertLessEqual((audit.log_dir / 'tag-access.jsonl').stat().st_size, 8192)

    def test_audit_invalid_fields_fail_closed_without_unbounded_or_private_values(self):
        for kwargs in ({'status': 'SYNTHETIC_SECRET'}, {'status': True}, {'status': 1000},
                       {'duration_ms': float('inf')}, {'duration_ms': float('nan')},
                       {'duration_ms': -1}, {'duration_ms': 86400001},
                       {'method': None}, {'path': None}, {'headers': None},
                       {'headers': {None: 'private'}}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(
                    self.module.TagAccessUnavailable, '^Tag access temporarily unavailable$'):
                self.record(**kwargs)
        self.assertEqual(self.audit_rows(), [])

    def test_multiprocess_rotation_keeps_complete_unique_lines_across_restart(self):
        args = (str(self.root / 'audit'), 8192, 20, 40)
        self.assertEqual(self.workers(process_audit, args, 6), [40] * 6)
        rows = self.audit_rows()
        self.assertEqual(len(rows), 240)
        self.assertEqual(len({row['path'] for row in rows}), 240)
        files = list((self.root / 'audit').glob('tag-access.jsonl*'))
        self.assertGreater(len(files), 1)
        for file in files:
            self.assertLessEqual(file.stat().st_size, 8192)
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
            self.assertNotIn(b'SYNTHETIC_ROTATION_SECRET', file.read_bytes())
        self.assertEqual(self.workers(process_audit, (*args[:3], 1), 1), [1])
        self.assertEqual(len(self.audit_rows()), 241)

    def test_audit_configuration_defaults_env_and_bounds(self):
        with patch.dict(os.environ, {}, clear=True):
            audit = self.module.TagAudit()
            self.assertEqual(str(audit.log_dir), '/var/lib/btc4fun/tag-audit')
            self.assertEqual(audit.max_bytes, 1048576)
            self.assertEqual(audit.backup_count, 5)
        with patch.dict(os.environ, {'TAG_AUDIT_DIR': str(self.root / 'audit'),
                                    'TAG_AUDIT_MAX_BYTES': '8192', 'TAG_AUDIT_BACKUP_COUNT': '0'}):
            audit = self.module.TagAudit()
            self.assertEqual(audit.log_dir, self.root / 'audit')
            self.assertEqual((audit.max_bytes, audit.backup_count), (8192, 0))
            explicit = self.audit(max_bytes=16384, backup_count=2)
            self.assertEqual((explicit.max_bytes, explicit.backup_count), (16384, 2))
        for kwargs in ({'log_dir': ''}, {'log_dir': 'relative'}, {'log_dir': 'bad\0path'},
                       {'max_bytes': 8191}, {'max_bytes': 104857601}, {'max_bytes': True},
                       {'max_bytes': 8192.0}, {'max_bytes': 'abc'}, {'backup_count': -1},
                       {'backup_count': 101}, {'backup_count': True}, {'backup_count': 1.5}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(
                    self.module.TagAccessUnavailable, '^Tag access temporarily unavailable$'):
                self.audit(**kwargs)

    def test_audit_record_bounds_control_escaping_and_header_budget(self):
        headers = {'X-\n-Control': 'private', 'X-' + 'n' * 10000: 'private'}
        headers.update({'X-' + str(n) + '\u202e' * 100: 'private' for n in range(1000)})
        self.record(method='G\nET' + 'x' * 10000, path='/' + '\u202e\n\0' * 10000,
                    client_ip='p' * 10000, headers=headers)
        raw = (self.root / 'audit' / 'tag-access.jsonl').read_bytes()
        self.assertLessEqual(len(raw), 8192)
        self.assertEqual(raw.count(b'\n'), 1)
        self.assertNotIn(b'\0', raw)
        row = json.loads(raw)
        self.assertLessEqual(len(row['method']), 16)
        self.assertLessEqual(len(row['path']), 256)
        self.assertLessEqual(len(row['client_ip']), 45)
        self.assertLessEqual(len(row['headers']), 32)
        self.assertTrue(all(len(name) <= 64 for name in row['headers']))
        self.assertTrue(row['headers_truncated'])

    def test_audit_header_values_use_exact_allowlist_not_trusted_names(self):
        secret = 'SYNTHETIC_HEADER_SECRET'
        headers = {name: secret for name in ('Authorization', 'Cookie', 'Set-Cookie', 'X-CSRF-Token',
                   'X-Unknown', 'User-Agent', 'Referer', 'Forwarded', 'X-Forwarded-For', 'Accept-Language',
                   'Sec-WebSocket-Key', 'Content-Type', 'Accept', 'Content-Length')}
        self.record(headers=headers)
        raw = (self.root / 'audit' / 'tag-access.jsonl').read_text()
        self.assertNotIn(secret, raw)
        self.assertEqual(set(self.audit_rows()[0]['headers'].values()), {'[REDACTED]'})
        self.record(headers={'Content-Type': 'application/json', 'Accept': 'text/html',
                             'Content-Length': '123', 'Sec-Fetch-Mode': 'navigate'})
        self.assertEqual(self.audit_rows()[1]['headers'], {'content-type': 'application/json',
                         'accept': 'text/html', 'content-length': '123', 'sec-fetch-mode': 'navigate'})
        self.record(headers={'Accept': 'text/html;secret=' + secret,
                             'Content-Type': 'application/json;boundary=' + secret,
                             'Sec-Fetch-Mode': secret})
        self.assertNotIn(secret, (self.root / 'audit' / 'tag-access.jsonl').read_text())

    def test_audit_writes_private_jsonl_and_strips_query_and_fragment(self):
        self.record(path='/tag-inquiry?tag=SYNTHETIC_QUERY_SECRET#SYNTHETIC_FRAGMENT')
        file = self.root / 'audit' / 'tag-access.jsonl'
        raw = file.read_bytes()
        self.assertNotIn(b'SYNTHETIC_QUERY_SECRET', raw)
        self.assertNotIn(b'SYNTHETIC_FRAGMENT', raw)
        row = json.loads(raw)
        self.assertEqual(row['path'], '/tag-inquiry')
        self.assertEqual(row['client_ip'], '192.0.2.1')
        self.assertEqual(row['method'], 'GET')
        self.assertEqual(row['status'], 200)
        self.assertEqual(row['duration_ms'], 1.25)
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(file.parent.stat().st_mode), 0o700)

    def workers(self, target, args, count):
        context = multiprocessing.get_context('spawn')
        barrier, output = context.Barrier(count), context.Queue()
        workers = [context.Process(target=target, args=(*args, barrier, output)) for _ in range(count)]
        try:
            for worker in workers:
                worker.start()
            results = [output.get(timeout=20) for _ in workers]
            for worker in workers:
                worker.join(timeout=10)
                self.assertEqual(worker.exitcode, 0)
            return results
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.kill()
                    worker.join(timeout=5)
                worker.close()
            output.close()
            output.join_thread()

    def test_real_process_race_and_fresh_process_restart_share_quota(self):
        self.assertEqual(sorted(self.workers(process_admission, (str(self.db), 1000), 8)), [0] + [20] * 7)
        self.assertEqual(self.workers(process_admission, (str(self.db), 1001), 1), [19])
        self.assertEqual(self.workers(process_admission, (str(self.db), 1020), 1), [0])

    def test_database_busy_timeout_is_bounded_fail_closed(self):
        self.limiter().admit('192.0.2.1')
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('BEGIN IMMEDIATE')
            started = time.monotonic()
            with self.assertRaises(self.module.TagAccessUnavailable):
                self.limiter().admit('192.0.2.2')
            self.assertLess(time.monotonic() - started, 2)
            db.rollback()
        self.assertEqual(self.limiter().admit('192.0.2.2'), 0)

    def test_state_file_is_private_even_with_permissive_umask(self):
        previous = os.umask(0)
        try:
            self.assertEqual(self.limiter().admit('192.0.2.1'), 0)
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE(self.db.stat().st_mode), 0o600)
        target = self.root / 'target'
        target.write_text('synthetic-not-a-database')
        link = self.root / 'link'
        link.symlink_to(target)
        with self.assertRaises(self.module.TagAccessUnavailable):
            self.limiter(state_file=link).admit('192.0.2.1')
        self.assertEqual(target.read_text(), 'synthetic-not-a-database')

    def test_invalid_ip_never_creates_state_or_echoes_input(self):
        for ip in ('bad-private-value', '', None, 1234, 'fe80::1%eth0', '1' * 1000):
            with self.subTest(kind=type(ip).__name__), self.assertRaisesRegex(ValueError, '^Invalid client IP$'):
                self.limiter().admit(ip)
        self.assertFalse(self.db.exists())

    def test_invalid_clocks_and_storage_fail_closed_with_fixed_errors(self):
        for now in (float('nan'), float('inf'), -1, True, '1000', None):
            with self.subTest(clock=repr(now)), self.assertRaisesRegex(
                    self.module.TagAccessUnavailable, '^Tag access temporarily unavailable$'):
                self.limiter(clock=lambda: now).admit('192.0.2.1')
        for path in (self.root / 'absent' / 'state', self.root):
            with self.subTest(path=path.name), self.assertRaisesRegex(
                    self.module.TagAccessUnavailable, '^Tag access temporarily unavailable$'):
                self.limiter(state_file=path).admit('192.0.2.1')
        self.db.write_bytes(b'not sqlite synthetic private failure detail')
        with self.assertRaisesRegex(self.module.TagAccessUnavailable, '^Tag access temporarily unavailable$'):
            self.limiter().admit('192.0.2.1')

    def test_storage_capacity_is_fail_closed_and_expired_rows_are_reclaimed(self):
        with patch.object(self.module, 'MAX_ENTRIES', 2, create=True):
            for ip in ('192.0.2.1', '192.0.2.2'):
                self.assertEqual(self.limiter().admit(ip), 0)
            with self.assertRaises(self.module.TagAccessUnavailable):
                self.limiter().admit('192.0.2.3')
            self.assertEqual(self.limiter().admit('192.0.2.1'), 20)
            self.now[0] = 1020
            self.assertEqual(self.limiter().admit('192.0.2.3'), 0)
            with closing(sqlite3.connect(self.db)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM tag_admissions').fetchone()[0], 1)

    def test_backward_clock_is_fail_closed_across_restart_and_other_ips(self):
        self.assertEqual(self.limiter().admit('192.0.2.1'), 0)
        self.now[0] = 1010
        self.assertEqual(self.limiter().admit('192.0.2.1'), 10)
        self.now[0] = 1009
        for ip in ('192.0.2.1', '192.0.2.2'):
            with self.assertRaises(self.module.TagAccessUnavailable):
                self.limiter().admit(ip)
        self.now[0] = 1020
        self.assertEqual(self.limiter().admit('192.0.2.1'), 0)

    def test_limiter_configuration_uses_only_separate_state_and_valid_secret(self):
        with patch.dict(os.environ, {'CONTACT_SECRET': SECRET.decode()}, clear=True):
            default = self.module.TagLimiter()
            self.assertEqual(default.state_file, '/var/lib/btc4fun/tag-lookup.sqlite3')
            with patch.dict(os.environ, {'TAG_LOOKUP_STATE_FILE': str(self.db),
                                        'LOOKUP_STATE_FILE': '/never/open/website.sqlite3'}):
                self.assertEqual(self.module.TagLimiter().admit('192.0.2.1'), 0)
        for secret in (None, '', 'x' * 31, b'x' * 31, 4, ' ' * 32):
            with self.subTest(secret_type=type(secret).__name__), patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(self.module.TagAccessUnavailable, '^Tag access temporarily unavailable$'):
                    self.limiter(secret=secret)
        for path in ('', ':memory:', 'file:state?mode=memory', 'relative.db', 'bad\0path'):
            with self.subTest(path=repr(path)), self.assertRaises(self.module.TagAccessUnavailable):
                self.limiter(state_file=path)
        with self.assertRaises(self.module.TagAccessUnavailable):
            self.limiter(clock=1)

    def test_canonical_ip_aliases_share_quota_without_plaintext_state(self):
        self.assertEqual(self.limiter().admit('::ffff:192.0.2.1'), 0)
        self.assertEqual(self.limiter().admit('192.0.2.1'), 20)
        self.assertEqual(self.limiter().admit('2001:db8::1'), 0)
        self.assertEqual(self.limiter().admit('2001:0db8:0:0:0:0:0:1'), 20)
        raw = self.db.read_bytes()
        for private in (SECRET, b'192.0.2.1', b'2001:db8'):
            self.assertNotIn(private, raw)
        with closing(sqlite3.connect(self.db)) as db:
            rows = db.execute('SELECT ip_hash, admitted_at FROM tag_admissions').fetchall()
        self.assertEqual(len(rows), 2)
        for key, timestamp in rows:
            self.assertRegex(key, r'^[a-f0-9]{64}$')
            self.assertEqual(timestamp, 1000)

    def test_per_ip_twenty_second_gate_expiry_equality_no_denial_refresh(self):
        self.assertEqual(self.limiter().admit('192.0.2.1'), 0)
        self.assertEqual(self.limiter().admit('192.0.2.2'), 0)
        self.assertEqual(self.limiter().admit('192.0.2.1'), 20)
        self.now[0] = 1018.2
        self.assertEqual(self.limiter().admit('192.0.2.1'), 2)
        self.now[0] = 1019.999
        self.assertEqual(self.limiter().admit('192.0.2.1'), 1)
        self.now[0] = 1020
        self.assertEqual(self.limiter().admit('192.0.2.1'), 0)
        self.assertEqual(self.limiter().admit('192.0.2.1'), 20)

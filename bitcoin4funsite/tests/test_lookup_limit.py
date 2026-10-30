"""Offline lookup admission proofs; only synthetic scratch SQLite state."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import threading
import multiprocessing
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'lookup_limit.py'
SECRET = b'synthetic-lookup-secret-for-offline-tests-only'


def load_module():
    if not PATH.is_file():
        raise AssertionError('lookup limiter implementation missing')
    spec = importlib.util.spec_from_file_location('btc4fun_lookup_limit', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def process_admission(path, now, barrier, output):
    # spawn imports a fresh module, sharing only the real on-disk SQLite state.
    module = load_module()
    limiter = module.LookupLimiter(path, SECRET, clock=lambda: now)
    barrier.wait(timeout=10)
    # The bounded production busy timeout may reject a worker under loaded CI.
    # Retry only fail-closed unavailability; never retry a quota denial/admission.
    for attempt in range(5):
        try:
            result = limiter.admit('192.0.2.1', 'Concurrent')
            break
        except module.LookupLimitUnavailable:
            if attempt == 4:
                raise
    output.put(result)


class LookupLimitContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(
            prefix='lookup-limit-tests-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / 'lookup.sqlite3'
        self.now = [1000.0]
        self.module = load_module()

    def limiter(self, **kwargs):
        return self.module.LookupLimiter(
            state_file=kwargs.pop('state_file', self.db),
            secret=kwargs.pop('secret', SECRET),
            clock=kwargs.pop('clock', lambda: self.now[0]), **kwargs)

    def test_five_admissions_use_a_sliding_not_fixed_window(self):
        for now in (1000, 1003.5, 1011, 1027, 1059):
            self.now[0] = now
            self.assertEqual(self.limiter().admit('192.0.2.1', 'SameSerial'), 0)
        self.assertEqual(self.limiter().admit('192.0.2.1', 'Sixth'), 1)
        self.now[0] = 1060
        self.assertEqual(self.limiter().admit('192.0.2.1', 'Sixth'), 0)
        self.assertEqual(self.limiter().admit('192.0.2.1', 'Seventh'), 4)
        self.now[0] = 1063.499
        self.assertEqual(self.limiter().admit('192.0.2.1', 'Seventh'), 1)
        self.now[0] = 1063.5
        self.assertEqual(self.limiter().admit('192.0.2.1', 'Seventh'), 0)
        self.assertEqual(self.limiter().admit('192.0.2.1', 'Eighth'), 8)
        self.assertEqual(self.limiter().admit('192.0.2.2', 'OtherClient'), 0)

    def test_legacy_state_is_preserved_and_conservatively_expires(self):
        import hashlib
        import hmac
        ip, serial = '192.0.2.1', 'Legacy'
        ip_hash = hmac.new(SECRET, b'lookup-ip\0' + ip.encode(), hashlib.sha256).hexdigest()
        serial_hash = hmac.new(SECRET, b'lookup-serial\0' + serial.encode(), hashlib.sha256).hexdigest()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE lookup_admissions (ip_hash TEXT PRIMARY KEY, '
                       'serial_hash TEXT NOT NULL, admitted_at REAL NOT NULL) WITHOUT ROWID')
            db.execute('INSERT INTO lookup_admissions VALUES (?, ?, ?)', (ip_hash, serial_hash, 1000))
        for now, retry in ((1000, 60), (1015, 45), (1059.99, 1)):
            self.now[0] = now
            self.assertEqual(self.limiter().admit(ip, 'New'), retry)
            self.assertEqual(self.limiter().admit(ip, serial, qr=True), 0)
            self.assertEqual(self.limiter().admit(ip, 'Different', qr=True), retry)
            with closing(sqlite3.connect(self.db)) as db:
                self.assertEqual(db.execute('SELECT * FROM lookup_admissions').fetchall(),
                                 [(ip_hash, serial_hash, 1000)])
        self.assertEqual(self.limiter().admit('192.0.2.2', 'OtherClient'), 0)
        self.now[0] = 1060
        for _ in range(5):
            self.assertEqual(self.limiter().admit(ip, 'New'), 0)
        self.assertEqual(self.limiter().admit(ip, serial, qr=True), 60)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM lookup_admissions').fetchone()[0], 0)

    def test_backward_clock_fails_closed_without_refresh_or_reset(self):
        self.assertEqual(self.limiter().admit('192.0.2.1', 'First'), 0)
        self.now[0] = 999
        for qr in (False, True):
            with self.assertRaises(self.module.LookupLimitUnavailable):
                self.limiter().admit('192.0.2.1', 'First', qr=qr)
        self.now[0] = 1000
        for _ in range(4):
            self.assertEqual(self.limiter().admit('192.0.2.1', 'Other'), 0)
        self.assertEqual(self.limiter().admit('192.0.2.1', 'Other'), 60)

    def test_state_is_bounded_full_fails_closed_and_expired_entries_pruned(self):
        limiter = self.limiter()
        # A smaller test ceiling exercises the same SQL path without thousands of fsyncs.
        with patch.object(self.module, 'MAX_ENTRIES', 3, create=True):
            for n in range(1, 4):
                self.assertEqual(limiter.admit('192.0.2.' + str(n), 'A'), 0)
            with self.assertRaises(self.module.LookupLimitUnavailable):
                limiter.admit('192.0.2.4', 'A')
            for n in range(1, 4):
                for _ in range(4):
                    self.assertEqual(limiter.admit('192.0.2.' + str(n), 'A'), 0)
                self.assertEqual(limiter.admit('192.0.2.' + str(n), 'A'), 60)
                self.assertEqual(limiter.admit('192.0.2.' + str(n), 'A', qr=True), 0)
            with closing(sqlite3.connect(self.db)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM lookup_window').fetchone()[0], 15)
            self.now[0] = 1060
            self.assertEqual(limiter.admit('192.0.2.4', 'A'), 0)
            with closing(sqlite3.connect(self.db)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM lookup_window').fetchone()[0], 1)

    def test_concurrent_separate_connections_only_five_admitted(self):
        barrier = threading.Barrier(8)
        def admit(limiter):
            barrier.wait(timeout=3)
            return limiter.admit('192.0.2.1', 'A')
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(admit, [self.limiter() for _ in range(8)]))
        self.assertEqual(sorted(results), [0] * 5 + [60] * 3)

    def test_synchronized_process_workers_and_fresh_restart_share_atomic_quota(self):
        context = multiprocessing.get_context('spawn')
        def run_workers(count, now):
            barrier, output = context.Barrier(count), context.Queue()
            workers = [context.Process(target=process_admission,
                       args=(str(self.db), now, barrier, output)) for _ in range(count)]
            try:
                for worker in workers:
                    worker.start()
                results = [output.get(timeout=15) for _ in workers]
                for worker in workers:
                    worker.join(timeout=10)
                    self.assertEqual(worker.exitcode, 0)
                return sorted(results)
            finally:
                for worker in workers:
                    if worker.is_alive():
                        worker.kill()
                        worker.join(timeout=5)
                    worker.close()
                output.close()
                output.join_thread()
        self.assertEqual(run_workers(8, 1000), [0] * 5 + [60] * 3)
        self.assertEqual(run_workers(1, 1001), [59])
        self.assertEqual(run_workers(1, 1060), [0])

    def test_state_contains_only_hmac_identities_and_original_timestamp(self):
        limiter = self.limiter()
        ip, serial = '192.0.2.101', 'Synthetic-Private-Serial'
        self.assertEqual(limiter.admit(ip, serial), 0)
        with closing(sqlite3.connect(self.db)) as db:
            before = db.execute('SELECT ip_hash, serial_hash, admitted_at FROM lookup_window').fetchall()
            root = db.execute("SELECT rootpage FROM sqlite_master WHERE name='lookup_window'").fetchone()
            self.assertEqual([column[1] for column in db.execute('PRAGMA table_info(lookup_window)')],
                             ['ip_hash', 'slot', 'serial_hash', 'admitted_at'])
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0][2], 1000)
        self.assertRegex(before[0][0], r'^[a-f0-9]{64}$')
        self.assertRegex(before[0][1], r'^[a-f0-9]{64}$')
        self.now[0] = 1014
        self.assertEqual(self.limiter().admit(ip, serial, qr=True), 0)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT ip_hash, serial_hash, admitted_at FROM lookup_window').fetchall(), before)
            self.assertEqual(db.execute("SELECT rootpage FROM sqlite_master WHERE name='lookup_window'").fetchone(), root)
        for path in Path(self.directory.name).iterdir():
            data = path.read_bytes()
            for private in [ip.encode(), serial.encode(), SECRET]:
                self.assertNotIn(private, data)

    def test_database_lock_busy_wait_is_bounded_and_sanitized(self):
        limiter = self.limiter()
        limiter.admit('192.0.2.1', 'A')
        with closing(sqlite3.connect(self.db, isolation_level=None)) as db:
            db.execute('BEGIN IMMEDIATE')
            started = time.monotonic()
            with self.assertRaises(self.module.LookupLimitUnavailable) as caught:
                limiter.admit('192.0.2.2', 'B')
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertEqual(str(caught.exception), 'Lookup temporarily unavailable')
            db.rollback()
        self.assertEqual(limiter.admit('192.0.2.2', 'B'), 0)

    def test_nonfinite_or_invalid_clock_fails_closed(self):
        for value in [float('nan'), float('inf'), -float('inf'), None, '1000', True]:
            with self.subTest(value=repr(value)), self.assertRaises(self.module.LookupLimitUnavailable):
                self.limiter(clock=lambda: value).admit('192.0.2.1', 'A')
        self.assertEqual(self.limiter().admit('192.0.2.1', 'A'), 0)

    def test_config_and_sql_errors_are_sanitized_fail_closed(self):
        def unavailable(callback):
            with self.assertRaises(self.module.LookupLimitUnavailable) as caught:
                callback()
            self.assertEqual(str(caught.exception), 'Lookup temporarily unavailable')
            self.assertNotIn(str(self.db), repr(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)

        for secret in [b'', b'x' * 31, 123, [], '\ud800']:
            with self.subTest(secret_type=type(secret)):
                unavailable(lambda: self.limiter(secret=secret).admit('192.0.2.1', 'A'))
        for path in ['', ':memory:', 'file:memory?mode=memory', 123]:
            unavailable(lambda: self.limiter(state_file=path).admit('192.0.2.1', 'A'))
        unavailable(lambda: self.limiter(state_file=self.db / 'missing').admit('192.0.2.1', 'A'))
        self.db.write_bytes(b'synthetic corrupt sqlite file')
        unavailable(lambda: self.limiter().admit('192.0.2.1', 'A'))

    def test_default_environment_is_injected_only_with_synthetic_values(self):
        with patch.dict(os.environ, {'CONTACT_SECRET': SECRET.decode(), 'LOOKUP_STATE_FILE': str(self.db)}):
            limiter = self.module.LookupLimiter(clock=lambda: self.now[0])
            self.assertEqual(limiter.admit('192.0.2.1', 'A'), 0)
            for _ in range(4):
                self.assertEqual(self.limiter().admit('192.0.2.1', 'B'), 0)
            self.assertEqual(self.limiter().admit('192.0.2.1', 'B'), 60)

    def test_invalid_arguments_rejected_before_hash_or_database(self):
        limiter = self.limiter()
        invalid = [(None, 'A', False), (123, 'A', False), ('x' * 100, 'A', False),
                   ('not-an-ip', 'A', False), ('192.0.2.1', None, False),
                   ('192.0.2.1', '', False), ('192.0.2.1', '-bad', False),
                   ('192.0.2.1', 'a' * 65, False), ('192.0.2.1', 'A\n', False),
                   ('192.0.2.1', 'A', 1), ('192.0.2.1', 'A', 'yes')]
        with patch.object(self.module.hmac, 'new', side_effect=AssertionError('hash called')), \
                patch.object(self.module.sqlite3, 'connect', side_effect=AssertionError('DB called')):
            for ip, serial, qr in invalid:
                with self.subTest(ip=ip, serial=serial, qr=qr), self.assertRaises(ValueError):
                    limiter.admit(ip, serial, qr=qr)

    def test_ipv6_text_aliases_share_gate(self):
        limiter = self.limiter()
        self.assertEqual(limiter.admit('2001:0db8:0000:0000:0000:0000:0000:0001', 'A'), 0)
        for _ in range(4):
            self.assertEqual(limiter.admit('2001:db8::1', 'B'), 0)
        self.assertEqual(limiter.admit('2001:db8::1', 'B'), 60)

    def test_qr_companions_for_all_serials_keep_individual_expiry(self):
        limiter = self.limiter()
        self.assertEqual(limiter.admit('192.0.2.1', 'First', qr=True), 0)
        for now, serial in ((1007, 'Second'), (1011, 'Third'), (1027, 'Fourth'), (1059, 'Fifth')):
            self.now[0] = now
            self.assertEqual(limiter.admit('192.0.2.1', serial), 0)
        with closing(sqlite3.connect(self.db)) as db:
            before = db.execute('SELECT * FROM lookup_window ORDER BY slot').fetchall()
        for serial in ('First', 'Second', 'Third', 'Fourth', 'Fifth'):
            self.assertEqual(self.limiter().admit('192.0.2.1', serial, qr=True), 0)
            self.assertEqual(self.limiter().admit('192.0.2.1', serial), 1)
        self.assertEqual(limiter.admit('192.0.2.1', 'Unseen', qr=True), 1)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT * FROM lookup_window ORDER BY slot').fetchall(), before)
        self.now[0] = 1060
        self.assertEqual(limiter.admit('192.0.2.1', 'Sixth'), 0)
        self.assertEqual(limiter.admit('192.0.2.1', 'First', qr=True), 7)
        self.assertEqual(limiter.admit('192.0.2.1', 'Second', qr=True), 0)
        self.now[0] = 1067
        self.assertEqual(limiter.admit('192.0.2.1', 'Second', qr=True), 0)
        self.assertEqual(limiter.admit('192.0.2.1', 'Unseen'), 4)

    def test_strict_gate_boundary_shared_instances_and_distinct_ip(self):
        first, second = self.limiter(), self.limiter()
        for _ in range(5):
            self.assertEqual(first.admit('192.0.2.1', 'Serial-1'), 0)
        self.assertEqual(second.admit('192.0.2.1', 'Serial-1'), 60)
        self.assertEqual(second.admit('192.0.2.2', 'Serial-1'), 0)
        self.now[0] = 1059.999
        self.assertEqual(second.admit('192.0.2.1', 'Other'), 1)
        self.now[0] = 1060.0
        for _ in range(5):
            self.assertEqual(second.admit('192.0.2.1', 'Other'), 0)
        self.assertEqual(self.limiter().admit('192.0.2.1', 'Other'), 60)


if __name__ == '__main__':
    unittest.main()

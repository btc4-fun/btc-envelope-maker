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

    def test_state_is_bounded_full_fails_closed_and_expired_entries_pruned(self):
        limiter = self.limiter()
        # A smaller test ceiling exercises the same SQL path without thousands of fsyncs.
        with patch.object(self.module, 'MAX_ENTRIES', 3, create=True):
            for n in range(1, 4):
                self.assertEqual(limiter.admit('192.0.2.' + str(n), 'A'), 0)
            with self.assertRaises(self.module.LookupLimitUnavailable):
                limiter.admit('192.0.2.4', 'A')
            self.assertEqual(limiter.admit('192.0.2.1', 'A'), 15)
            self.now[0] = 1015
            self.assertEqual(limiter.admit('192.0.2.1', 'B'), 0)
            self.now[0] = 1060
            self.assertEqual(limiter.admit('192.0.2.4', 'A'), 0)
            with closing(sqlite3.connect(self.db)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM lookup_admissions').fetchone()[0], 2)

    def test_concurrent_separate_connections_only_one_admitted(self):
        barrier = threading.Barrier(2)
        def admit(limiter):
            barrier.wait(timeout=3)
            return limiter.admit('192.0.2.1', 'A')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(admit, [self.limiter(), self.limiter()]))
        self.assertEqual(sorted(results), [0, 15])

    def test_state_contains_only_hmac_identities_and_original_timestamp(self):
        limiter = self.limiter()
        ip, serial = '192.0.2.101', 'Synthetic-Private-Serial'
        self.assertEqual(limiter.admit(ip, serial), 0)
        with closing(sqlite3.connect(self.db)) as db:
            before = db.execute('SELECT * FROM lookup_admissions').fetchall()
            root = db.execute("SELECT rootpage FROM sqlite_master WHERE name='lookup_admissions'").fetchone()
            self.assertEqual([column[1] for column in db.execute('PRAGMA table_info(lookup_admissions)')],
                             ['ip_hash', 'serial_hash', 'admitted_at'])
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0][2], 1000)
        self.assertRegex(before[0][0], r'^[a-f0-9]{64}$')
        self.assertRegex(before[0][1], r'^[a-f0-9]{64}$')
        self.now[0] = 1014
        self.assertEqual(self.limiter().admit(ip, serial, qr=True), 0)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT * FROM lookup_admissions').fetchall(), before)
            self.assertEqual(db.execute("SELECT rootpage FROM sqlite_master WHERE name='lookup_admissions'").fetchone(), root)
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
            self.assertEqual(self.limiter().admit('192.0.2.1', 'B'), 15)

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
        self.assertEqual(limiter.admit('2001:db8::1', 'B'), 15)

    def test_qr_companion_does_not_extend_or_refresh_gate(self):
        limiter = self.limiter()
        self.assertEqual(limiter.admit('192.0.2.1', 'First', qr=True), 0)
        self.now[0] = 1007
        self.assertEqual(limiter.admit('192.0.2.1', 'First', qr=True), 0)
        self.assertEqual(limiter.admit('192.0.2.1', 'Different', qr=True), 8)
        self.assertEqual(limiter.admit('192.0.2.1', 'First'), 8)
        self.now[0] = 1014.999
        self.assertEqual(self.limiter().admit('192.0.2.1', 'First', qr=True), 0)
        self.now[0] = 1015
        self.assertEqual(limiter.admit('192.0.2.1', 'Next'), 0)
        self.assertEqual(limiter.admit('192.0.2.1', 'First', qr=True), 15)

    def test_strict_gate_boundary_shared_instances_and_distinct_ip(self):
        first, second = self.limiter(), self.limiter()
        self.assertEqual(first.admit('192.0.2.1', 'Serial-1'), 0)
        self.assertEqual(second.admit('192.0.2.1', 'Serial-1'), 15)
        self.assertEqual(second.admit('192.0.2.2', 'Serial-1'), 0)
        self.now[0] = 1014.999
        self.assertEqual(second.admit('192.0.2.1', 'Other'), 1)
        self.now[0] = 1015.0
        self.assertEqual(second.admit('192.0.2.1', 'Other'), 0)
        self.assertEqual(self.limiter().admit('192.0.2.1', 'Other'), 15)


if __name__ == '__main__':
    unittest.main()

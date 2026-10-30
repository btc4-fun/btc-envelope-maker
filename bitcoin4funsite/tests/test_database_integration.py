from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
import unittest
import uuid

import psycopg

APP_PATH = Path(__file__).resolve().parents[1] / 'app.py'
sys.path.insert(0, str(APP_PATH.parent))
PUBLIC_TEST_ADDRESS = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'


@unittest.skipUnless(os.environ.get('BTC_TEST_OWNER_PASSWORD_FILE'), 'explicit isolated database credentials required')
class ReadonlyDatabaseIntegration(unittest.TestCase):
    def setUp(self):
        self.owner = dict(
            host=os.environ.get('BTC_DB_HOST', '127.0.0.1'),
            port=int(os.environ.get('BTC_DB_PORT', '5432')),
            dbname=os.environ['BTC_DB_NAME'],
            user=os.environ['BTC_TEST_OWNER_USER'],
            password=Path(os.environ['BTC_TEST_OWNER_PASSWORD_FILE']).read_text().rstrip('\r\n'),
            connect_timeout=4,
        )
        self.serial = 'TEST-DO-NOT-FUND-' + uuid.uuid4().hex[:16]
        with psycopg.connect(**self.owner) as conn:
            conn.execute('INSERT INTO public.wallets (serial,address) VALUES (%s,%s)', (self.serial, PUBLIC_TEST_ADDRESS))
        spec = importlib.util.spec_from_file_location('bitcoin4fun_integration_app', APP_PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        from lookup_limit import LookupLimiter
        directory = tempfile.TemporaryDirectory(prefix='wallet-db-limit-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(directory.cleanup)
        self.limiter = LookupLimiter(state_file=str(Path(directory.name) / 'lookup.sqlite3'),
                                     secret='SYNTHETIC_DB_TEST_SECRET_' * 2)

    def tearDown(self):
        with psycopg.connect(**self.owner) as conn:
            conn.execute('DELETE FROM public.wallets WHERE serial = %s AND address = %s', (self.serial, PUBLIC_TEST_ADDRESS))
        with psycopg.connect(**self.owner) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM public.wallets WHERE serial=%s', (self.serial,)).fetchone()[0], 0)

    def test_actual_readonly_role_serves_public_record_and_cannot_write(self):
        row = self.module.database_lookup(self.serial)
        self.assertEqual(row, {'serial': self.serial, 'address': PUBLIC_TEST_ADDRESS})
        app = self.module.create_app({'TESTING': True, 'LOOKUP_LIMITER': self.limiter})
        response = app.test_client().get('/api/wallets/' + self.serial, environ_overrides={'REMOTE_ADDR': '198.51.100.81'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['address'], PUBLIC_TEST_ADDRESS)
        self.assertEqual(app.test_client().get('/api/wallets/' + self.serial + '/qr.svg', environ_overrides={'REMOTE_ADDR': '198.51.100.81'}).status_code, 200)
        web = {**self.owner, 'user': os.environ['BTC_DB_USER'], 'password': Path(os.environ['BTC_DB_PASSWORD_FILE']).read_text().rstrip('\r\n')}
        with psycopg.connect(**web) as conn:
            conn.execute('SET default_transaction_read_only = off')
            conn.commit()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('UPDATE public.wallets SET address=address WHERE serial=%s', (self.serial,))
            conn.rollback()
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute('SELECT created_utc FROM public.wallets LIMIT 1')
            conn.rollback()

    def test_private_contact_columns_exist_and_are_not_publicly_readable(self):
        metadata = ('email', 'synthetic-only@example.invalid', 'SYNTHETIC_PRIVATE_CONTACT_NOTES')
        with psycopg.connect(**self.owner) as connection:
            columns = {row[0] for row in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='wallets'")}
            self.assertTrue({'contact_type', 'contact_value', 'notes'} <= columns)
            connection.execute('UPDATE public.wallets SET contact_type=%s, contact_value=%s, notes=%s WHERE serial=%s', (*metadata, self.serial))
        response = self.module.create_app({'TESTING': True, 'LOOKUP_LIMITER': self.limiter}).test_client().get('/api/wallets/' + self.serial, environ_overrides={'REMOTE_ADDR': '198.51.100.82'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {'serial', 'address', 'explorer_url'})
        self.assertNotIn('SYNTHETIC_PRIVATE', response.text)
        self.assertNotIn('example.invalid', response.text)
        web = {**self.owner, 'user': os.environ['BTC_DB_USER'], 'password': Path(os.environ['BTC_DB_PASSWORD_FILE']).read_text().rstrip('\r\n')}
        with psycopg.connect(**web) as connection:
            for column in ('contact_type', 'contact_value', 'notes'):
                with self.subTest(column=column), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    # Identifiers come from the fixed tuple above, never request data.
                    connection.execute('SELECT ' + column + ' FROM public.wallets WHERE serial=%s', (self.serial,))
                connection.rollback()


if __name__ == '__main__':
    unittest.main()

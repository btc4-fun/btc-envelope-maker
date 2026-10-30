from __future__ import annotations

import importlib.util
import os
import sys
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

    def tearDown(self):
        with psycopg.connect(**self.owner) as conn:
            conn.execute('DELETE FROM public.wallets WHERE serial = %s AND address = %s', (self.serial, PUBLIC_TEST_ADDRESS))
        with psycopg.connect(**self.owner) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM public.wallets WHERE serial=%s', (self.serial,)).fetchone()[0], 0)

    def test_actual_readonly_role_serves_public_record_and_cannot_write(self):
        row = self.module.database_lookup(self.serial)
        self.assertEqual(row, {'serial': self.serial, 'address': PUBLIC_TEST_ADDRESS})
        app = self.module.create_app({'TESTING': True})
        response = app.test_client().get('/api/wallets/' + self.serial)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['address'], PUBLIC_TEST_ADDRESS)
        self.assertEqual(app.test_client().get('/api/wallets/' + self.serial + '/qr.svg').status_code, 200)
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


if __name__ == '__main__':
    unittest.main()

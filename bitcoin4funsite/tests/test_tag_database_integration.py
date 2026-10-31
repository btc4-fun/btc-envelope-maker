"""Opt-in, synthetic PostgreSQL ACL proofs; never use configured databases.

Run: NFC_TEST_POSTGRES=1 .venv/bin/python -m unittest discover \
    -s bitcoin4funsite/tests -p test_tag_database_integration.py -v

Only a uniquely named container on the local Unix Docker socket is used. The
real Flask/database/limiter/audit/ChainActivity path runs with fixture upstream
bytes, not live Bitcoin queries. No production role or schema is changed.
"""
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

import psycopg

APP_PATH = Path(__file__).resolve().parents[1] / 'app.py'
sys.path.insert(0, str(APP_PATH.parent))
from chain_activity import ChainActivity, MAX_RESPONSE_BYTES
from lookup_limit import LookupLimiter
from tag_access import TagAudit, TagLimiter

SERIAL = 'SYNTH-DO-NOT-FUND-0587k45300'
UID = '01020304050607'
ADDRESS = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'
PRIVATE_COLUMNS = ('jalali_datetime', 'created_utc', 'contact_type', 'contact_value', 'notes')
PRIVATE_VALUES = ('SYNTH_JALALI', 'SYNTH_CREATED', 'SYNTH_CONTACT_TYPE',
                  'SYNTH_PRIVATE@example.invalid', 'SYNTH_PRIVATE_NOTES')
ROLE = 'synthetic_tag_web'
SECRET = b'SYNTHETIC_TAG_DATABASE_TEST_ONLY_' * 2


@unittest.skipUnless(os.environ.get('NFC_TEST_POSTGRES') == '1',
                     'opt-in disposable local Docker PostgreSQL')
class TagReadonlyPostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # libpq service/hostaddr/options must not redirect even explicit hosts.
        clean_env = {key: value for key, value in os.environ.items()
                     if not key.startswith(('PG', 'BTC_DB_'))}
        environment = patch.dict(os.environ, clean_env, clear=True)
        environment.start()
        cls.addClassCleanup(environment.stop)
        cls.name = 'nfc-tag-readonly-proof-' + uuid.uuid4().hex[:12]
        cls.docker = ['docker', '--host', 'unix:///var/run/docker.sock']
        cls.addClassCleanup(cls.remove_container)
        subprocess.run(cls.docker + [
            'run', '--detach', '--pull=never', '--name', cls.name,
            '--publish', '127.0.0.1::5432',
            '--env', 'POSTGRES_HOST_AUTH_METHOD=trust',
            '--tmpfs', '/var/lib/postgresql', 'postgres:18-bookworm',
        ], check=True, capture_output=True, text=True, timeout=30)
        endpoint = subprocess.check_output(
            cls.docker + ['port', cls.name, '5432/tcp'], text=True, timeout=10).strip()
        if not endpoint.startswith('127.0.0.1:') or '\n' in endpoint:
            raise AssertionError('test PostgreSQL must bind loopback only')
        cls.owner = dict(host='127.0.0.1', port=int(endpoint.rsplit(':', 1)[1]),
                         dbname='postgres', user='postgres', connect_timeout=1,
                         sslmode='disable')
        for _ in range(100):
            try:
                with psycopg.connect(**cls.owner) as connection:
                    connection.execute('SELECT 1')
                break
            except psycopg.OperationalError:
                time.sleep(0.1)
        else:
            raise AssertionError('disposable PostgreSQL TCP startup timed out')
        with psycopg.connect(**cls.owner) as connection:
            connection.execute('CREATE ROLE synthetic_tag_web LOGIN NOSUPERUSER '
                               'NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS')
            connection.execute('REVOKE ALL ON SCHEMA public FROM PUBLIC')
            connection.execute('GRANT USAGE ON SCHEMA public TO synthetic_tag_web')
            connection.execute('CREATE TABLE public.wallets ('
                               'serial TEXT PRIMARY KEY, address TEXT NOT NULL, '
                               'nfc_uid TEXT UNIQUE, jalali_datetime TEXT, '
                               'created_utc TEXT, contact_type TEXT, '
                               'contact_value TEXT, notes TEXT)')
            connection.execute('INSERT INTO public.wallets VALUES '
                               '(%s,%s,%s,%s,%s,%s,%s,%s)',
                               (SERIAL, ADDRESS, UID, *PRIVATE_VALUES))
        print('\nDisposable PostgreSQL started: ' + cls.name, flush=True)

    @classmethod
    def remove_container(cls):
        names = subprocess.check_output(
            cls.docker + ['ps', '--all', '--format', '{{.Names}}'],
            text=True, timeout=10).splitlines()
        if cls.name in names:
            subprocess.run(cls.docker + ['rm', '--force', cls.name],
                           check=True, capture_output=True, timeout=30)
        names = subprocess.check_output(
            cls.docker + ['ps', '--all', '--format', '{{.Names}}'],
            text=True, timeout=10).splitlines()
        if cls.name in names:
            raise AssertionError('disposable PostgreSQL container cleanup failed')
        print('Verified container absent: ' + cls.name, flush=True)

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='nfc-tag-pg-',
                                                dir=os.environ.get('TMPDIR'))
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        password_file = self.directory / 'synthetic-password'
        password_file.write_text('SYNTHETIC_LOCAL_ONLY\n', encoding='utf-8')
        password_file.chmod(0o600)
        environment = patch.dict(os.environ, {
            'BTC_DB_HOST': '127.0.0.1', 'BTC_DB_PORT': str(self.owner['port']),
            'BTC_DB_NAME': 'postgres', 'BTC_DB_USER': ROLE,
            'BTC_DB_PASSWORD_FILE': str(password_file),
        })
        environment.start()
        self.addCleanup(environment.stop)
        with psycopg.connect(**self.owner) as connection:
            # Table-level revocation does NOT revoke column grants. Reset both.
            connection.execute('REVOKE ALL ON public.wallets FROM synthetic_tag_web')
            connection.execute('REVOKE SELECT (serial,address,nfc_uid) '
                               'ON public.wallets FROM synthetic_tag_web')
            connection.execute('GRANT SELECT (serial,address) '
                               'ON public.wallets TO synthetic_tag_web')
        spec = importlib.util.spec_from_file_location('tag_pg_integration_app', APP_PATH)
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.clock = [100.0]
        self.requests = []
        self.tag_state = self.directory / 'tag.sqlite3'
        self.audit_dir = self.directory / 'audit'
        self.app = self.module.create_app({
            'TESTING': True, 'TAG_LOOKUP_ENABLED': True,
            'TAG_ACTIVITY': ChainActivity(self.transport),
            'TAG_LIMITER': self.new_tag_limiter(),
            'TAG_AUDIT': TagAudit(self.audit_dir),
            'LOOKUP_LIMITER': LookupLimiter(str(self.directory / 'serial.sqlite3'),
                                           SECRET, lambda: self.clock[0]),
        })
        # Neither lookup callable is substituted: both route paths use SQL.
        self.assertNotIn('TAG_LOOKUP', self.app.config)
        self.assertNotIn('WALLET_LOOKUP', self.app.config)
        self.client = self.app.test_client()

    def new_tag_limiter(self):
        return TagLimiter(str(self.tag_state), SECRET, lambda: self.clock[0])

    def transport(self, url, **options):
        self.requests.append((url, options))
        base = 'https://blockstream.info/api/address/' + ADDRESS
        if url == base + '/txs/chain':
            return b'[]'
        if url == base:
            return json.dumps({
                'address': ADDRESS,
                'chain_stats': {'funded_txo_sum': 800, 'spent_txo_sum': 300},
                'mempool_stats': {'funded_txo_sum': 0, 'spent_txo_sum': 100},
            }).encode()
        raise AssertionError('Unexpected fixture transport URL')

    def grant_uid(self):
        with psycopg.connect(**self.owner) as connection:
            connection.execute('GRANT SELECT (nfc_uid) ON public.wallets '
                               'TO synthetic_tag_web')

    def serial_response(self):
        response = self.client.get('/api/wallets/' + SERIAL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {
            'serial': SERIAL, 'address': ADDRESS,
            'explorer_url': 'https://mempool.space/address/' + ADDRESS,
        })
        return response.json

    def test_missing_uid_grant_denies_then_approved_grant_serves_real_route(self):
        before = self.serial_response()
        with self.assertRaises(psycopg.errors.InsufficientPrivilege) as denied:
            self.module.database_lookup(UID, by_tag=True)
        self.assertEqual(denied.exception.sqlstate, '42501')
        response = self.client.get('/api/tags/' + UID)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {'error': 'tag_unavailable'})
        self.assertEqual(self.requests, [])

        self.grant_uid()
        self.assertEqual(self.module.database_lookup(UID, by_tag=True),
                         {'serial': SERIAL, 'address': ADDRESS})
        self.clock[0] += 20  # Failed database queries still consume admission.
        response = self.client.get('/api/tags/' + UID)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['serial'], SERIAL)
        self.assertEqual(response.json['address'], ADDRESS)
        self.assertEqual(response.json['confirmed_sats'], 500)
        self.assertEqual(response.json['pending_delta_sats'], -100)
        self.assertEqual(response.json['transactions'], [])
        self.assertEqual(response.json['history_scope'], 'confirmed_only')
        self.assertEqual(response.json['mempool_scope'], 'balance_only')
        self.assertEqual(response.json['consistency'], 'non_atomic')
        self.assertEqual(len(self.requests), 2)
        for _, options in self.requests:
            self.assertEqual(options, {'headers': {'Accept': 'application/json'},
                                       'max_bytes': MAX_RESPONSE_BYTES, 'timeout': 4})
        self.assertEqual(self.serial_response(), before)
        qr = self.client.get('/api/wallets/' + SERIAL + '/qr.svg')
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.mimetype, 'image/svg+xml')
        self.assertIn(b'<svg', qr.data)
        self.assertEqual(len(self.requests), 2)

        # Reconstruct the limiter: denial is persisted, not in-memory state.
        self.app.config['TAG_LIMITER'] = self.new_tag_limiter()
        self.app.config['TAG_AUDIT'] = TagAudit(self.audit_dir)
        retry = self.client.get('/api/tags/' + UID)
        self.assertEqual(retry.status_code, 429)
        self.assertEqual(retry.headers['Retry-After'], '20')
        self.assertEqual(len(self.requests), 2)
        with closing(sqlite3.connect(self.tag_state)) as connection:
            self.assertEqual(connection.execute(
                'SELECT count(*) FROM tag_admissions').fetchone(), (1,))
        text = (self.audit_dir / 'tag-access.jsonl').read_text()
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual([row['status'] for row in rows], [102, 503, 102, 200, 102, 429])
        self.assertTrue(all(row['path'] == '/api/tags/:uid' for row in rows))
        for private in (*PRIVATE_VALUES, UID):
            self.assertNotIn(private, text)
            self.assertNotIn(private, response.text)

    def test_column_acl_denies_private_metadata_and_writes_without_readonly_option(self):
        self.grant_uid()
        web = {**self.owner, 'user': ROLE,
               'options': '-c default_transaction_read_only=off'}
        with psycopg.connect(**web) as connection:
            self.assertEqual(connection.execute('SHOW transaction_read_only').fetchone(), ('off',))
            self.assertEqual(connection.execute('SELECT current_user').fetchone(), (ROLE,))
            self.assertEqual(connection.execute(
                'SELECT serial,address,nfc_uid FROM public.wallets').fetchall(),
                [(SERIAL, ADDRESS, UID)])
            connection.commit()
            for column in PRIVATE_COLUMNS:
                with self.subTest(private_column=column):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege) as denied:
                        connection.execute('SELECT ' + column + ' FROM public.wallets')
                    self.assertEqual(denied.exception.sqlstate, '42501')
                    connection.rollback()
            statements = (
                'SELECT * FROM public.wallets',
                'UPDATE public.wallets SET address=address',
                'UPDATE public.wallets SET nfc_uid=nfc_uid',
                "INSERT INTO public.wallets (serial,address) VALUES ('SYNTH_NEW','SYNTH_ADDRESS')",
                'DELETE FROM public.wallets',
                'TRUNCATE public.wallets',
                'ALTER TABLE public.wallets ADD COLUMN synthetic_extra TEXT',
            )
            for statement in statements:
                with self.subTest(statement=statement):
                    self.assertEqual(connection.execute('SHOW transaction_read_only').fetchone(), ('off',))
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege) as denied:
                        connection.execute(statement)
                    self.assertEqual(denied.exception.sqlstate, '42501')
                    connection.rollback()
        with psycopg.connect(**self.owner) as connection:
            self.assertEqual(connection.execute('SELECT * FROM public.wallets').fetchall(),
                             [(SERIAL, ADDRESS, UID, *PRIVATE_VALUES)])
            grants = connection.execute(
                "SELECT column_name,privilege_type FROM information_schema.column_privileges "
                "WHERE grantee=%s AND table_schema='public' AND table_name='wallets'",
                (ROLE,)).fetchall()
            self.assertEqual(set(grants), {(column, 'SELECT') for column in ('serial', 'address', 'nfc_uid')})

    def test_unknown_tag_returns_not_found_without_chain_transport(self):
        self.grant_uid()
        response = self.client.get('/api/tags/11121314151617')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json, {'error': 'not_found'})
        self.assertEqual(self.requests, [])
        self.assertEqual(self.module.database_lookup(SERIAL),
                         {'serial': SERIAL, 'address': ADDRESS})
        rows = [json.loads(line) for line in
                (self.audit_dir / 'tag-access.jsonl').read_text().splitlines()]
        self.assertEqual([row['status'] for row in rows], [102, 404])


if __name__ == '__main__':
    unittest.main()

"""Offline public reverse lookup: synthetic records and disposable quota state."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ADDRESS = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'
OTHER_ADDRESS = 'bc1qzmtrqsfuaf6l6kkcsseumq26ukaphfj9skkug6'
SERIAL = 'TEST-DO-NOT-FUND-0587k45300'
PATH = '/api/addresses/' + ADDRESS


class AddressSerialLookup(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('address_serial_app', ROOT / 'app.py')
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.limiter = Mock()
        self.limiter.admit.return_value = 0
        self.lookup = Mock(return_value={'address': ADDRESS, 'serial': SERIAL,
                                        'notes': 'SYNTHETIC_PRIVATE'})
        self.market = Mock()
        self.activity = Mock()
        self.app = self.module.create_app({
            'TESTING': True, 'LOOKUP_LIMITER': self.limiter,
            'ADDRESS_LOOKUP': self.lookup, 'MARKET_SERVICE': self.market,
            'TAG_ACTIVITY': self.activity,
        })
        self.client = self.app.test_client()

    def assert_headers(self, response):
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['X-Robots-Tag'], 'noindex, nofollow, noarchive')

    def test_public_response_uses_registered_serial_and_fixed_origin(self):
        with patch.object(self.module, 'database_lookup') as database:
            response = self.client.get(PATH, base_url='https://untrusted.invalid', headers={
                'X-Forwarded-Host': 'other.invalid', 'X-Forwarded-Proto': 'http',
                'Forwarded': 'host=other.invalid;proto=http',
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'address': ADDRESS, 'serial': SERIAL,
                                        'lookup_url': 'https://btc4.fun/s/' + SERIAL})
        self.assert_headers(response)
        self.assertNotIn('SYNTHETIC_PRIVATE', response.text)
        self.lookup.assert_called_once_with(ADDRESS)
        self.limiter.admit.assert_called_once_with('127.0.0.1', 'address_' + ADDRESS, qr=False)
        self.assertIs(self.app.extensions['lookup_limiter'], self.limiter)
        database.assert_not_called()
        self.market.snapshot.assert_not_called()
        self.activity.snapshot.assert_not_called()


    def test_invalid_requests_precede_quota_database_secrets_and_providers(self):
        invalid = [ADDRESS.upper(), ADDRESS[:-1] + 'q', ' ' + ADDRESS, ADDRESS + '\n',
                   'bitcoin:' + ADDRESS, 'https://btc4.fun/s/' + SERIAL,
                   'tb1q' + ADDRESS[4:], 'bc1q' + 'q' * 58, 'bc1p' + 'q' * 58,
                   ADDRESS + '/qr.svg', "x' OR 1=1--", 'bc1q' + 'q' * 10000]
        paths = ['/api/addresses/' + quote(value, safe='') for value in invalid]
        paths += [PATH + query for query in (
            '?url=https://evil.invalid', '?lookup_url=https://evil.invalid',
            '?qr=1', '?after_txid=', '?unknown', '?a=1&a=2', '?%00=x', '?&')]
        with patch.object(self.module, 'database_lookup') as database, \
                patch.object(self.module.psycopg, 'connect') as connect, \
                patch.object(self.module.Path, 'read_text') as read:
            for path in paths:
                with self.subTest(path=path[:100]):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.json, {'error': 'invalid_address'})
                    self.assert_headers(response)
            self.limiter.admit.assert_not_called()
            self.lookup.assert_not_called()
            database.assert_not_called()
            connect.assert_not_called()
            read.assert_not_called()
        self.market.snapshot.assert_not_called()
        self.activity.snapshot.assert_not_called()


    def test_missing_and_untrusted_records_never_guess_a_serial(self):
        cases = [(None, 404, 'not_found'),
                 ({'address': OTHER_ADDRESS, 'serial': SERIAL}, 503, 'unavailable'),
                 ({'address': ADDRESS.upper(), 'serial': SERIAL}, 503, 'unavailable'),
                 ({'address': ADDRESS, 'serial': 'not-a-serial'}, 503, 'unavailable'),
                 ({'address': ADDRESS, 'serial': SERIAL + '\n'}, 503, 'unavailable'),
                 ({'address': ADDRESS, 'serial': None}, 503, 'unavailable'),
                 ({'address': ADDRESS, 'serial': 123}, 503, 'unavailable'),
                 ({'address': ADDRESS}, 503, 'unavailable'),
                 ({'serial': SERIAL}, 503, 'unavailable'),
                 (False, 503, 'unavailable')]
        for record, status, error in cases:
            with self.subTest(record=record):
                self.lookup.return_value = record
                response = self.client.get(PATH)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json, {'error': error})
                self.assert_headers(response)
        self.lookup.side_effect = RuntimeError('SYNTHETIC_PRIVATE_CONNECTION_DETAIL')
        with self.assertLogs(self.app.logger, level='WARNING') as logs:
            response = self.client.get(PATH)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {'error': 'unavailable'})
        self.assertNotIn('SYNTHETIC_PRIVATE', response.text + str(logs.output))


    def test_default_route_queries_only_public_columns_with_bound_address(self):
        del self.app.config['ADDRESS_LOOKUP']
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (SERIAL, ADDRESS)
        with patch.object(self.module.Path, 'read_text', return_value='SYNTHETIC_PASSWORD\n') as read, \
                patch.dict(os.environ, {'BTC_DB_USER': 'SYNTHETIC_USER'}), \
                patch.object(self.module.psycopg, 'connect', return_value=connection) as connect:
            response = self.client.get(PATH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'address': ADDRESS, 'serial': SERIAL,
                                        'lookup_url': 'https://btc4.fun/s/' + SERIAL})
        cursor.execute.assert_called_once_with(
            'SELECT serial, address FROM public.wallets WHERE address = %s LIMIT 1', (ADDRESS,))
        read.assert_called_once()
        self.assertTrue(connection.read_only)
        self.assertIn('default_transaction_read_only=on', connect.call_args.kwargs['options'])
        self.assertEqual(connect.call_args.kwargs['application_name'], 'bitcoin4fun-readonly')
        self.market.snapshot.assert_not_called()
        self.activity.snapshot.assert_not_called()

    def test_database_modes_are_allowlisted_and_ambiguous_flags_precede_secret_access(self):
        with patch.object(self.module.Path, 'read_text', return_value='SYNTHETIC_PASSWORD'), \
                patch.dict(os.environ, {'BTC_DB_USER': 'SYNTHETIC_USER'}), \
                patch.object(self.module.psycopg, 'connect') as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = (SERIAL, ADDRESS)
            for flags, column in (({}, 'serial'), ({'by_tag': True}, 'nfc_uid'),
                                  ({'by_address': True}, 'address')):
                with self.subTest(flags=flags):
                    cursor.execute.reset_mock()
                    value = "BOUND_ONLY' OR 1=1--"
                    row = self.module.database_lookup(value, **flags)
                    self.assertEqual(row, {'serial': SERIAL, 'address': ADDRESS})
                    cursor.execute.assert_called_once_with(
                        f'SELECT serial, address FROM public.wallets WHERE {column} = %s LIMIT 1', (value,))
            cursor.fetchone.return_value = None
            self.assertIsNone(self.module.database_lookup(ADDRESS, by_address=True))
        with patch.object(self.module.Path, 'read_text') as read, \
                patch.object(self.module.psycopg, 'connect') as connect:
            with self.assertRaises(ValueError):
                self.module.database_lookup(ADDRESS, by_tag=True, by_address=True)
            read.assert_not_called()
            connect.assert_not_called()


    def test_real_quota_is_shared_in_both_orders_without_address_qr_exemption(self):
        from lookup_limit import LookupLimiter
        for address_first in (False, True):
            with self.subTest(address_first=address_first), \
                    tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
                now = [1000.0]
                limiter = LookupLimiter(Path(directory) / 'quota.sqlite3',
                                        'SYNTHETIC_ADDRESS_QUOTA_SECRET_' * 2,
                                        clock=lambda: now[0])
                serial_lookup = Mock(return_value={'serial': SERIAL, 'address': ADDRESS})
                address_lookup = Mock(return_value={'serial': SERIAL, 'address': ADDRESS})
                app = self.module.create_app({'TESTING': True, 'LOOKUP_LIMITER': limiter,
                                              'ADDRESS_LOOKUP': address_lookup,
                                              'WALLET_LOOKUP': serial_lookup})
                client = app.test_client()
                serial_path = '/api/wallets/' + SERIAL
                first, second = (PATH, serial_path) if address_first else (serial_path, PATH)
                self.assertEqual(client.get(first).status_code, 200)
                for _ in range(4):
                    self.assertEqual(client.get(second).status_code, 200)
                self.assertIs(app.extensions['lookup_limiter'], limiter)
                now[0] = 1017
                for path in (PATH, serial_path, '/s/' + SERIAL, '/lookup?serial=' + SERIAL):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 429)
                    self.assertEqual(response.headers['Retry-After'], '43')
                    if path.startswith('/api/'):
                        self.assertEqual(response.json, {'error': 'rate_limited', 'retry_after': 43})
                        self.assert_headers(response)
                self.assertEqual(address_lookup.call_count, 1 if address_first else 4)
                self.assertEqual(serial_lookup.call_count, 4 if address_first else 1)
                # Existing serial QR companions remain free, not reverse lookups.
                self.assertEqual(client.get(serial_path + '/qr.svg').status_code, 200)
                self.assertEqual(client.get(PATH).status_code, 429)
                now[0] = 1060
                self.assertEqual(client.get(PATH).status_code, 200)

    def test_real_denied_and_broken_quota_cannot_read_secrets_or_connect(self):
        from lookup_limit import LookupLimiter
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            state = Path(directory) / 'quota.sqlite3'
            limiter = LookupLimiter(state, 'SYNTHETIC_ADDRESS_QUOTA_SECRET_' * 2, clock=lambda: 1000)
            for _ in range(5):
                self.assertEqual(limiter.admit('127.0.0.1', SERIAL), 0)
            app = self.module.create_app({'TESTING': True, 'LOOKUP_LIMITER': limiter,
                                          'MARKET_SERVICE': self.market, 'TAG_ACTIVITY': self.activity})
            client = app.test_client()
            # Leave production DB fallback intact: fail closed before it runs.
            with patch.object(self.module.Path, 'read_text') as read, \
                    patch.object(self.module.psycopg, 'connect') as connect:
                response = client.get(PATH)
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.json, {'error': 'rate_limited', 'retry_after': 60})
                self.assertEqual(response.headers['Retry-After'], '60')
                self.assert_headers(response)
                state.write_bytes(b'SYNTHETIC_CORRUPT_QUOTA')
                response = client.get(PATH)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json, {'error': 'unavailable'})
                self.assert_headers(response)
                read.assert_not_called()
                connect.assert_not_called()
            self.market.snapshot.assert_not_called()
            self.activity.snapshot.assert_not_called()

    def test_default_limiter_factory_is_shared_and_misses_consume_quota(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            environment = {'LOOKUP_STATE_FILE': str(Path(directory) / 'quota.sqlite3'),
                           'CONTACT_SECRET': 'SYNTHETIC_ADDRESS_FACTORY_SECRET_' * 2}
            with patch.dict(os.environ, environment):
                address_lookup = Mock(return_value=None)
                serial_lookup = Mock(return_value=None)
                app = self.module.create_app({'ADDRESS_LOOKUP': address_lookup, 'WALLET_LOOKUP': serial_lookup})
                client = app.test_client()
                for _ in range(4):
                    self.assertEqual(client.get(PATH).status_code, 404)
                limiter = app.extensions['lookup_limiter']
                self.assertEqual(client.get('/api/wallets/' + SERIAL).status_code, 404)
                self.assertIs(app.extensions['lookup_limiter'], limiter)
                self.assertEqual(client.get(PATH).status_code, 429)
                self.assertEqual(address_lookup.call_count, 4)
                serial_lookup.assert_called_once_with(SERIAL)

    def test_address_lookup_has_no_network_or_private_data_dependency(self):
        import socket
        private = {'mnemonic': 'SYNTHETIC_PRIVATE', 'private_key': 'SYNTHETIC_PRIVATE',
                   'nfc_uid': 'SYNTHETIC_PRIVATE', 'contact_type': 'SYNTHETIC_PRIVATE',
                   'contact_value': 'SYNTHETIC_PRIVATE', 'notes': 'SYNTHETIC_PRIVATE'}
        self.lookup.return_value.update(private)
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('No network')) as network, \
                patch.object(self.module.Path, 'read_text') as read, \
                patch.object(self.module.psycopg, 'connect') as connect:
            response = self.client.get(PATH)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.json), {'address', 'serial', 'lookup_url'})
            self.assertNotIn('SYNTHETIC_PRIVATE', response.text)
            network.assert_not_called()
            read.assert_not_called()
            connect.assert_not_called()
        self.market.snapshot.assert_not_called()
        self.activity.snapshot.assert_not_called()


if __name__ == '__main__':
    unittest.main()

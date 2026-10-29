from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock
from jinja2 import DictLoader

APP_PATH = Path(__file__).resolve().parents[1] / 'app.py'


class ApplicationContract(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('bitcoin4fun_app', APP_PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_health_is_available_without_database_or_network(self):
        self.assertTrue(APP_PATH.is_file(), 'website application has not been implemented')
        spec = importlib.util.spec_from_file_location('bitcoin4fun_app', APP_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app = module.create_app({'TESTING': True})
        response = app.test_client().get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'status': 'ok'})

    def test_serial_lookup_returns_only_public_fields(self):
        lookup = Mock(return_value={'serial': '0587k45300', 'address': 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu', 'mnemonic': 'MUST_NOT_LEAK'})
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lookup})
        response = app.test_client().get('/api/wallets/0587k45300')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {'serial', 'address', 'explorer_url'})
        self.assertNotIn('MUST_NOT_LEAK', response.text)
        lookup.assert_called_once_with('0587k45300')

    def test_invalid_serial_is_rejected_before_database_access(self):
        lookup = Mock()
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lookup})
        for serial in ['bad%27serial', 'a' * 65, '%3Cscript%3E', 'abc%0A', 'abc%20def']:
            with self.subTest(serial=serial):
                self.assertEqual(app.test_client().get('/api/wallets/' + serial).status_code, 400)
        lookup.assert_not_called()

    def test_missing_serial_and_database_failure_are_distinct(self):
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: None})
        self.assertEqual(app.test_client().get('/api/wallets/unknown').status_code, 404)
        app.config['WALLET_LOOKUP'] = Mock(side_effect=RuntimeError('PRIVATE_DSN_AND_PASSWORD'))
        response = app.test_client().get('/api/wallets/unknown')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE_DSN_AND_PASSWORD', response.text)

    def test_invalid_address_in_database_is_not_advertised_for_deposit(self):
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: {'serial': serial, 'address': 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyq'}})
        response = app.test_client().get('/api/wallets/invalidaddress')
        self.assertEqual(response.status_code, 503)


    def test_malformed_stored_addresses_are_rejected_before_checksum_decoding(self):
        from unittest.mock import patch
        for address in [None, 42, 'bc1q' + 'q' * 999996, 'bc1q' + 'q' * 39, 'bc1q' + '!' * 38]:
            with self.subTest(address_type=type(address).__name__):
                app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: {'serial': serial, 'address': address}})
                with patch.object(self.module, 'decode_segwit', return_value=(None, None)) as decoder:
                    response = app.test_client().get('/api/wallets/TEST-DO-NOT-FUND')
                self.assertEqual(response.status_code, 503)
                decoder.assert_not_called()

    def test_qr_is_generated_locally_from_verified_address(self):
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: {'serial': serial, 'address': 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'}})
        response = app.test_client().get('/api/wallets/0587k45300/qr.svg')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/svg+xml')
        self.assertIn('<svg', response.text)
        self.assertNotIn('<script', response.text)

    def test_lookup_form_has_server_rendered_result_without_javascript(self):
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: {'serial': serial, 'address': 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'}})
        app.jinja_loader = DictLoader({'lookup.html': '{{ wallet.address if wallet else "MISSING" }}'})
        response = app.test_client().get('/lookup?serial=0587k45300')
        self.assertEqual(response.status_code, 200)
        self.assertIn('bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu', response.text)

    def test_short_serial_pages_are_not_indexed(self):
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: None})
        app.jinja_loader = DictLoader({'lookup.html': 'public lookup'})
        for path in ['/shortserial', '/lookup', '/lookup?serial=shortserial']:
            with self.subTest(path=path):
                response = app.test_client().get(path)
                self.assertEqual(response.headers.get('X-Robots-Tag'), 'noindex, nofollow, noarchive')

    def test_security_headers_forbid_third_party_resources(self):
        response = self.module.create_app({'TESTING': True}).test_client().get('/healthz')
        self.assertIn("default-src 'none'", response.headers.get('Content-Security-Policy', ''))
        self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_all_pages_and_serial_shortcut_are_registered(self):
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: None})
        app.jinja_loader = DictLoader({name + '.html': '<html lang="fa" dir="rtl">{{ serial }}</html>' for name in ('index', 'guide', 'kids', 'terms', 'lookup')})
        for path in ['/', '/guide', '/kids', '/terms', '/lookup', '/s/0587k45300', '/0587k45300']:
            with self.subTest(path=path):
                response = app.test_client().get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('dir="rtl"', response.text)
        self.assertEqual(app.test_client().get('/no/such/page').status_code, 404)

    def test_database_query_uses_only_public_columns_bound_serial_and_readonly(self):
        from unittest.mock import patch
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w') as secret:
            secret.write('SYNTHETIC_PASSWORD')
            secret.flush()
            connection = Mock()
            cursor = Mock()
            connection.__enter__ = Mock(return_value=connection)
            connection.__exit__ = Mock(return_value=False)
            cursor.__enter__ = Mock(return_value=cursor)
            cursor.__exit__ = Mock(return_value=False)
            connection.cursor.return_value = cursor
            cursor.fetchone.return_value = ('abc', 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu')
            with patch.dict(os.environ, {'BTC_DB_PASSWORD_FILE': secret.name, 'BTC_DB_USER': 'SYNTHETIC_USER'}), patch.object(self.module.psycopg, 'connect', return_value=connection) as connect:
                row = self.module.database_lookup('abc')
            self.assertEqual(row['serial'], 'abc')
            cursor.execute.assert_called_once_with('SELECT serial, address FROM public.wallets WHERE serial = %s LIMIT 1', ('abc',))
            self.assertTrue(connection.read_only)
            self.assertIn('default_transaction_read_only=on', connect.call_args.kwargs['options'])


if __name__ == '__main__':
    unittest.main()

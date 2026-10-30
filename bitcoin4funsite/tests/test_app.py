from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
import sys
from unittest.mock import Mock
from jinja2 import DictLoader

APP_PATH = Path(__file__).resolve().parents[1] / 'app.py'
sys.path.insert(0, str(APP_PATH.parent))


class ApplicationContract(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('bitcoin4fun_app', APP_PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.real_create_app = self.module.create_app
        self.no_limit = Mock()
        self.no_limit.admit.return_value = 0
        def create_with_fixture(config=None):
            settings = dict(config or {})
            settings.setdefault('LOOKUP_LIMITER', self.no_limit)
            return self.real_create_app(settings)
        self.module.create_app = create_with_fixture

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
        lookup = Mock(return_value={'serial': '0587k45300', 'address': 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu', 'mnemonic': 'MUST_NOT_LEAK', 'contact_type': 'email', 'contact_value': 'SYNTHETIC_PRIVATE_CONTACT', 'notes': 'SYNTHETIC_PRIVATE_NOTES'})
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lookup})
        response = app.test_client().get('/api/wallets/0587k45300')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {'serial', 'address', 'explorer_url'})
        self.assertNotIn('MUST_NOT_LEAK', response.text)
        self.assertNotIn('SYNTHETIC_PRIVATE', response.text)
        lookup.assert_called_once_with('0587k45300')

    def test_original_wallet_example_images_are_never_publicly_served(self):
        app = self.module.create_app({'TESTING': True})
        import tempfile
        import os
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            app.static_folder = directory
            for name in ('privatekey.png', 'publickey.png'):
                (Path(directory) / name).write_bytes(b'SYNTHETIC_NONWALLET_FIXTURE')
            with app.test_client() as client:
                for name in ('privatekey.png', 'publickey.png'):
                    for path in ('/static/' + name, '/static/%70' + name[1:]):
                        with self.subTest(path=path):
                            with client.get(path) as response:
                                self.assertEqual(response.status_code, 404)

    def test_both_public_serial_url_forms_render_same_safe_record_without_js(self):
        serial = 'TEST-DO-NOT-FUND-0587k45300'
        address = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'
        lookup = Mock(return_value={'serial': serial, 'address': address, 'notes': 'PRIVATE_SENTINEL'})
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lookup})
        pages = []
        for base_url, path in (('https://btc4.fun', '/s/' + serial),
                               ('https://go.btc4.fun', '/' + serial)):
            response = app.test_client().get(path, base_url=base_url)
            self.assertEqual(response.status_code, 200)
            self.assertIn(address, response.text)
            self.assertIn(serial, response.text)
            self.assertNotIn('PRIVATE_SENTINEL', response.text)
            self.assertEqual(response.headers['X-Robots-Tag'], 'noindex, nofollow, noarchive')
            pages.append(response.text)
        self.assertEqual(pages[0], pages[1])
        self.assertEqual(lookup.call_count, 2)

    def test_invalid_serial_is_rejected_before_database_access(self):
        lookup = Mock()
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lookup})
        for serial in ['bad%27serial', 'a' * 65, '%3Cscript%3E', 'abc%0A', 'abc%20def']:
            with self.subTest(serial=serial):
                self.assertEqual(app.test_client().get('/api/wallets/' + serial).status_code, 400)
        lookup.assert_not_called()

    def test_serial_rate_limit_precedes_database_and_is_shared_by_all_routes(self):
        limiter = Mock()
        limiter.admit.side_effect = [0, 14, 13, 12]
        lookup = Mock(return_value=None)
        app = self.real_create_app({'TESTING': True, 'WALLET_LOOKUP': lookup, 'LOOKUP_LIMITER': limiter})
        client = app.test_client()
        self.assertEqual(client.get('/api/wallets/First0587k45300').status_code, 404)
        for path in ('/s/Second0587k45300', '/Second0587k45300', '/lookup?serial=Second0587k45300'):
            response = client.get(path)
            self.assertEqual(response.status_code, 429)
            self.assertIn('Retry-After', response.headers)
            self.assertIn('پنج استعلام در شصت ثانیه', response.text)
            self.assertIn('data-retry-after="' + response.headers['Retry-After'] + '"', response.text)
        lookup.assert_called_once_with('First0587k45300')
        self.assertEqual(limiter.admit.call_count, 4)

    def test_api_rate_limit_and_failure_are_sanitized_and_fail_closed(self):
        limiter = Mock()
        limiter.admit.return_value = 15
        lookup = Mock()
        app = self.real_create_app({'TESTING': True, 'WALLET_LOOKUP': lookup, 'LOOKUP_LIMITER': limiter})
        response = app.test_client().get('/api/wallets/First0587k45300')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json, {'error': 'rate_limited', 'retry_after': 15})
        self.assertEqual(response.headers['Retry-After'], '15')
        limiter.admit.side_effect = RuntimeError('PRIVATE_RATE_STATE')
        response = app.test_client().get('/api/wallets/First0587k45300')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE_RATE_STATE', response.text)
        lookup.assert_not_called()

    def test_lookup_rate_identity_uses_trusted_last_proxy_hop_and_qr_flag(self):
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: None})
        client = app.test_client()
        client.get('/api/wallets/First0587k45300', headers={'X-Forwarded-For': '192.0.2.99, 198.51.100.8'})
        self.no_limit.admit.assert_called_with('198.51.100.8', 'First0587k45300', qr=False)
        client.get('/api/wallets/First0587k45300/qr.svg', headers={'X-Forwarded-For': '198.51.100.8'})
        self.no_limit.admit.assert_called_with('198.51.100.8', 'First0587k45300', qr=True)
        client.get('/api/wallets/First0587k45300', environ_overrides={'REMOTE_ADDR': '8.8.8.8'},
                   headers={'X-Forwarded-For': '192.0.2.99'})
        self.no_limit.admit.assert_called_with('8.8.8.8', 'First0587k45300', qr=False)

    def test_missing_serial_and_database_failure_are_distinct(self):
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: None})
        self.assertEqual(app.test_client().get('/api/wallets/unknown0587k45300').status_code, 404)
        app.config['WALLET_LOOKUP'] = Mock(side_effect=RuntimeError('PRIVATE_DSN_AND_PASSWORD'))
        response = app.test_client().get('/api/wallets/unknown0587k45300')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE_DSN_AND_PASSWORD', response.text)

    def test_website_uses_the_shared_address_validation_contract(self):
        import address_validation
        self.assertIs(getattr(self.module, 'valid_address', None), address_validation.valid_address)

    def test_invalid_address_in_database_is_not_advertised_for_deposit(self):
        app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: {'serial': serial, 'address': 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyq'}})
        response = app.test_client().get('/api/wallets/invalidaddress0587k45300')
        self.assertEqual(response.status_code, 503)


    def test_malformed_stored_addresses_are_rejected_before_checksum_decoding(self):
        from unittest.mock import patch
        for address in [None, 42, 'bc1q' + 'q' * 999996, 'bc1q' + 'q' * 39, 'bc1q' + '!' * 38]:
            with self.subTest(address_type=type(address).__name__):
                app = self.module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: {'serial': serial, 'address': address}})
                decoder = Mock(return_value=0)
                # Patch the actual shared function's checksum seam, independent
                # of standalone/package import names and discovery sys.path order.
                with patch.dict(self.module.valid_address.__globals__, bech32_polymod=decoder):
                    response = app.test_client().get('/api/wallets/TEST-DO-NOT-FUND-0587k45300')
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
        for path in ['/shortserial0587k45300', '/lookup', '/lookup?serial=shortserial0587k45300']:
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

    def test_new_public_pages_work_without_market_access(self):
        market = Mock()
        app = self.module.create_app({'TESTING': True, 'MARKET_SERVICE': market})
        app.jinja_loader = DictLoader({name + '.html': name for name in ('satoshi', 'costs', 'contact')})
        for path in ['/satoshi', '/costs', '/contact']:
            self.assertEqual(app.test_client().get(path).status_code, 200)
        market.snapshot.assert_not_called()

    def test_market_unavailable_returns_no_fabricated_quote_or_secrets(self):
        service = Mock()
        service.snapshot.side_effect = RuntimeError('SYNTHETIC_PRIVATE_TOKEN')
        app = self.module.create_app({'TESTING': True, 'MARKET_SERVICE': service})
        response = app.test_client().get('/api/market')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {'error': 'market_unavailable'})
        self.assertNotIn('SYNTHETIC', response.text)

    def test_terms_short_alias_is_the_same_page(self):
        client = self.module.create_app({'TESTING': True}).test_client()
        self.assertEqual(client.get('/t').data, client.get('/terms').data)

    def test_market_endpoint_integrates_exact_quotes_and_only_public_fields(self):
        service = Mock()
        service.snapshot.return_value = {
            'status': 'stale', 'fetched_at': '2026-10-29T20:00:00+00:00',
            'raw_prices': {'btc_toman': '21000000000', 'usdt_toman': '270000'},
            'fee_rate': '1', 'source': {'prices': 'https://swapwallet.app/api/v1/market/prices', 'fees': 'https://mempool.space/api/v1/fees/recommended'},
            'private_unused': 'SYNTHETIC_PRIVATE_TOKEN',
        }
        app = self.module.create_app({'TESTING': True, 'MARKET_SERVICE': service})
        response = app.test_client().get('/api/market')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'stale')
        self.assertEqual(response.json['rates']['btc_toman'], '21105000000')
        self.assertIn('raw_rates', response.json)
        self.assertEqual(response.json['raw_rates'], {'btc_toman': '21000000000', 'usdt_toman': '270000'})
        self.assertEqual(response.json['rows'][0]['principal_sats'], 500)
        self.assertEqual(response.json['rows'][0]['total_rial'], response.json['rows'][0]['total_toman'] * 10)
        self.assertNotIn('SYNTHETIC', response.text)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_contact_forwarded_ip_uses_last_proxy_hop_not_spoofed_first(self):
        service = Mock()
        app = self.module.create_app({'TESTING': True, 'CONTACT_SERVICE': service})
        client = app.test_client()
        client.post('/contact', data={'message': 'Public test'}, headers={'X-Forwarded-For': '198.51.100.66, 203.0.113.4'})
        self.assertEqual(service.submit.call_args.args[1], '203.0.113.4')
        service.reset_mock()
        client.post('/contact', data={'message': 'Public test'}, headers={'X-Forwarded-For': '198.51.100.66'}, environ_overrides={'REMOTE_ADDR': '8.8.8.8'})
        self.assertEqual(service.submit.call_args.args[1], '8.8.8.8')

    def test_contact_normalizes_native_textarea_newlines_before_validation(self):
        service = Mock()
        app = self.module.create_app({'TESTING': True, 'CONTACT_SERVICE': service})
        response = app.test_client().post('/contact', data={'name': 'TEST', 'mobile': '', 'message': 'Line one\r\nLine two', 'csrf_token': 'SYNTHETIC', 'website': ''})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(service.submit.call_args.args[0]['message'], 'Line one\nLine two')

    def test_contact_referrer_policy_keeps_native_same_origin_post_working(self):
        client = self.module.create_app({'TESTING': True}).test_client()
        self.assertEqual(client.get('/contact').headers['Referrer-Policy'], 'same-origin')
        self.assertEqual(client.get('/lookup').headers['Referrer-Policy'], 'no-referrer')

    def test_contact_post_uses_server_service_and_redirects_after_success(self):
        service = Mock()
        service.token.return_value = 'SYNTHETIC_FORM_TOKEN'
        service.submit.return_value = {'id': 'SYNTHETIC_MESSAGE_ID'}
        app = self.module.create_app({'TESTING': True, 'CONTACT_SERVICE': service})
        client = app.test_client()
        form = {'name': 'TEST-DO-NOT-FUND', 'mobile': '', 'message': 'Public test only', 'csrf_token': 'SYNTHETIC_FORM_TOKEN', 'website': ''}
        response = client.post('/contact', data=form, headers={'Origin': 'https://btc4.fun', 'X-Forwarded-For': '198.51.100.23'})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['Location'], '/contact?sent=1')
        service.submit.assert_called_once()
        self.assertEqual(dict(service.submit.call_args.args[0]), form)
        self.assertEqual(service.submit.call_args.args[1], '198.51.100.23')
        self.assertNotIn('SYNTHETIC_MESSAGE_ID', response.text)

    def test_contact_rejects_foreign_origin_nonform_and_oversize_before_notification(self):
        service = Mock()
        app = self.module.create_app({'TESTING': True, 'CONTACT_SERVICE': service})
        client = app.test_client()
        self.assertEqual(client.post('/contact', data={'message': 'x'}, headers={'Origin': 'https://evil.invalid'}).status_code, 403)
        self.assertEqual(client.post('/contact', json={'message': 'x'}).status_code, 415)
        self.assertEqual(client.post('/contact', data={'message': 'x' * 20000}).status_code, 413)
        service.submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()

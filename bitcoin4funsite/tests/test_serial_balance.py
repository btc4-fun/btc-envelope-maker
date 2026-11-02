"""Synthetic serial balance flow; no real database or upstream calls."""
from unittest.mock import Mock
import unittest

from test_lookup_flow import load_app, ADDRESS, SERIALS
from test_chain_activity import FakeHTTP, stats, ORIGIN
from chain_activity import ChainActivity

SERIAL = SERIALS[0]


class SerialBalance(unittest.TestCase):
    def fixture(self, *bodies):
        http = FakeHTTP(*(bodies or (stats(),)))
        lookup = Mock(return_value={'serial': SERIAL, 'address': ADDRESS})
        limiter = Mock()
        limiter.admit.return_value = 0
        app = load_app().create_app({'TESTING': True, 'WALLET_LOOKUP': lookup,
                                    'LOOKUP_LIMITER': limiter,
                                    'SERIAL_BALANCE': ChainActivity(request_bytes=http, clock=lambda: 1000)})
        return app.test_client(), lookup, limiter, http

    def test_explicit_balance_admits_once_reads_mapping_once_and_fetches_no_history(self):
        client, lookup, limiter, http = self.fixture()
        response = client.get('/api/wallets/' + SERIAL + '?balance=1', headers={
            'X-Forwarded-For': '192.0.2.99', 'Cookie': 'synthetic=private'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('balance', response.json)
        self.assertEqual(response.json['balance'], {
            'address': ADDRESS, 'confirmed_sats': 500, 'pending_delta_sats': -50,
            'source': ORIGIN, 'fetched_at': '1970-01-01T00:16:40+00:00'})
        self.assertEqual(set(response.json), {'serial', 'address', 'explorer_url', 'balance'})
        lookup.assert_called_once_with(SERIAL)
        limiter.admit.assert_called_once_with('127.0.0.1', SERIAL, qr=False)
        self.assertEqual(http.calls, [(ORIGIN + '/address/' + ADDRESS, {
            'headers': {'Accept': 'application/json'}, 'max_bytes': 262144, 'timeout': 4})])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')


    def test_ordinary_aliases_qr_and_reverse_never_fetch_balance(self):
        client, lookup, limiter, http = self.fixture()
        client.application.config['ADDRESS_LOOKUP'] = Mock(return_value={'serial': SERIAL, 'address': ADDRESS})
        for path in ('/lookup', '/lookup?serial=' + SERIAL, '/s/' + SERIAL, '/' + SERIAL,
                     '/api/wallets/' + SERIAL, '/api/wallets/' + SERIAL + '/qr.svg',
                     '/api/addresses/' + ADDRESS):
            self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(set(client.get('/api/wallets/' + SERIAL).json),
                         {'serial', 'address', 'explorer_url'})
        self.assertEqual(http.calls, [])

    def test_denied_invalid_missing_and_corrupt_mapping_never_fetch(self):
        for case, expected in (('limited', 429), ('state_error', 503), ('invalid', 400),
                               ('missing', 404), ('bad_address', 503), ('database', 503)):
            client, lookup, limiter, http = self.fixture()
            serial = SERIAL
            if case == 'limited': limiter.admit.return_value = 43
            if case == 'state_error': limiter.admit.side_effect = RuntimeError('synthetic')
            if case == 'invalid': serial = 'invalid!'
            if case == 'missing': lookup.return_value = None
            if case == 'bad_address': lookup.return_value = {'address': ADDRESS[:-1] + 'q'}
            if case == 'database': lookup.side_effect = RuntimeError('synthetic')
            response = client.get('/api/wallets/' + serial + '?balance=1')
            with self.subTest(case=case):
                self.assertEqual(response.status_code, expected)
                self.assertEqual(http.calls, [])
                if case in ('limited', 'state_error', 'invalid'):
                    lookup.assert_not_called()
                if case == 'invalid': limiter.admit.assert_not_called()
                if case == 'limited': self.assertEqual(response.headers['Retry-After'], '43')

    def test_real_zero_is_not_an_error_and_native_aliases_fetch_once(self):
        zero = stats(0, 0)
        zero['mempool_stats'] = {'funded_txo_sum': 0, 'spent_txo_sum': 0}
        for path in ('/api/wallets/' + SERIAL, '/s/' + SERIAL, '/' + SERIAL,
                     '/lookup?serial=' + SERIAL):
            client, lookup, limiter, http = self.fixture(zero)
            response = client.get(path + ('&' if '?' in path else '?') + 'balance=1')
            self.assertEqual(response.status_code, 200)
            if path.startswith('/api/'):
                self.assertEqual(response.json['balance']['confirmed_sats'], 0)
                self.assertEqual(response.json['balance']['pending_delta_sats'], 0)
            else:
                self.assertIn('0.00000000', response.text)
            lookup.assert_called_once_with(SERIAL)
            limiter.admit.assert_called_once_with('127.0.0.1', SERIAL, qr=False)
            self.assertEqual(len(http.calls), 1)

    def test_options_are_strict_and_rejected_before_admission(self):
        for base in ('/api/wallets/' + SERIAL, '/s/' + SERIAL, '/' + SERIAL,
                     '/lookup?serial=' + SERIAL):
            for query in ('balance=0', 'balance=', 'balance=true', 'balance=1&balance=1',
                          'balance=1&address=' + ADDRESS, 'unknown=1', 'balance=1&after_txid=x'):
                client, lookup, limiter, http = self.fixture()
                response = client.get(base + ('&' if '?' in base else '?') + query)
                with self.subTest(base=base, query=query):
                    self.assertEqual(response.status_code, 400)
                    lookup.assert_not_called()
                    limiter.admit.assert_not_called()
                    self.assertEqual(http.calls, [])
        client, lookup, limiter, http = self.fixture()
        for path in ('/lookup?serial=' + SERIAL + '&serial=' + SERIAL + '&balance=1',
                     '/lookup?balance=1', '/api/wallets/' + SERIAL + '/qr.svg?balance=1'):
            self.assertEqual(client.get(path).status_code, 400)
        lookup.assert_not_called()
        limiter.admit.assert_not_called()
        self.assertEqual(http.calls, [])

    def test_provider_failure_retains_mapping_without_inventing_zero(self):
        for body in (TimeoutError('SYNTHETIC_PRIVATE_ERROR'), b'broken', stats(0, 1)):
            client, lookup, limiter, http = self.fixture(body)
            response = client.get('/api/wallets/' + SERIAL + '?balance=1')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json, {'serial': SERIAL, 'address': ADDRESS,
                'explorer_url': 'https://mempool.space/address/' + ADDRESS,
                'balance_error': 'unavailable'})
            self.assertNotIn('SYNTHETIC_PRIVATE_ERROR', response.text)
            self.assertEqual(len(http.calls), 1)

    def test_native_balance_error_retains_address_and_qr(self):
        client, lookup, limiter, http = self.fixture(TimeoutError())
        response = client.get('/lookup?serial=' + SERIAL + '&balance=1')
        self.assertEqual(response.status_code, 503)
        self.assertIn(ADDRESS, response.text)
        self.assertIn('/api/wallets/' + SERIAL + '/qr.svg', response.text)
        self.assertEqual(len(http.calls), 1)


if __name__ == '__main__':
    unittest.main()

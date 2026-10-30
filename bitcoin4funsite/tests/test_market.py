from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'market.py'


class MarketContract(unittest.TestCase):
    def load(self):
        self.assertTrue(PATH.is_file(), 'server-side market service missing')
        spec = importlib.util.spec_from_file_location('btc4fun_market', PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_reads_only_required_public_prices_and_economy_fee(self):
        module = self.load()
        requests = []
        def fetch(url, token=None):
            requests.append((url, token is not None))
            if 'swapwallet' in url:
                return {'result': {'BTC/IRT': '21000000000', 'USDT/IRT': '270000', 'PRIVATE_UNUSED': 'never output'}}
            return {'economyFee': 1, 'minimumFee': 1, 'fastestFee': 10}
        service = module.MarketService(fetch=fetch, token_loader=lambda: 'SYNTHETIC', clock=lambda: 1000)
        data = service.snapshot()
        self.assertEqual(data['status'], 'fresh')
        self.assertEqual(data['raw_prices'], {'btc_toman': '21000000000', 'usdt_toman': '270000'})
        self.assertEqual(data['fee_rate'], '1')
        self.assertNotIn('SYNTHETIC', repr(data))
        self.assertNotIn('PRIVATE_UNUSED', repr(data))
        self.assertEqual(requests, [(module.PRICE_URL, True), (module.FEE_URL, False)])

    def test_cache_avoids_repeated_requests_and_marks_stale_before_expiry(self):
        module = self.load()
        now = [1000]
        calls = []
        failing = [False]
        def fetch(url, token=None):
            calls.append(url)
            if failing[0]:
                raise RuntimeError('SYNTHETIC_SECRET_MUST_NOT_ESCAPE')
            return {'result': {'BTC/IRT': '21000000000', 'USDT/IRT': '270000'}} if url == module.PRICE_URL else {'economyFee': 1}
        service = module.MarketService(fetch=fetch, token_loader=lambda: 'SYNTHETIC', clock=lambda: now[0])
        first = service.snapshot()
        service.snapshot()
        self.assertEqual(len(calls), 2)
        failing[0] = True
        now[0] = 1061
        stale = service.snapshot()
        self.assertEqual(stale['status'], 'stale')
        self.assertEqual(stale['fetched_at'], first['fetched_at'])
        count = len(calls)
        service.snapshot()
        self.assertEqual(len(calls), count, 'failure backoff must prevent request storms')
        now[0] = 1301
        with self.assertRaises(module.MarketUnavailable) as error:
            service.snapshot()
        self.assertNotIn('SYNTHETIC', str(error.exception))

    def test_failed_refresh_cannot_serve_cache_that_expires_during_fetch(self):
        module = self.load()
        now = [1000.0]
        failing = [False]
        def fetch(url, token=None):
            if failing[0]:
                now[0] += 4
                raise TimeoutError('synthetic failure')
            return {'result': {'BTC/IRT': '21000000000', 'USDT/IRT': '270000'}} if url == module.PRICE_URL else {'economyFee': 1}
        service = module.MarketService(fetch=fetch, token_loader=lambda: 'SYNTHETIC', clock=lambda: now[0])
        service.snapshot()
        failing[0] = True
        now[0] = 1299
        with self.assertRaises(module.MarketUnavailable):
            service.snapshot()
        self.assertEqual(now[0], 1303)

    def test_failure_backoff_starts_after_fetch_completion(self):
        module = self.load()
        now = [1000.0]
        calls = []
        def failing(url, token=None):
            calls.append(url)
            now[0] += 4
            raise TimeoutError('synthetic failure')
        service = module.MarketService(fetch=failing, token_loader=lambda: 'SYNTHETIC', clock=lambda: now[0])
        with self.assertRaises(module.MarketUnavailable):
            service.snapshot()
        now[0] = 1030
        with self.assertRaises(module.MarketUnavailable):
            service.snapshot()
        self.assertEqual(len(calls), 1, '30-second backoff must start at completion, not start')
        now[0] = 1034
        with self.assertRaises(module.MarketUnavailable):
            service.snapshot()
        self.assertEqual(len(calls), 2)

    def test_success_keeps_pre_refresh_timestamp_and_checks_freshness_at_completion(self):
        module = self.load()
        now = [1000.0]
        def fetch(url, token=None):
            now[0] += 4
            return {'result': {'BTC/IRT': '21000000000', 'USDT/IRT': '270000'}} if url == module.PRICE_URL else {'economyFee': 1}
        service = module.MarketService(fetch=fetch, token_loader=lambda: 'SYNTHETIC', clock=lambda: now[0])
        snapshot = service.snapshot()
        self.assertEqual(now[0], 1008)
        self.assertEqual(snapshot['fetched_at'], '1970-01-01T00:16:40+00:00')
        self.assertEqual(service._fetched, 1000)
        self.assertEqual(snapshot['status'], 'fresh')

    def test_invalid_prices_and_fees_never_enter_cache(self):
        module = self.load()
        for bad in ['NaN', 'Infinity', '-1', '0', True, '1e99', 'a' * 1000]:
            with self.subTest(bad=repr(bad)[:20]):
                service = module.MarketService(fetch=lambda url, token=None: {'result': {'BTC/IRT': bad, 'USDT/IRT': '270000'}} if url == module.PRICE_URL else {'economyFee': 1}, token_loader=lambda: 'SYNTHETIC')
                with self.assertRaises(module.MarketUnavailable):
                    service.snapshot()
        service = module.MarketService(fetch=lambda url, token=None: {'result': {'BTC/IRT': '21000000000', 'USDT/IRT': '270000'}} if url == module.PRICE_URL else {'economyFee': -1}, token_loader=lambda: 'SYNTHETIC')
        with self.assertRaises(module.MarketUnavailable):
            service.snapshot()

    def test_transport_preserves_allowlist_decimal_json_and_bounded_contract(self):
        module = self.load()
        from decimal import Decimal
        from unittest.mock import patch
        body = b'{"result":{"BTC/IRT":21000000000.123456,"USDT/IRT":270000.1}}'
        with patch.object(module._bounded_http, 'request_bytes', return_value=body) as request:
            result = module._fetch_json(module.PRICE_URL, 'SYNTHETIC')
            self.assertEqual(result['result']['BTC/IRT'], Decimal('21000000000.123456'))
            request.assert_called_once_with(module.PRICE_URL, headers={
                'Accept': 'application/json', 'User-Agent': 'btc4fun/1', 'Authorization': 'Bearer SYNTHETIC',
            }, max_bytes=262144, timeout=4)
        with patch.object(module._bounded_http, 'request_bytes') as request:
            for url, token in [('https://other.invalid/', None), (module.FEE_URL, 'SYNTHETIC')]:
                with self.assertRaises(module.MarketUnavailable):
                    module._fetch_json(url, token)
            request.assert_not_called()
        for status in [301, 302, 303, 307, 308]:
            with self.assertRaises(module.MarketUnavailable):
                module.NoRedirect().redirect_request(None, None, status, 'moved', {}, 'https://elsewhere.invalid')
        for body in [b'not-json', b'\xff']:
            with patch.object(module._bounded_http, 'request_bytes', return_value=body):
                with self.assertRaises(module.MarketUnavailable):
                    module._fetch_json(module.PRICE_URL)
        with patch.object(module._bounded_http, 'request_bytes', side_effect=RuntimeError('SYNTHETIC_PRIVATE_ERROR')):
            with self.assertRaises(module.MarketUnavailable) as error:
                module._fetch_json(module.PRICE_URL)
            self.assertNotIn('SYNTHETIC', str(error.exception))


if __name__ == '__main__':
    unittest.main()

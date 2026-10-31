"""Offline Esplora contract fixtures: never query any address on a network."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'chain_activity.py'
ADDRESS = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'
OTHER = 'bc1qzmtrqsfuaf6l6kkcsseumq26ukaphfj9skkug6'
ORIGIN = 'https://blockstream.info/api'
SUPPLY = 21_000_000 * 100_000_000


def stats(funded=900, spent=400):
    return {'address': ADDRESS,
            'chain_stats': {'funded_txo_sum': funded, 'spent_txo_sum': spent},
            'mempool_stats': {'funded_txo_sum': 50, 'spent_txo_sum': 100}}


def transaction(index=1, *, coinbase=False):
    return {'txid': format(index, '064x'),
            'status': {'confirmed': True, 'block_height': 100, 'block_time': 1231006505},
            'vin': [{'is_coinbase': coinbase, 'prevout': None if coinbase else
                     {'scriptpubkey_address': ADDRESS, 'value': 600}}],
            'vout': [{'scriptpubkey_address': ADDRESS, 'value': 200},
                     {'scriptpubkey_address': OTHER, 'value': 300},
                     {'value': 0}], 'unused': 'never return raw upstream data'}


class FakeHTTP:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, bytes) else json.dumps(value).encode()


class ChainActivityContract(unittest.TestCase):
    def load(self):
        self.assertTrue(PATH.is_file(), 'bounded chain activity adapter missing')
        spec = importlib.util.spec_from_file_location('btc4fun_chain_activity', PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_confirmed_page_has_only_public_deltas_and_continuation(self):
        module = self.load()
        page = [transaction(i) for i in range(1, 26)]
        page[0] = transaction(1, coinbase=True)
        http = FakeHTTP(stats(), page, stats(), [transaction(26)], stats(), [])
        service = module.ChainActivity(request_bytes=http, clock=lambda: 1000)
        first = service.snapshot(ADDRESS)
        self.assertEqual(first['transactions'][0], {
            'txid': format(1, '064x'), 'confirmed': True,
            'block_height': 100, 'block_time': 1231006505, 'delta_sats': 200})
        self.assertEqual(first['transactions'][1]['delta_sats'], -400)
        self.assertEqual(len(first['transactions']), 25)
        self.assertEqual(first['next_after_txid'], format(25, '064x'))
        self.assertNotIn('unused', repr(first))
        second = service.snapshot(ADDRESS, first['next_after_txid'])
        self.assertNotIn('next_after_txid', second)
        self.assertEqual(http.calls[3][0], ORIGIN + '/address/' + ADDRESS + '/txs/chain/' + format(25, '064x'))
        last = service.snapshot(ADDRESS, format(26, '064x'))
        self.assertEqual(last['transactions'], [])
        self.assertNotIn('next_after_txid', last)

    def test_transport_and_json_fail_closed_without_private_error_details(self):
        module = self.load()
        self.assertTrue(hasattr(module, 'ChainActivityUnavailable'))
        bad_bodies = [TimeoutError('SYNTHETIC_PRIVATE_ERROR'),
                      RuntimeError('SYNTHETIC_PRIVATE_ERROR'), b'not-json', b'\xff',
                      b'[]' + b' ' * 262143, b'{"a":1,"a":2}',
                      b'{"a":NaN}', b'{"a":Infinity}',
                      b'[' * 2000 + b']' * 2000]
        for body in bad_bodies:
            for position in (0, 1):
                with self.subTest(body=repr(body)[:60], position=position):
                    http = FakeHTTP(body, []) if position == 0 else FakeHTTP(stats(), body)
                    with self.assertRaises(module.ChainActivityUnavailable) as caught:
                        module.ChainActivity(request_bytes=http).snapshot(ADDRESS)
                    self.assertEqual(str(caught.exception), 'Chain activity temporarily unavailable')
                    self.assertTrue(caught.exception.__suppress_context__)
                    self.assertEqual(len(http.calls), position + 1)

    def test_stats_validate_consumed_fields_and_allow_lifetime_turnover(self):
        module = self.load()
        good = stats(10 * SUPPLY + 500, 10 * SUPPLY)
        good['mempool_stats'] = {'funded_txo_sum': 2 * SUPPLY + 100,
                                 'spent_txo_sum': 2 * SUPPLY}
        result = module.ChainActivity(request_bytes=FakeHTTP(good, [])).snapshot(ADDRESS)
        self.assertEqual(result['confirmed_sats'], 500)
        self.assertEqual(result['pending_delta_sats'], 100)
        invalid = [None, [], {}, {'address': ADDRESS}, stats(0, 1),
                   stats(SUPPLY + 1, 0), stats(2 ** 64, 2 ** 64 - 1)]
        for field in ('address', 'chain_stats', 'mempool_stats'):
            for value in (None, True, 10, [], '', OTHER):
                changed = stats()
                changed[field] = value
                invalid.append(changed)
        for group in ('chain_stats', 'mempool_stats'):
            for key in ('funded_txo_sum', 'spent_txo_sum'):
                for value in (None, True, False, -1, '1', 1.0, 2 ** 64, [], {}):
                    changed = stats()
                    changed[group][key] = value
                    invalid.append(changed)
                changed = stats()
                del changed[group][key]
                invalid.append(changed)
        for funded, spent in ((SUPPLY + 1, 0), (0, SUPPLY + 1)):
            changed = stats()
            changed['mempool_stats'] = {'funded_txo_sum': funded, 'spent_txo_sum': spent}
            invalid.append(changed)
        for value in invalid:
            with self.subTest(value=value):
                http = FakeHTTP(value, [])
                with self.assertRaises(module.ChainActivityUnavailable):
                    module.ChainActivity(request_bytes=http).snapshot(ADDRESS)
                self.assertEqual(len(http.calls), 1, 'invalid balances must stop before history')

    def test_history_rejects_malformed_or_unbounded_consumed_fields(self):
        module = self.load()
        invalid = [None, {}, True, [transaction(i) for i in range(1, 27)],
                   [transaction(), transaction()], [None], [[]], [{}]]
        def changed(path, value):
            tx = transaction()
            node = tx
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
            invalid.append([tx])
        for value in (None, True, 42, 'a' * 63, 'a' * 65, 'A' * 64, 'g' * 64):
            changed(['txid'], value)
        for value in (None, [], True, {}):
            changed(['status'], value)
        for value in (None, 1, 0, 'true', False):
            changed(['status', 'confirmed'], value)
        for field in ('block_height', 'block_time'):
            for value in (None, True, -1, 1.5, '100', 2 ** 32):
                changed(['status', field], value)
        for field in ('vin', 'vout'):
            for value in (None, {}, True, [], [None], [{}], [0] * 10001):
                changed([field], value)
        for value in (None, 0, 1, 'false'):
            changed(['vin', 0, 'is_coinbase'], value)
        changed(['vin', 0, 'is_coinbase'], True)  # Non-null prevout on coinbase.
        for value in (None, [], True, {}):
            changed(['vin', 0, 'prevout'], value)
        for path in (['vout', 0], ['vout', 1], ['vin', 0, 'prevout']):
            for value in (None, True, -1, 1.0, '200', SUPPLY + 1):
                changed(path + ['value'], value)
            for value in (True, 1, [], {}, '', 'x' * 91, 'bad\naddress', 'é'):
                changed(path + ['scriptpubkey_address'], value)
        tx = transaction()
        tx['vout'] = [{'value': SUPPLY, 'scriptpubkey_address': ADDRESS}, {'value': 1}]
        invalid.append([tx])
        tx = transaction()
        tx['vin'] = [{'is_coinbase': False, 'prevout': {'value': SUPPLY, 'scriptpubkey_address': ADDRESS}},
                     {'is_coinbase': False, 'prevout': {'value': 1}}]
        invalid.append([tx])
        tx = transaction(coinbase=True)
        tx['vin'] *= 2
        invalid.append([tx])
        tx = transaction()
        tx['vin'].append({'is_coinbase': True, 'prevout': None})
        invalid.append([tx])
        tx = transaction()
        tx['vin'][0]['prevout']['scriptpubkey_address'] = OTHER
        tx['vout'][0]['scriptpubkey_address'] = OTHER
        invalid.append([tx])
        for value in invalid:
            with self.subTest(value=repr(value)[:180]):
                with self.assertRaises(module.ChainActivityUnavailable):
                    module.ChainActivity(request_bytes=FakeHTTP(stats(), value)).snapshot(ADDRESS)
        with self.assertRaises(module.ChainActivityUnavailable):
            module.ChainActivity(request_bytes=FakeHTTP(stats(), [transaction()])).snapshot(ADDRESS, format(1, '064x'))

    def test_non_coinbase_outputs_cannot_exceed_all_input_values(self):
        module = self.load()
        tx = transaction()
        tx['vout'][1]['value'] = 401
        with self.assertRaises(module.ChainActivityUnavailable):
            module.ChainActivity(request_bytes=FakeHTTP(stats(), [tx])).snapshot(ADDRESS)
        tx['vout'][1]['value'] = 400
        result = module.ChainActivity(request_bytes=FakeHTTP(stats(), [tx])).snapshot(ADDRESS)
        self.assertEqual(result['transactions'][0]['delta_sats'], -400)

    def test_default_transport_is_bounded_http_and_exact_byte_limit_is_allowed(self):
        module = self.load()
        body = json.dumps(stats()).encode()
        body += b' ' * (262144 - len(body))
        with patch.object(module._bounded_http, 'request_bytes', side_effect=[body, b'[]']) as http:
            result = module.ChainActivity().snapshot(ADDRESS)
        self.assertEqual(result['confirmed_sats'], 500)
        self.assertEqual(http.call_count, 2)
        for call in http.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 4)
            self.assertEqual(call.kwargs['max_bytes'], 262144)

    def test_zero_and_maximum_balances_are_real_validated_values(self):
        module = self.load()
        for amount in (0, SUPPLY):
            value = stats(amount, 0)
            value['mempool_stats'] = {'funded_txo_sum': 0, 'spent_txo_sum': 0}
            result = module.ChainActivity(request_bytes=FakeHTTP(value, [])).snapshot(ADDRESS)
            self.assertEqual(result['confirmed_sats'], amount)
            self.assertEqual(result['pending_delta_sats'], 0)

    def test_multiple_inputs_outputs_and_self_transfer_have_net_delta(self):
        module = self.load()
        tx = transaction()
        tx['vin'].append({'is_coinbase': False, 'prevout': {'value': 400, 'scriptpubkey_address': ADDRESS}})
        tx['vout'] = [{'value': 600, 'scriptpubkey_address': ADDRESS},
                      {'value': 400, 'scriptpubkey_address': ADDRESS},
                      {'value': 0, 'scriptpubkey_address': None}]
        result = module.ChainActivity(request_bytes=FakeHTTP(stats(), [tx])).snapshot(ADDRESS)
        self.assertEqual(result['transactions'][0]['delta_sats'], 0)

    def test_missing_consumed_history_fields_fail_closed(self):
        module = self.load()
        paths = [['txid'], ['status'], ['vin'], ['vout'], ['status', 'confirmed'],
                 ['status', 'block_height'], ['status', 'block_time'],
                 ['vin', 0, 'is_coinbase'], ['vin', 0, 'prevout'],
                 ['vin', 0, 'prevout', 'value'], ['vout', 0, 'value']]
        for path in paths:
            tx = transaction()
            node = tx
            for key in path[:-1]:
                node = node[key]
            del node[path[-1]]
            with self.subTest(path=path):
                with self.assertRaises(module.ChainActivityUnavailable):
                    module.ChainActivity(request_bytes=FakeHTTP(stats(), [tx])).snapshot(ADDRESS)

    def test_rejects_bad_address_and_cursor_before_any_fetch(self):
        module = self.load()
        invalid_addresses = [None, True, 42, '', ADDRESS.upper(), ADDRESS + '/txs',
                             ADDRESS[:-1] + 'q', 'https://example.com', 'x' * 100000]
        invalid_cursors = ['', True, 7, 'a' * 63, 'a' * 65, 'A' * 64,
                           'g' * 64, '../' + 'a' * 64, 'a' * 64 + '\n']
        for address, cursor in ([(a, None) for a in invalid_addresses] +
                                [(ADDRESS, c) for c in invalid_cursors]):
            with self.subTest(address=repr(address)[:60], cursor=cursor):
                http = FakeHTTP(stats(), [])
                with self.assertRaises(ValueError):
                    module.ChainActivity(request_bytes=http).snapshot(address, cursor)
                self.assertEqual(http.calls, [])

    def test_snapshot_separates_balances_and_labels_non_atomic_reads(self):
        module = self.load()
        http = FakeHTTP(stats(), [])
        clock_calls = []
        def clock():
            clock_calls.append(True)
            return 1000
        data = module.ChainActivity(request_bytes=http, clock=clock).snapshot(ADDRESS)
        self.assertEqual(data, {
            'address': ADDRESS, 'confirmed_sats': 500, 'pending_delta_sats': -50,
            'transactions': [], 'history_scope': 'confirmed_only',
            'mempool_scope': 'balance_only', 'consistency': 'non_atomic',
            'source': ORIGIN, 'fetched_at': '1970-01-01T00:16:40+00:00',
        })
        self.assertEqual(clock_calls, [True])
        self.assertEqual(http.calls, [
            (ORIGIN + '/address/' + ADDRESS,
             {'headers': {'Accept': 'application/json'}, 'max_bytes': 262144, 'timeout': 4}),
            (ORIGIN + '/address/' + ADDRESS + '/txs/chain',
             {'headers': {'Accept': 'application/json'}, 'max_bytes': 262144, 'timeout': 4}),
        ])
        self.assertEqual(json.loads(json.dumps(data)), data)


if __name__ == '__main__':
    unittest.main()

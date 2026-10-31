"""Bounded public Bitcoin activity, not a payment or spendability oracle.

Wire reference: https://github.com/Blockstream/esplora/blob/master/API.md
Use /address/:address for chain/mempool sums and /txs/chain for confirmed
history only, never the mixed /txs endpoint (50 mempool + 25 confirmed).
Reads are non-atomic, including between pages: confirmations/reorgs can change
results. fetched_at is one conservative local request-start UTC timestamp,
NOT a provider timestamp or a chain-tip consistency guarantee. Pending activity
is balance-only; coinbase maturity and spendability are not evaluated.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import time

# Match the site's standalone file-spec loading as well as package imports.
_http_spec = importlib.util.spec_from_file_location(
    'btc4fun_bounded_http', Path(__file__).resolve().with_name('bounded_http.py'))
assert _http_spec is not None and _http_spec.loader is not None
_bounded_http = importlib.util.module_from_spec(_http_spec)
_http_spec.loader.exec_module(_bounded_http)

_address_spec = importlib.util.spec_from_file_location(
    'btc4fun_address_validation', Path(__file__).resolve().with_name('address_validation.py'))
assert _address_spec is not None and _address_spec.loader is not None
_address_validation = importlib.util.module_from_spec(_address_spec)
_address_spec.loader.exec_module(_address_validation)

SOURCE = 'https://blockstream.info/api'
MAX_RESPONSE_BYTES = 262144
MAX_MONEY = 21_000_000 * 100_000_000
# Turnover is NOT a balance: coins can cycle through an address repeatedly.
MAX_TURNOVER = (1 << 64) - 1


class ChainActivityUnavailable(Exception):
    """Transport, bounds, or upstream schema failure; never a zero balance."""


def _reject_constant(value):
    raise ValueError('Non-finite JSON number')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def _valid_txid(value):
    return isinstance(value, str) and len(value) == 64 and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _integer(value, maximum, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid integer')
    return value


def _balances(data, address):
    if not isinstance(data, dict) or data['address'] != address:
        raise ValueError('Invalid address response')
    deltas = []
    for group in ('chain_stats', 'mempool_stats'):
        stat = data[group]
        funded = _integer(stat['funded_txo_sum'], MAX_TURNOVER)
        spent = _integer(stat['spent_txo_sum'], MAX_TURNOVER)
        deltas.append(_integer(funded - spent, MAX_MONEY,
                               0 if group == 'chain_stats' else -MAX_MONEY))
    return deltas


def _output(out, address):
    amount = _integer(out['value'], MAX_MONEY)
    target = out.get('scriptpubkey_address')
    # Counterparties can be legacy, Taproot, or other address kinds the site's
    # P2WPKH-only input validator does not accept. Non-address scripts omit it.
    if target is not None and (not isinstance(target, str) or not 1 <= len(target) <= 90
                               or re.fullmatch(r'[A-Za-z0-9]+', target) is None):
        raise ValueError('Invalid output address')
    return amount, target == address


def _transaction(tx, address):
    txid = tx['txid']
    if not _valid_txid(txid) or tx['status']['confirmed'] is not True:
        raise ValueError('Invalid confirmed transaction')
    result = {'txid': txid, 'confirmed': True,
              'block_height': _integer(tx['status']['block_height'], (1 << 32) - 1),
              'block_time': _integer(tx['status']['block_time'], (1 << 32) - 1)}
    inputs, outputs = tx['vin'], tx['vout']
    # Local complexity policy, not a claim about Bitcoin consensus limits.
    for items in (inputs, outputs):
        if not isinstance(items, list) or not 1 <= len(items) <= 10000:
            raise ValueError('Transaction complexity exceeded')
    incoming = outgoing = input_total = output_total = 0
    related = False
    for out in outputs:
        amount, matches = _output(out, address)
        output_total = _integer(output_total + amount, MAX_MONEY)
        if matches:
            incoming += amount
            related = True
    for vin in inputs:
        coinbase = vin['is_coinbase']
        if type(coinbase) is not bool:
            raise ValueError('Invalid coinbase flag')
        if coinbase:
            if len(inputs) != 1 or vin['prevout'] is not None:
                raise ValueError('Invalid coinbase input')
            continue
        amount, matches = _output(vin['prevout'], address)
        input_total = _integer(input_total + amount, MAX_MONEY)
        if matches:
            outgoing += amount
            related = True
    if not related:
        raise ValueError('Unrelated history transaction')
    if not inputs[0]['is_coinbase'] and output_total > input_total:
        raise ValueError('Invalid transaction sums')
    result['delta_sats'] = _integer(incoming - outgoing, MAX_MONEY, -MAX_MONEY)
    return result


def _history(transactions, address, after_txid):
    if not isinstance(transactions, list) or len(transactions) > 25:
        raise ValueError('Invalid history page')
    seen = {after_txid}
    result = []
    for tx in transactions:
        public = _transaction(tx, address)
        if public['txid'] in seen:
            raise ValueError('Repeated history transaction')
        seen.add(public['txid'])
        result.append(public)
    return result


class ChainActivity:
    """Two sequential GETs, no cache/retries or network work on construction.

    snapshot(address, after_txid=None) raises ValueError for caller input and
    ChainActivityUnavailable for any upstream/bounds failure. A full 25-item
    page supplies next_after_txid as a continuation candidate, NOT proof that
    another transaction exists; the next page may be empty. No result claims
    a complete history or an atomic balance/history view. No raw vin/vout or
    counterparties leave this adapter. request_bytes/clock are offline seams.
    """

    def __init__(self, request_bytes=None, clock=time.time):
        self.request_bytes = request_bytes or _bounded_http.request_bytes
        self.clock = clock

    def _fetch(self, path):
        try:
            body = self.request_bytes(
                SOURCE + path, headers={'Accept': 'application/json'},
                max_bytes=MAX_RESPONSE_BYTES, timeout=4)
            if type(body) is not bytes or len(body) > MAX_RESPONSE_BYTES:
                raise ValueError('Invalid response bytes')
            result = json.loads(body.decode('utf-8'), parse_constant=_reject_constant,
                                object_pairs_hook=_unique_object)
            pending = [(result, 0)]
            while pending:
                value, depth = pending.pop()
                if depth > 32:
                    raise ValueError('Excessive JSON nesting')
                if isinstance(value, (dict, list)):
                    children = value.values() if isinstance(value, dict) else value
                    pending.extend((child, depth + 1) for child in children)
            return result
        except Exception:
            raise ChainActivityUnavailable('Chain activity temporarily unavailable') from None

    def snapshot(self, address, after_txid=None):
        if not _address_validation.valid_address(address):
            raise ValueError('Invalid Bitcoin address')
        if after_txid is not None and not _valid_txid(after_txid):
            raise ValueError('Invalid history cursor')
        try:
            return self._snapshot(address, after_txid)
        except Exception:
            raise ChainActivityUnavailable('Chain activity temporarily unavailable') from None

    def _snapshot(self, address, after_txid):
        fetched_at = datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()
        path = '/address/' + address
        confirmed, pending = _balances(self._fetch(path), address)
        transactions = self._fetch(path + '/txs/chain' + ('/' + after_txid if after_txid else ''))
        result = {
            'address': address,
            'confirmed_sats': confirmed,
            'pending_delta_sats': pending,
            'transactions': _history(transactions, address, after_txid),
            'history_scope': 'confirmed_only', 'mempool_scope': 'balance_only',
            'consistency': 'non_atomic', 'source': SOURCE, 'fetched_at': fetched_at,
        }
        if len(transactions) == 25:
            result['next_after_txid'] = transactions[-1]['txid']
        return result

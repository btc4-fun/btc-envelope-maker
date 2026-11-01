from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.request

# Load the fixed sibling even when this module is loaded by file-spec without
# its directory on sys.path (the standalone offline tests use that mode).
_http_spec = importlib.util.spec_from_file_location('btc4fun_bounded_http', Path(__file__).resolve().with_name('bounded_http.py'))
assert _http_spec is not None and _http_spec.loader is not None
_bounded_http = importlib.util.module_from_spec(_http_spec)
_http_spec.loader.exec_module(_bounded_http)

PRICE_URL = 'https://swapwallet.app/api/v1/market/prices'
FEE_URL = 'https://mempool.space/api/v1/fees/recommended'
MAX_RESPONSE_BYTES = 262144


class MarketUnavailable(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MarketUnavailable('Market redirect refused')


def _fetch_json(url, token=None):
    if url not in {PRICE_URL, FEE_URL} or (token and url != PRICE_URL):
        raise MarketUnavailable('Market destination refused')
    headers = {'Accept': 'application/json', 'User-Agent': 'btc4fun/1'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        data = _bounded_http.request_bytes(url, headers=headers, max_bytes=MAX_RESPONSE_BYTES, timeout=4)
        return json.loads(data, parse_float=Decimal)
    except Exception:
        raise MarketUnavailable('Market information temporarily unavailable') from None


def _load_token():
    token = os.environ.get('SWAPWALLET_API_TOKEN', '')
    if not token or any(c in token for c in '\r\n'):
        raise MarketUnavailable('Market credentials unavailable')
    return token


def _positive_decimal(value, maximum):
    text = str(value)
    if isinstance(value, bool) or len(text) > 32 or re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', text) is None:
        raise MarketUnavailable('Invalid market value')
    number = Decimal(text)
    if not number.is_finite() or not 0 < number <= maximum:
        raise MarketUnavailable('Invalid market value')
    return format(number, 'f')


class MarketService:
    def __init__(self, fetch=_fetch_json, token_loader=_load_token, clock=time.time):
        self.fetch = fetch
        self.token_loader = token_loader
        self.clock = clock
        self._lock = threading.Lock()
        self._cached = None
        self._fetched = 0
        self._next_refresh = 0

    def snapshot(self):
        with self._lock:
            now = self.clock()
            if now >= self._next_refresh:
                try:
                    prices = self.fetch(PRICE_URL, self.token_loader())['result']
                    fees = self.fetch(FEE_URL)
                    result = {
                        'status': 'fresh',
                        'fetched_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                        'source': {'prices': PRICE_URL, 'fees': FEE_URL},
                        'raw_prices': {
                            'btc_toman': _positive_decimal(prices['BTC/IRT'], Decimal('1e15')),
                            'usdt_toman': _positive_decimal(prices['USDT/IRT'], Decimal('1e15')),
                        },
                        'fee_rate': _positive_decimal(fees['economyFee'], Decimal('10000')),
                    }
                    result['fee_rates'] = {'economy': result['fee_rate']}
                    for name, field in (('medium', 'halfHourFee'), ('fast', 'fastestFee')):
                        try:
                            rate = _positive_decimal(fees[field], Decimal('10000'))
                            if len(rate.partition('.')[2]) > 18:
                                raise MarketUnavailable('Invalid fee precision')
                            result['fee_rates'][name] = rate
                        except (KeyError, MarketUnavailable):
                            # Never substitute a different priority's recommendation.
                            result['fee_rates'][name] = None
                    self._cached = result
                    self._fetched = now
                    self._next_refresh = now + 60
                except Exception:
                    self._next_refresh = self.clock() + 30
            # Refresh can cross the cache lifetime even when the fetch fails.
            now = self.clock()
            if self._cached is None or not 0 <= now - self._fetched <= 300:
                raise MarketUnavailable('Market information temporarily unavailable')
            result = deepcopy(self._cached)
            result['status'] = 'fresh' if now - self._fetched < 60 else 'stale'
            return result

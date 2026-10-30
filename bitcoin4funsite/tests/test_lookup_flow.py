"""Real limiter and Flask route integration with synthetic local state only."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ADDRESS = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'
SERIALS = ('TEST-DO-NOT-FUND-0587k45300', '0587kTX0', '0587kTX100',
           'TEST-0587k45301', 'A_b-C0587kTX1000')


def aliases(serial):
    return ('/s/' + serial, '/' + serial, '/lookup?serial=' + serial,
            '/api/wallets/' + serial, '/api/wallets/' + serial + '/qr.svg')


def load_app():
    spec = importlib.util.spec_from_file_location('lookup_flow_app', ROOT / 'app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LookupAdmissionFlow(unittest.TestCase):
    def test_actual_gate_is_shared_across_aliases_and_keeps_all_qrs_working(self):
        from lookup_limit import LookupLimiter
        module = load_app()
        now = [1000.0]
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            limiter = LookupLimiter(state_file=str(Path(directory) / 'state.sqlite3'),
                                    secret='SYNTHETIC_LOOKUP_FLOW_SECRET_' * 2, clock=lambda: now[0])
            lookup = Mock(side_effect=lambda serial: {'serial': serial, 'address': ADDRESS})
            app = module.create_app({'TESTING': True, 'WALLET_LOOKUP': lookup, 'LOOKUP_LIMITER': limiter})
            client = app.test_client()
            for index, serial in enumerate(SERIALS):
                response = client.get(aliases(serial)[index], base_url=(
                    'https://btc4.fun' if index % 2 else 'https://go.btc4.fun'))
                self.assertEqual(response.status_code, 200)
                if index < 3:
                    self.assertIn('data-initial-state="found"', response.text)
                    self.assertIn(ADDRESS, response.text)
            for serial in SERIALS:
                self.assertEqual(client.get(aliases(serial)[-1]).status_code, 200)
            self.assertEqual(lookup.call_count, 10)
            now[0] = 1017
            for path in aliases('TEST-DO-NOT-FUND-0587k45302'):
                response = client.get(path, base_url='https://go.btc4.fun')
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.headers['Retry-After'], '43')
                if not path.startswith('/api/'):
                    self.assertIn('۴۳ ثانیه', response.text)
                    self.assertIn('۴۳ ثانیه', response.text.split('<noscript>')[1])
                else:
                    self.assertEqual(response.json, {'error': 'rate_limited', 'retry_after': 43})
            self.assertEqual(lookup.call_count, 10)
            now[0] = 1060
            self.assertEqual(client.get('/' + SERIALS[1]).status_code, 200)
            self.assertEqual(lookup.call_count, 11)

    def test_default_production_factory_enforces_limit_without_test_bypass(self):
        module = load_app()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            env = {'CONTACT_SECRET': 'SYNTHETIC_FACTORY_LOOKUP_SECRET_' * 2,
                   'LOOKUP_STATE_FILE': str(Path(directory) / 'factory.sqlite3')}
            with patch.dict(os.environ, env):
                lookup = Mock(return_value=None)
                app = module.create_app({'WALLET_LOOKUP': lookup})
                client = app.test_client()
                for _ in range(5):
                    self.assertEqual(client.get('/api/wallets/' + SERIALS[0]).status_code, 404)
                self.assertEqual(client.get('/api/wallets/' + SERIALS[0]).status_code, 429)
                self.assertEqual(lookup.call_count, 5)
                self.assertTrue(Path(env['LOOKUP_STATE_FILE']).is_file())

    def test_denial_and_broken_state_precede_real_wallet_secret_read_and_connect(self):
        from lookup_limit import LookupLimiter
        module = load_app()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            state = Path(directory) / 'state.sqlite3'
            limiter = LookupLimiter(state, 'SYNTHETIC_BOUNDARY_SECRET_' * 2, clock=lambda: 1000)
            for serial in SERIALS:
                self.assertEqual(limiter.admit('127.0.0.1', serial), 0)
            # No wallet override: the production DB function must remain unreachable.
            client = module.create_app({'TESTING': True, 'LOOKUP_LIMITER': limiter}).test_client()
            with patch.object(module.psycopg, 'connect') as connect, \
                    patch.object(module.Path, 'read_text', side_effect=AssertionError('secret read')) as read:
                for path in aliases('0587k45309'):
                    self.assertEqual(client.get(path).status_code, 429)
                state.write_bytes(b'synthetic broken state')
                for path in aliases('0587k45309'):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 503)
                    self.assertNotIn(str(state), response.text)
                connect.assert_not_called()
                read.assert_not_called()

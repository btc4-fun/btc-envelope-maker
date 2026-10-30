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


class LookupAdmissionFlow(unittest.TestCase):
    def test_actual_gate_is_shared_across_aliases_and_keeps_qr_working(self):
        from lookup_limit import LookupLimiter
        spec = importlib.util.spec_from_file_location('lookup_flow_app', ROOT / 'app.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        now = [1000.0]
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            limiter = LookupLimiter(state_file=str(Path(directory) / 'state.sqlite3'),
                                     secret='SYNTHETIC_LOOKUP_FLOW_SECRET_' * 2, clock=lambda: now[0])
            lookup = Mock(side_effect=lambda serial: {'serial': serial, 'address': ADDRESS})
            app = module.create_app({'TESTING': True, 'WALLET_LOOKUP': lookup, 'LOOKUP_LIMITER': limiter})
            client = app.test_client()
            response = client.get('/s/TEST-DO-NOT-FUND-ONE', base_url='https://btc4.fun')
            self.assertEqual(response.status_code, 200)
            self.assertIn('data-initial-state="found"', response.text)
            self.assertIn(ADDRESS, response.text)
            self.assertEqual(client.get('/api/wallets/TEST-DO-NOT-FUND-ONE/qr.svg').status_code, 200)
            self.assertEqual(lookup.call_count, 2)
            for path in ('/TEST-DO-NOT-FUND-TWO', '/lookup?serial=TEST-DO-NOT-FUND-TWO',
                         '/api/wallets/TEST-DO-NOT-FUND-TWO', '/api/wallets/TEST-DO-NOT-FUND-TWO/qr.svg'):
                response = client.get(path, base_url='https://go.btc4.fun')
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.headers['Retry-After'], '15')
            self.assertEqual(lookup.call_count, 2)
            now[0] += 15
            self.assertEqual(client.get('/TEST-DO-NOT-FUND-TWO').status_code, 200)
            self.assertEqual(lookup.call_count, 3)

    def test_default_production_factory_enforces_limit_without_test_bypass(self):
        spec = importlib.util.spec_from_file_location('lookup_factory_app', ROOT / 'app.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as directory:
            env = {'CONTACT_SECRET': 'SYNTHETIC_FACTORY_LOOKUP_SECRET_' * 2,
                   'LOOKUP_STATE_FILE': str(Path(directory) / 'factory.sqlite3')}
            with patch.dict(os.environ, env):
                app = module.create_app({'WALLET_LOOKUP': lambda serial: None})
                client = app.test_client()
                self.assertEqual(client.get('/api/wallets/TEST-DO-NOT-FUND').status_code, 404)
                self.assertEqual(client.get('/api/wallets/TEST-DO-NOT-FUND').status_code, 429)
                self.assertTrue(Path(env['LOOKUP_STATE_FILE']).is_file())

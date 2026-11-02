"""Synthetic peer provenance; no external calls."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app


class TrustedProxies(unittest.TestCase):
    def resolved(self, peer, forwarded, trusted=None):
        service = Mock()
        config = {'TESTING': True, 'CONTACT_SERVICE': service}
        if trusted is not None:
            config['TRUSTED_PROXIES'] = trusted
        with patch.dict('os.environ', {'TRUSTED_PROXIES': ''}):
            client = create_app(config).test_client()
        response = client.post('/contact', data={'message': 'synthetic'},
            headers={'Origin': 'https://btc4.fun', 'X-Forwarded-For': forwarded},
            environ_overrides={'REMOTE_ADDR': peer})
        self.assertEqual(response.status_code, 303)
        return service.submit.call_args.args[1]

    def test_private_peer_is_not_implicitly_trusted(self):
        self.assertEqual(self.resolved('10.0.0.2', '203.0.113.7'), '10.0.0.2')

    def test_explicit_peer_uses_last_valid_forwarded_address(self):
        self.assertEqual(self.resolved('10.0.0.2', '198.51.100.1, 203.0.113.7, invalid',
                                       '10.0.0.2/32'), '203.0.113.7')

    def test_nonlisted_peer_and_invalid_chain_use_peer(self):
        self.assertEqual(self.resolved('10.0.0.3', '203.0.113.7', '10.0.0.2/32'), '10.0.0.3')
        self.assertEqual(self.resolved('10.0.0.2', 'invalid', '10.0.0.2/32'), '10.0.0.2')

    def test_invalid_proxy_configuration_fails_at_startup(self):
        with self.assertRaises(ValueError):
            create_app({'TRUSTED_PROXIES': 'not-an-address'})

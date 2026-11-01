"""Offline public branding contracts; never imports wallet generation."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bitcoin4funsite'))


class PublicBrandingContract(unittest.TestCase):
    def test_all_public_routes_use_new_domain_contact_and_repository(self):
        spec = importlib.util.spec_from_file_location('branding_app', ROOT / 'bitcoin4funsite/app.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        service = Mock()
        service.token.return_value = 'SYNTHETIC_FORM_TOKEN'
        app = module.create_app({'TESTING': True, 'WALLET_LOOKUP': lambda serial: None, 'CONTACT_SERVICE': service})
        for host in ('https://btc4.fun', 'https://go.btc4.fun'):
            for route in ('/', '/guide', '/kids', '/terms', '/t', '/costs', '/satoshi', '/contact', '/lookup'):
                with self.subTest(host=host, route=route):
                    response = app.test_client().get(route, base_url=host)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('btc4.fun', response.text)
                    self.assertIn('mailto:09113458375@btc4.fun', response.text)
                    self.assertIn('https://github.com/btc4-fun/btc-envelope-maker', response.text)
                    self.assertNotIn('bitcoin4.fun', response.text)

    def test_current_public_docs_link_the_new_endpoints(self):
        self.assertIn('https://btc4.fun', (ROOT / 'README.md').read_text())
        self.assertIn('https://go.btc4.fun/SERIAL', (ROOT / 'bitcoin4funsite/INSTALLATION.md').read_text())
        self.assertIn('09113458375@btc4.fun', (ROOT / 'SECURITY.md').read_text())


if __name__ == '__main__':
    unittest.main()

"""Security page routing is local and independent of wallet services."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
from jinja2 import DictLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app


class SecurityRoute(unittest.TestCase):
    def test_security_page_uses_template_without_wallet_or_market(self):
        lookup = Mock(side_effect=AssertionError('No wallet access'))
        market = Mock()
        market.snapshot.side_effect = AssertionError('No market access')
        app = create_app({'TESTING': True, 'WALLET_LOOKUP': lookup, 'MARKET_SERVICE': market})
        app.jinja_loader = DictLoader({'security.html': 'security-guidance'})
        response = app.test_client().get('/security')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, 'security-guidance')
        self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
        lookup.assert_not_called()
        market.snapshot.assert_not_called()

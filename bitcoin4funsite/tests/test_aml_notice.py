"""Public anti-money-laundering notice: route, wording, links and snapshot scope."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REPOSITORY_ROOT = ROOT.parent
TEMPLATE = ROOT / 'templates' / 'aml.html'
PHRASES = (
    'پول‌شویی',
    'ده دلار',
    'کارمزد',
    'ارزش استفاده به پول‌شویی ندارد',
    'تجربه',
    'کادو',
)


def load_app():
    spec = importlib.util.spec_from_file_location('aml_notice_app', ROOT / 'app.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AmlNotice(unittest.TestCase):
    def setUp(self):
        limiter = Mock()
        limiter.admit.return_value = 0
        self.app = load_app().create_app({'TESTING': True, 'LOOKUP_LIMITER': limiter,
                                          'WALLET_LOOKUP': lambda serial: None})
        self.client = self.app.test_client()

    def test_notice_page_is_public_and_uses_its_own_template(self):
        self.assertTrue(TEMPLATE.is_file(), 'Missing anti-money-laundering notice template')
        response = self.client.get('/aml')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<link rel="canonical" href="https://btc4.fun/aml">', response.text)
        self.assertIsNone(response.headers.get('X-Robots-Tag'))

    def test_notice_states_the_deposit_cap_and_the_purpose(self):
        text = self.client.get('/aml').text
        for phrase in PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        self.assertIn('ده دلار', text)

    def test_notice_never_claims_immunity_or_guarantees(self):
        text = self.client.get('/aml').text
        for forbidden in ('ضد پول‌شویی', 'تضمین امنیت', 'غیرقابل هک', 'سود تضمین'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_notice_is_linked_from_terms_and_sitemap(self):
        terms = self.client.get('/terms').text
        self.assertIn('href="/aml"', terms)
        sitemap = self.client.get('/sitemap.xml').text
        self.assertIn('https://btc4.fun/aml</loc>', sitemap)

    def test_notice_is_not_part_of_the_github_pages_snapshot(self):
        generator = (REPOSITORY_ROOT / 'scripts' / 'build_github_pages.py').read_text(encoding='utf-8')
        self.assertNotIn('aml.html', generator)


if __name__ == '__main__':
    unittest.main()

"""Public release landing page, not expiring CI artifacts."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app


class DownloadPage(unittest.TestCase):
    def test_download_page_links_real_customer_builds_with_clear_limits(self):
        c = create_app({'TESTING': True}).test_client()
        response = c.get('/download')
        self.assertEqual(response.status_code, 200)
        for phrase in ('btc4fun', 'گیت‌هاب', 'Assets', 'btc4fun-release.apk', 'SHA256SUMS',
                       'https://github.com/btc4-fun/btc-tag-checker/releases/latest'):
            self.assertIn(phrase, response.text)
        self.assertIn('href="/download"', c.get('/').text)
        self.assertNotIn('/actions/workflows/', response.text)
        self.assertNotIn('هنوز نسخهٔ نهایی', response.text)
        self.assertIn('بدون ورود', response.text)
        self.assertIn('sha256sum -c SHA256SUMS', response.text)
        self.assertIn('نصب نکنید', response.text)
        self.assertIn('امضای سازنده', response.text)

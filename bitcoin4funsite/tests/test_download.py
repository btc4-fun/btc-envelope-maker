"""Download guidance must not promise a nonexistent signed release."""
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
        for phrase in ('btc4fun', 'آزمایشی', 'گیت‌هاب', 'ورود', 'Artifacts',
                       'https://github.com/btc4-fun/btc-tag-checker/actions/workflows/android.yml'):
            self.assertIn(phrase, response.text)
        self.assertIn('href="/download"', c.get('/').text)
        self.assertNotIn('/releases/latest/download/', response.text)

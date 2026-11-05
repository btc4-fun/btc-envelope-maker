"""Public page metadata: unique descriptions, unique titles, sitemap scope."""
from __future__ import annotations

import importlib.util
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PUBLIC_PAGES = ('/', '/guide', '/security', '/terms', '/download', '/costs')
SERVER_DEPENDENT = ('/lookup', '/contact', '/api/', '/s/')


class Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.description = None
        self.title = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and attrs.get('name') == 'description':
            self.description = attrs.get('content')
        if tag == 'title':
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or '') + data


def load_app():
    spec = importlib.util.spec_from_file_location('public_meta_app', ROOT / 'app.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicMeta(unittest.TestCase):
    def setUp(self):
        limiter = Mock()
        limiter.admit.return_value = 0
        self.app = load_app().create_app({'TESTING': True, 'LOOKUP_LIMITER': limiter,
                                          'WALLET_LOOKUP': lambda serial: None})
        self.client = self.app.test_client()

    def head(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        parser = Head()
        parser.feed(response.text)
        return parser

    def test_each_public_page_has_a_unique_nonempty_meta_description(self):
        descriptions = {}
        for path in PUBLIC_PAGES:
            with self.subTest(path=path):
                description = self.head(path).description or ''
                self.assertTrue(description.strip(), 'meta description must not be empty')
                descriptions[path] = description.strip()
        self.assertEqual(len(set(descriptions.values())), len(PUBLIC_PAGES),
                         'every public page needs its own meta description')

    def test_public_page_titles_are_unique_and_carry_the_brand_suffix(self):
        titles = {}
        for path in PUBLIC_PAGES:
            with self.subTest(path=path):
                title = (self.head(path).title or '').strip()
                self.assertTrue(title)
                titles[path] = title
        self.assertEqual(len(set(titles.values())), len(PUBLIC_PAGES))
        for path in ('/guide', '/security', '/terms', '/download', '/costs'):
            with self.subTest(path=path):
                self.assertIn('بیت‌کوین برای سرگرمی', titles[path])

    def test_sitemap_lists_only_public_pages_and_no_server_dependent_route(self):
        sitemap = self.client.get('/sitemap.xml')
        self.assertEqual(sitemap.status_code, 200)
        for path in PUBLIC_PAGES:
            with self.subTest(path=path):
                self.assertIn('https://btc4.fun' + path + '</loc>', sitemap.text)
        for path in SERVER_DEPENDENT:
            with self.subTest(path=path):
                self.assertNotIn('https://btc4.fun' + path, sitemap.text)


if __name__ == '__main__':
    unittest.main()

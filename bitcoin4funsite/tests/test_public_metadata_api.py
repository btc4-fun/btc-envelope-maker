"""Optional public metadata: `public` in API responses, flag semantics, UI render."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ADDRESS = 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'
SERIAL = 'TEST-DO-NOT-FUND-0587k45300'
PATH = '/api/addresses/' + ADDRESS
SERIAL_PATH = '/api/wallets/' + SERIAL
BALANCE = {'address': ADDRESS, 'confirmed_sats': 1234, 'pending_delta_sats': 0,
           'source': 'https://blockstream.info/api', 'fetched_at': '2026-11-05T00:00:00+00:00'}
FULL_PUBLIC = {
    'public_notes': 'پاکت آزمایشی؛ هیچ ارزشی ندارد.',
    'site_key': 'btc4.fun',
    'site_url': 'https://btc4.fun/',
    'image_url': 'https://btc4.fun/static/logo.png',
}


def load_app():
    spec = importlib.util.spec_from_file_location('public_metadata_app', ROOT / 'app.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicMetadataApi(unittest.TestCase):
    def setUp(self):
        self.module = load_app()
        self.limiter = Mock()
        self.limiter.admit.return_value = 0
        self.balance = Mock()
        self.balance.balance.return_value = dict(BALANCE)

    def build(self, record, **config):
        settings = {
            'TESTING': True, 'LOOKUP_LIMITER': self.limiter,
            'WALLET_LOOKUP': Mock(return_value=record),
            'ADDRESS_LOOKUP': Mock(return_value=record),
            'SERIAL_BALANCE': self.balance,
        }
        settings.update(config)
        return self.module.create_app(settings).test_client()

    # -- flag semantics -----------------------------------------------------
    def test_address_without_flag_returns_exactly_three_keys_and_no_public(self):
        client = self.build(dict(address=ADDRESS, serial=SERIAL, **FULL_PUBLIC))
        response = client.get(PATH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {'address', 'serial', 'lookup_url'})
        self.assertEqual(response.json, {'address': ADDRESS, 'serial': SERIAL,
                                         'lookup_url': 'https://btc4.fun/s/' + SERIAL})

    def test_address_balance_flag_adds_balance_and_optional_public(self):
        client = self.build(dict(address=ADDRESS, serial=SERIAL, **FULL_PUBLIC))
        response = client.get(PATH + '?balance=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {'address', 'serial', 'lookup_url', 'balance', 'public'})
        self.assertEqual(response.json['balance'], BALANCE)
        self.assertEqual(response.json['public'], {
            'notes': FULL_PUBLIC['public_notes'],
            'site': {'key': 'btc4.fun', 'url': 'https://btc4.fun/'},
            'image_url': 'https://btc4.fun/static/logo.png',
        })

    def test_address_balance_flag_without_public_fields_omits_public(self):
        client = self.build({'address': ADDRESS, 'serial': SERIAL})
        response = client.get(PATH + '?balance=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {'address', 'serial', 'lookup_url', 'balance'})
        self.assertNotIn('public', response.json)

    def test_serial_without_flag_keeps_the_existing_shape(self):
        client = self.build(dict(address=ADDRESS, serial=SERIAL, **FULL_PUBLIC))
        response = client.get(SERIAL_PATH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {'serial', 'address', 'explorer_url'})

    def test_serial_balance_flag_adds_optional_public(self):
        client = self.build(dict(address=ADDRESS, serial=SERIAL, **FULL_PUBLIC))
        response = client.get(SERIAL_PATH + '?balance=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json), {'serial', 'address', 'explorer_url', 'balance', 'public'})
        self.assertEqual(response.json['public']['notes'], FULL_PUBLIC['public_notes'])

    def test_serial_balance_flag_without_public_fields_omits_public(self):
        client = self.build({'address': ADDRESS, 'serial': SERIAL})
        response = client.get(SERIAL_PATH + '?balance=1')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('public', response.json)

    # -- query admission ----------------------------------------------------
    def test_only_a_single_balance_1_query_is_admitted(self):
        client = self.build({'address': ADDRESS, 'serial': SERIAL})
        for query in ('?balance=0', '?balance=1&balance=1', '?balance=1&x=2', '?x=1',
                      '?balance', '?Balance=1', '?&'):
            with self.subTest(query=query):
                response = client.get(PATH + query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json, {'error': 'invalid_lookup_request'})
        self.limiter.admit.assert_not_called()

    # -- upstream balance failure ------------------------------------------
    def test_address_balance_failure_is_a_clear_503(self):
        self.balance.balance.side_effect = RuntimeError('SYNTHETIC_PRIVATE_UPSTREAM')
        client = self.build(dict(address=ADDRESS, serial=SERIAL, **FULL_PUBLIC))
        response = client.get(PATH + '?balance=1')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json, {'address': ADDRESS, 'serial': SERIAL,
                                         'lookup_url': 'https://btc4.fun/s/' + SERIAL,
                                         'error': 'balance_unavailable'})
        self.assertNotIn('SYNTHETIC_PRIVATE', response.text)

    def test_serial_balance_failure_keeps_the_backwards_compatible_error(self):
        self.balance.balance.side_effect = RuntimeError('SYNTHETIC_PRIVATE_UPSTREAM')
        client = self.build(dict(address=ADDRESS, serial=SERIAL, **FULL_PUBLIC))
        response = client.get(SERIAL_PATH + '?balance=1')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['balance_error'], 'unavailable')

    # -- sanitizer ----------------------------------------------------------
    def test_unsafe_or_off_allowlist_public_values_are_dropped(self):
        record = {
            'address': ADDRESS, 'serial': SERIAL,
            'public_notes': 'ok\u202eevil',                      # bidi override
            'site_key': 'btc4.fun', 'site_url': 'http://btc4.fun/',   # not https
            'image_url': 'https://evil.invalid/x.png',          # host not allowed
        }
        client = self.build(record)
        response = client.get(SERIAL_PATH + '?balance=1')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('public', response.json)
        self.assertNotIn('evil', response.text)

    def test_notes_alone_need_no_site(self):
        client = self.build({'address': ADDRESS, 'serial': SERIAL, 'public_notes': 'تنها یادداشت'})
        response = client.get(SERIAL_PATH + '?balance=1')
        self.assertEqual(response.json['public'], {'notes': 'تنها یادداشت'})

    def test_site_requires_both_key_and_url(self):
        for record in ({'site_key': 'btc4.fun'},
                       {'site_url': 'https://btc4.fun/'},
                       {'site_key': 'bad key!', 'site_url': 'https://btc4.fun/'}):
            with self.subTest(record=record):
                client = self.build(dict(address=ADDRESS, serial=SERIAL, **record))
                response = client.get(SERIAL_PATH + '?balance=1')
                self.assertNotIn('public', response.json)

    # -- no-JS template -----------------------------------------------------
    def test_no_js_template_renders_optional_fields(self):
        client = self.build(dict(address=ADDRESS, serial=SERIAL, **FULL_PUBLIC))
        # /s/<serial> is the browser-rendered no-JS page (the API route is JSON).
        response = client.get('/s/' + SERIAL)
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('یادداشت عمومی', html)
        self.assertIn(FULL_PUBLIC['public_notes'], html)
        self.assertIn('سایت', html)
        self.assertIn('href="https://btc4.fun/"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn('تصویر', html)
        self.assertIn('src="https://btc4.fun/static/logo.png"', html)
        self.assertIn('alt=""', html)
        self.assertIn('width="320"', html)
        self.assertIn('height="180"', html)

    def test_no_js_template_omits_optional_section_when_empty(self):
        client = self.build({'address': ADDRESS, 'serial': SERIAL})
        html = client.get('/s/' + SERIAL).text
        self.assertNotIn('یادداشت عمومی', html)
        self.assertNotIn('اطلاعات اختیاری پاکت', html)


class PublicPayloadUnit(unittest.TestCase):
    def test_helper_shapes(self):
        module = load_app()
        self.assertIsNone(module.public_payload({'address': ADDRESS, 'serial': SERIAL}))
        self.assertIsNone(module.public_payload(None))
        self.assertIsNone(module.public_payload({'public_notes': '   '}))
        self.assertEqual(module.public_payload({'public_notes': 'x'}), {'notes': 'x'})
        self.assertIsNone(module.public_payload({'public_notes': 'x' * 501}))
        self.assertEqual(
            module.public_payload({'public_notes': 'n', 'site_key': 'b.tc4fun.ir',
                                   'site_url': 'https://b.tc4fun.ir/path'}),
            {'notes': 'n', 'site': {'key': 'b.tc4fun.ir', 'url': 'https://b.tc4fun.ir/path'}})
        for bad in ('https://btc4.fun:8443/', 'https://user@btc4.fun/', 'https://evil.invalid/',
                    'http://btc4.fun/', 'javascript:alert(1)', 'https://btc4.fun/ x'):
            with self.subTest(bad=bad):
                self.assertIsNone(module.public_payload({'image_url': bad}))


class SiteJsContract(unittest.TestCase):
    def test_site_js_validates_public_fields(self):
        source = (ROOT / 'static' / 'site.js').read_text(encoding='utf-8')
        self.assertIn('publicBlock(wallet)', source)
        self.assertIn('PUBLIC_HOSTS', source)
        self.assertIn('noopener noreferrer', source)
        self.assertIn('img.hidden = true', source)
        self.assertIn('publicText(source.notes, 500)', source)


if __name__ == '__main__':
    unittest.main()

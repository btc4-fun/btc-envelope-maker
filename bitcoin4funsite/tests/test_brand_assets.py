"""The public logo and favicon are local, transparent, non-executable PNGs."""
from pathlib import Path
import struct
import unittest


ROOT = Path(__file__).resolve().parents[1]
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def png_header(path):
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise AssertionError(f'{path.name} is not a PNG')
    width, height, bit_depth, color_type = struct.unpack('>IIBB', data[16:26])
    return width, height, bit_depth, color_type


class BrandAssetContract(unittest.TestCase):
    def test_logo_and_favicon_are_transparent_rgba_pngs(self):
        for name, size in (('logo.png', 256), ('favicon.png', 32)):
            with self.subTest(name=name):
                path = ROOT / 'static' / name
                self.assertTrue(path.is_file(), f'Missing brand asset: {name}')
                width, height, bit_depth, color_type = png_header(path)
                self.assertEqual((width, height), (size, size))
                self.assertEqual(bit_depth, 8)
                # PNG color type 6 is truecolor with alpha; the background must
                # be transparent so the gold mark sits on any page colour.
                self.assertEqual(color_type, 6, f'{name} must carry an alpha channel')

    def test_header_and_envelope_use_the_logo_and_favicon_is_linked(self):
        base = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
        index = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('<link rel="icon" type="image/png" href="/static/favicon.png">', base)
        self.assertIn('class="brand-mark" src="/static/logo.png"', base)
        self.assertNotIn('<span class="brand-mark"', base)
        self.assertIn('class="card-symbol" src="/static/logo.png"', index)
        self.assertNotIn('<span class="card-symbol">', index)

    def test_brand_restriction_is_recorded_in_the_license(self):
        license_text = (ROOT.parent / 'LICENSE.md').read_text(encoding='utf-8')
        notice = (ROOT.parent / 'NOTICE').read_text(encoding='utf-8')
        for name in ('btc4fun', 'bitcoin4fun'):
            self.assertIn(name, license_text)
        self.assertIn('prior written permission', license_text)
        self.assertIn('logo.png', notice)


if __name__ == '__main__':
    unittest.main()

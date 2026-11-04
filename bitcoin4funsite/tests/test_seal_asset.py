"""The public seal is a local, metadata-free, non-executable SVG asset."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class SealAssetContract(unittest.TestCase):
    def test_seal_svg_has_only_local_safe_references(self):
        source = (ROOT / 'static' / 'seal.svg').read_text(encoding='utf-8')
        self.assertNotRegex(source, r'<\s*(script|foreignObject|metadata|rdf:RDF|image)\b')
        self.assertNotRegex(source, r'(?i)(?:https?://(?!www\.w3\.org/2000/svg)|data:|javascript:|xlink:href\s*=\s*["\'](?!#))')
        root = ET.fromstring(source)
        self.assertTrue(root.tag.endswith('svg'))
        for element in root.iter():
            self.assertNotIn('metadata', element.tag.lower())
            for name, value in element.attrib.items():
                if name.endswith('href'):
                    self.assertTrue(value.startswith('#'), (name, value))

    def test_guide_points_to_proprietary_seal_license_exception(self):
        guide = (ROOT / 'templates' / 'guide.html').read_text(encoding='utf-8')
        license_text = (ROOT / 'static' / 'SEAL-LICENSE.md').read_text(encoding='utf-8')
        self.assertIn('href="/static/SEAL-LICENSE.md"', guide)
        self.assertIn('excluded from the repository\'s general PolyForm Noncommercial license', license_text)
        self.assertIn('prior written permission', license_text)


if __name__ == '__main__':
    unittest.main()

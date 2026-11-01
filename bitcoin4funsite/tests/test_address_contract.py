"""Pinned public address contract without a generator dependency."""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

SITE = Path(__file__).resolve().parents[1]


class AddressContract(unittest.TestCase):
    def test_public_vectors(self):
        spec = importlib.util.spec_from_file_location('site_validator_contract', SITE / 'address_validation.py')
        assert spec is not None and spec.loader is not None
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        vectors = json.loads((SITE / 'tests/fixtures/public_contract.json').read_text())
        for vector in vectors['addresses']:
            with self.subTest(value=vector['value']):
                self.assertEqual(validator.valid_address(vector['value']), vector['valid'])
                self.assertEqual(validator.valid_inventory_address(vector['value']), vector['inventory'])

    def test_pinned_source_provenance(self):
        digest = hashlib.sha256((SITE / 'address_validation.py').read_bytes()).hexdigest()
        self.assertIn(digest, (SITE.parent / 'docs/address-validator-provenance.md').read_text())

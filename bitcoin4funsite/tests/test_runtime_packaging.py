"""Runtime helpers must survive the explicit image context allowlist."""
from pathlib import Path
import unittest

SITE = Path(__file__).resolve().parents[1]


class RuntimePackagingTests(unittest.TestCase):
    def test_shared_address_validator_is_in_image_and_context(self):
        dockerfile = (SITE / 'Dockerfile').read_text()
        copied = [line.split()[1:-1] for line in dockerfile.splitlines()
                  if line.startswith('COPY ')]
        self.assertTrue(any('address_validation.py' in names for names in copied))
        self.assertIn('!address_validation.py', (SITE / '.dockerignore').read_text().splitlines())

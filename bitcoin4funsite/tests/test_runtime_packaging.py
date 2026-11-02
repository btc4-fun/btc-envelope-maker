"""Runtime helpers survive the repository-root, explicit image allowlist."""
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import tempfile

SITE = Path(__file__).resolve().parents[1]
ROOT = SITE.parent


class RuntimePackagingTests(unittest.TestCase):
    def test_context_allowlists_match_and_cover_every_runtime_copy(self):
        local = [line.strip() for line in (SITE / '.dockerignore').read_text().splitlines()
                 if line.strip() and not line.startswith('#')]
        root = [line.strip() for line in (SITE / 'Dockerfile.dockerignore').read_text().splitlines()
                if line.strip() and not line.startswith('#')]
        self.assertEqual(root.count('!bitcoin4funsite/'), 1)
        normalized = [line.replace('bitcoin4funsite/', '', 1)
                      for line in root if line != '!bitcoin4funsite/']
        self.assertEqual(local, normalized)
        for line in (SITE / 'Dockerfile').read_text().splitlines():
            if line.startswith('COPY '):
                for source in line.split()[1:-1]:
                    self.assertIn('!' + source, root)
                    self.assertIn('!' + source.removeprefix('bitcoin4funsite/'), local)
        self.assertEqual(local[0], '*')
        for sensitive in ('static/privatekey.png', 'static/publickey.png'):
            self.assertIn(sensitive, local)
            self.assertGreater(local.index(sensitive), local.index('!static/**'))
        for forbidden in ('.env', 'secrets/', 'state/', 'tests/', 'btc_envelope_maker/'):
            self.assertFalse(any(line.startswith('!' + forbidden) for line in local))

    def test_tag_runtime_modules_are_copied_and_allowed(self):
        dockerfile = (SITE / 'Dockerfile').read_text()
        copy_lines = '\n'.join(line for line in dockerfile.splitlines() if line.startswith('COPY '))
        ignore = (SITE / 'Dockerfile.dockerignore').read_text().splitlines()
        for name in ('tag_access.py', 'chain_activity.py'):
            self.assertIn('bitcoin4funsite/' + name, copy_lines)
            self.assertIn('!bitcoin4funsite/' + name, ignore)

    def test_vendored_address_validator_is_in_image_without_generator(self):
        dockerfile = (SITE / 'Dockerfile').read_text()
        self.assertNotIn('btc_envelope_maker/', dockerfile)
        self.assertIn('bitcoin4funsite/address_validation.py', dockerfile)
        ignore = SITE / 'Dockerfile.dockerignore'
        self.assertTrue(ignore.exists())
        lines = ignore.read_text().splitlines()
        self.assertFalse(any('btc_envelope_maker/' in line for line in lines))
        self.assertIn('bitcoin4funsite/static/privatekey.png', lines)
        self.assertIn('bitcoin4funsite/static/publickey.png', lines)
        compose = (SITE / 'compose.yaml').read_text()
        self.assertIn('context: ..', compose)
        self.assertIn('dockerfile: bitcoin4funsite/Dockerfile', compose)

    def test_helper_only_image_shape_imports_without_generator_or_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(SITE / 'address_validation.py', root / 'address_validation.py')
            result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c',
                                     'import sys; sys.path.insert(0, sys.argv[1]); '
                                     'from address_validation import valid_address; '
                                     'assert valid_address("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"); '
                                     'assert not any(n.startswith("btc_envelope_maker") for n in sys.modules)',
                                     directory], cwd=directory, env={}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

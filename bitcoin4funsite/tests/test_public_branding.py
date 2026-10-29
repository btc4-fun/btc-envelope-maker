"""Offline rebrand contracts: no wallet generation, PDFs or database access."""
from __future__ import annotations

import ast
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import tomllib
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
LEGACY_DOMAIN = "bitcoin4.fun"
REPOSITORY_URL = "https://github.com/sae13/bitcoin4fun"
CONTACT = "09113458375@btc4.fun"


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


class PublicBrandingContract(unittest.TestCase):
    def test_all_public_routes_use_new_brand_and_contact_on_both_hosts(self):
        spec = importlib.util.spec_from_file_location(
            "bitcoin4fun_branding_app", ROOT / "bitcoin4funsite/app.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        lookup = Mock(return_value=None)
        app = module.create_app({"TESTING": True, "WALLET_LOOKUP": lookup})
        client = app.test_client()
        with patch.object(module.psycopg, "connect") as connect:
            for host in ("https://btc4.fun", "https://go.btc4.fun"):
                for route in ("/", "/guide", "/kids", "/terms", "/lookup",
                              "/s/TEST-DO-NOT-FUND", "/TEST-DO-NOT-FUND"):
                    with self.subTest(host=host, route=route):
                        response = client.get(route, base_url=host)
                        self.assertEqual(response.status_code, 200)
                        document = Document(response.text)
                        links = {attrs.get("href") for tag, attrs in document.elements
                                 if tag == "a"}
                        self.assertIn("btc4.fun", document.text)
                        self.assertIn(CONTACT, document.text)
                        self.assertIn("mailto:" + CONTACT, links)
                        self.assertIn(REPOSITORY_URL, links)
                        self.assertNotIn(LEGACY_DOMAIN, response.text)
                        self.assertNotIn("bitcoin4fun", " ".join(document.text))
                        self.assertIn(("span", {"class": "brand-subtitle",
                                               "lang": "en", "dir": "ltr"}),
                                      document.elements)
            connect.assert_not_called()
        self.assertEqual({call.args for call in lookup.call_args_list},
                         {("TEST-DO-NOT-FUND",)})

    def test_public_documentation_uses_target_endpoints_and_contact(self):
        expectations = {
            "README.md": ("# btc4.fun", "https://btc4.fun"),
            "NOTICE": ("Copyright Saeb Molaee", CONTACT),
            "SECURITY.md": (CONTACT,),
            "bitcoin4funsite/DEPLOYMENT.md": ("https://btc4.fun", "https://go.btc4.fun"),
            "bitcoin4funsite/INSTALLATION.md": ("https://btc4.fun", "https://go.btc4.fun/SERIAL"),
        }
        for name, expected in expectations.items():
            with self.subTest(file=name):
                source = (ROOT / name).read_text(encoding="utf-8")
                for value in expected:
                    self.assertIn(value, source)
                self.assertNotIn(LEGACY_DOMAIN, source)

    def test_generator_defaults_and_example_use_same_public_brand(self):
        # Inspect literal defaults without importing crypto/PDF dependencies or
        # executing the generator, including its entropy and output paths.
        generator = ROOT / "btc_envelope_maker/btc_envelope_maker.py"
        tree = ast.parse(generator.read_text(encoding="utf-8"))
        assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "DEFAULTS"
                               for target in node.targets)]
        self.assertEqual(len(assignments), 1)
        defaults = ast.literal_eval(assignments[0].value)
        with (ROOT / "btc_envelope_maker/config.example.toml").open("rb") as stream:
            example = tomllib.load(stream)
        for name, config in (("defaults", defaults), ("example", example)):
            with self.subTest(config=name):
                self.assertEqual(config["brand_name"], "btc4.fun")
                self.assertEqual(config["contact"], "btc4.fun   |   " + CONTACT)
                # Balance links remain independent, explicit explorer links.
                self.assertEqual(config["explorer_url"], "https://mempool.space/address/")
                self.assertEqual(config["db_url"], "")
                self.assertEqual(config["db_table"], "wallets")
                self.assertNotIn(LEGACY_DOMAIN, repr(config))


if __name__ == "__main__":
    unittest.main()

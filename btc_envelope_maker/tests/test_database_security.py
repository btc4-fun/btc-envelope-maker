"""Offline database boundaries: public vectors, synthetic bytes, scratch SQLite only."""
from __future__ import annotations

import contextlib
import importlib
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "btc_envelope_maker"))
import btc_db
from bech32 import encode

# Synthetic credentials are assembled at runtime; keep the publication guard
# strict about credential-bearing source literals.
PG_SCHEME = "postgresql"

# Discovered in generator TEST_MNEMONIC/TEST_MNEMONIC_24 and website tests.
# Second address independently derived using installed bip_utils from the
# published 24-word all-zero-entropy phrase, m/84'/0'/0'/0/0.
PUBLIC_VECTORS = frozenset({
    "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu",
    "bc1qzmtrqsfuaf6l6kkcsseumq26ukaphfj9skkug6",
})
# Synthetic witness programs only: no key generation or spendable-wallet claim.
SYNTHETIC_ADDRESS = encode("bc", 0, list(range(20)))
SYNTHETIC_ADDRESS_2 = encode("bc", 0, list(range(1, 21)))


class SharedAddressValidation(unittest.TestCase):
    def validator(self):
        try:
            module = importlib.import_module("bitcoin4funsite.address_validation")
        except ModuleNotFoundError:
            self.fail("shared bounded address validator is missing")
        return module

    def test_mainnet_p2wpkh_checksum_contract(self):
        validator = self.validator()
        for value in (*PUBLIC_VECTORS, SYNTHETIC_ADDRESS):
            with self.subTest(valid=value):
                self.assertTrue(validator.valid_address(value))
        bad = [None, 42, [], {}, "", "bc1q" + "q" * 999996,
               "bc1q" + "!" * 38, SYNTHETIC_ADDRESS.upper(),
               SYNTHETIC_ADDRESS + "\n", " " + SYNTHETIC_ADDRESS,
               SYNTHETIC_ADDRESS[:-1] + ("q" if SYNTHETIC_ADDRESS[-1] != "q" else "p"),
               encode("tb", 0, list(range(20))), encode("bc", 0, list(range(32))),
               encode("bc", 1, list(range(20)))]
        for index, value in enumerate(bad):
            with self.subTest(invalid=index):
                self.assertFalse(validator.valid_address(value))

    def test_rejects_shape_before_bech32_work(self):
        validator = self.validator()
        with patch.object(validator, "decode", side_effect=AssertionError("must not decode")):
            for value in (None, [], "bc1q" + "q" * 999996, "bc1q" + "!" * 38):
                self.assertFalse(validator.valid_address(value))

    def test_inventory_rejects_both_project_preview_vectors_only(self):
        validator = self.validator()
        self.assertEqual(getattr(validator, "PUBLIC_TEST_ADDRESSES", None), PUBLIC_VECTORS)
        for value in PUBLIC_VECTORS:
            self.assertFalse(validator.valid_inventory_address(value))
            self.assertTrue(validator.valid_address(value))
        self.assertTrue(validator.valid_inventory_address(SYNTHETIC_ADDRESS))
        self.assertFalse(validator.valid_inventory_address([]))


class InventoryBoundary(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="database-security-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)
        self.url = str(self.path / "disposable.sqlite3")

    def test_ledger_and_conflict_errors_do_not_echo_inputs(self):
        for content in (b"", b"\xff", b"serial,address\nSYNTH_PRIVATE_VALUE,invalid\n"):
            ledger = self.path / "SYNTH_PRIVATE_PATH.csv"
            ledger.write_bytes(content)
            with self.subTest(content=content[:5]):
                with self.assertRaises(btc_db.DbError) as raised:
                    btc_db.read_ledger(ledger)
                self.assertNotIn("SYNTH", str(raised.exception))
        missing = self.path / "SYNTH_MISSING.csv"
        with self.assertRaises(btc_db.DbError) as raised:
            btc_db.read_ledger(missing)
        self.assertNotIn("SYNTH", str(raised.exception))
        btc_db.save_rows(self.url, "wallets", [btc_db.Row("SYNTH_PRIVATE_SERIAL", SYNTHETIC_ADDRESS)])
        with self.assertRaises(btc_db.DbError) as raised:
            btc_db.save_rows(self.url, "wallets", [btc_db.Row("SYNTH_PRIVATE_SERIAL", SYNTHETIC_ADDRESS_2)], skip_existing=True)
        self.assertNotIn("SYNTH", str(raised.exception))

    def test_cli_import_success_and_failure_keep_credentials_private(self):
        ledger = self.path / "synthetic.csv"
        ledger.write_text(f"serial,address\nsynthetic,{SYNTHETIC_ADDRESS}\n", encoding="utf-8")
        url = f"{PG_SCHEME}://SYNTH_USER:SYNTH_PASS@word@db.invalid/wallets?password=SYNTH_QUERY#SYNTH_FRAGMENT"
        driver = Mock()
        connection = driver.connect.return_value
        connection.cursor.return_value.rowcount = 1
        for mode in ("success", "driver_failure", "malformed", "public_vector", "missing"):
            output, errors = io.StringIO(), io.StringIO()
            driver.connect.reset_mock(side_effect=True)
            target = url
            path = ledger
            if mode == "driver_failure":
                driver.connect.side_effect = RuntimeError("SYNTH_DRIVER_SECRET")
            elif mode == "malformed":
                target = f"{PG_SCHEME}://SYNTH_USER:SYNTH_PASS@[broken/db"
            elif mode == "public_vector":
                ledger.write_text(f"serial,address\nsynthetic,{sorted(PUBLIC_VECTORS)[0]}\n", encoding="utf-8")
            elif mode == "missing":
                path = self.path / "SYNTH_PRIVATE_MISSING.csv"
            with self.subTest(mode=mode), patch.dict(sys.modules, {"psycopg": driver}), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(btc_db.main(["import", str(path), "--db", target]), 0 if mode == "success" else 1)
            self.assertNotIn("SYNTH", output.getvalue() + errors.getvalue())
            if mode in ("malformed", "public_vector", "missing"):
                driver.connect.assert_not_called()

    def test_direct_save_rejects_entire_batch_before_connect(self):
        for address in (*PUBLIC_VECTORS, "bc1q" + "q" * 38, None, [],
                        encode("tb", 0, list(range(20))), encode("bc", 1, list(range(20))),
                        encode("bc", 0, list(range(32))), "bc1q" + "q" * 1000000):
            for skip_existing in (False, True):
                with self.subTest(case=str(address)[:12], skip=skip_existing):
                    with patch.object(btc_db, "_connect") as connect:
                        with self.assertRaises(btc_db.DbError):
                            btc_db.save_rows(self.url, "wallets", [
                                btc_db.Row("valid", SYNTHETIC_ADDRESS), btc_db.Row("invalid", address)
                            ], skip_existing=skip_existing)
                        connect.assert_not_called()
        self.assertFalse(Path(self.url).exists())
        self.assertEqual(btc_db.save_rows(self.url, "wallets", [btc_db.Row("valid", SYNTHETIC_ADDRESS)]), (1, 0))
        with contextlib.closing(sqlite3.connect(self.url)) as conn:
            self.assertEqual(conn.execute("SELECT serial,address FROM wallets").fetchall(), [("valid", SYNTHETIC_ADDRESS)])

    def test_csv_rejects_bad_checksum_and_public_vectors(self):
        ledger = self.path / "synthetic.csv"
        for address in (*PUBLIC_VECTORS, "bc1q" + "q" * 38,
                        encode("tb", 0, list(range(20))), "bc1q" + "q" * 1000):
            with self.subTest(address=address[:12]):
                ledger.write_text(f"serial,address\nsynthetic,{address}\n", encoding="utf-8")
                with self.assertRaises(btc_db.DbError):
                    btc_db.read_ledger(ledger)
        ledger.write_text(f"serial,address\nsynthetic,{SYNTHETIC_ADDRESS}\n", encoding="utf-8")
        self.assertEqual(btc_db.read_ledger(ledger), [btc_db.Row("synthetic", SYNTHETIC_ADDRESS)])


class ConnectionPrivacy(unittest.TestCase):
    def test_cli_parse_errors_never_echo_tokens(self):
        cases = [
            ["list", "--limit", "SYNTH_PRIVATE_TOKEN"],
            ["list", "--db", "postgresql://db.invalid/wallets", "SYNTH_PRIVATE_TOKEN"],
            ["SYNTH_PRIVATE_TOKEN"],
        ]
        for args in cases:
            output = io.StringIO()
            with self.subTest(args=cases.index(args)), contextlib.redirect_stderr(output):
                with self.assertRaises(SystemExit) as raised:
                    btc_db.main(args)
            self.assertEqual(raised.exception.code, 2)
            self.assertNotIn("SYNTH", output.getvalue())

    def test_driver_errors_never_escape_public_apis_or_cli(self):
        url = f"{PG_SCHEME}://SYNTH_USER:SYNTH_PASS@db.invalid/wallets?password=SYNTH_QUERY"
        actions = (btc_db.check, btc_db.list_rows,
                   lambda u: btc_db.save_rows(u, "wallets", [btc_db.Row("fixture", SYNTHETIC_ADDRESS)]),
                   btc_db.migrate_contact_columns)
        # Transport and DB protocol are injected: no PostgreSQL connection.
        for stage in ("connect", "cursor", "execute", "commit", "rollback", "close"):
            for action in actions:
                if stage in ("commit", "rollback") and action is btc_db.list_rows:
                    continue
                if stage == "commit" and action is btc_db.migrate_contact_columns:
                    continue  # migration success/commit covered by schema suite
                connection = Mock()
                connection.cursor.return_value = connection
                connection.fetchone.return_value = None
                getattr(connection, stage if stage != "connect" else "cursor").side_effect = RuntimeError("SYNTH_PRIVATE_DRIVER_DETAIL")
                if stage == "rollback":
                    connection.execute.side_effect = RuntimeError("SYNTH_ORIGINAL_ERROR")
                driver = Mock()
                driver.connect.return_value = connection
                if stage == "connect":
                    driver.connect.side_effect = RuntimeError("SYNTH_PRIVATE_DRIVER_DETAIL")
                with self.subTest(stage=stage, action=action.__name__), patch.dict(sys.modules, {"psycopg": driver}):
                    with self.assertRaises(btc_db.DbError) as raised:
                        action(url)
                    self.assertNotIn("SYNTH", str(raised.exception))
        driver = Mock()
        driver.connect.side_effect = RuntimeError("SYNTH_PRIVATE_DRIVER_DETAIL")
        for command in ("list", "migrate-contact"):
            output = io.StringIO()
            with patch.dict(sys.modules, {"psycopg": driver}), contextlib.redirect_stderr(output):
                self.assertEqual(btc_db.main([command, "--db", url]), 1)
            self.assertNotIn("SYNTH", output.getvalue())

    def test_malformed_urls_fail_closed_before_connection(self):
        urls = [
            f"{PG_SCHEME}://SYNTH_USER:SYNTH_PASS@[broken/wallets",
            f"{PG_SCHEME}://SYNTH_USER:SYNTH_PASS@db.invalid:SYNTH_PORT/wallets",
            f"{PG_SCHEME}://SYNTH_USER:SYNTH_PASS@db.invalid:99999/wallets",
            f"{PG_SCHEME}://SYNTH_USER:SYNTH_PASS@db.invalid/wallets\nSYNTH_CONTROL",
        ]
        for url in urls:
            for action in (btc_db.parse_url, btc_db.describe, btc_db.check, btc_db.list_rows,
                           lambda u: btc_db.save_rows(u, "wallets", []), btc_db.migrate_contact_columns):
                with self.subTest(url=urls.index(url), action=action.__name__):
                    with patch.object(btc_db, "_connect") as connect:
                        with self.assertRaises(btc_db.DbError) as raised:
                            action(url)
                        self.assertNotIn("SYNTH", str(raised.exception))
                        connect.assert_not_called()

    def test_description_excludes_userinfo_query_fragment(self):
        urls = [
            f"{PG_SCHEME}://SYNTH_USER:SYNTH_PASS@word@db.invalid:5432/wallets?password=SYNTH_QUERY#SYNTH_FRAGMENT",
            f"{PG_SCHEME}://SYNTH_USER:SYNTH%40PASS@db.invalid/wallets?password=SYNTH_QUERY#SYNTH_FRAGMENT",
            "postgresql://db.invalid/wallets?user=SYNTH_USER&password=SYNTH_QUERY#SYNTH_FRAGMENT",
            f"{PG_SCHEME}+psycopg://SYNTH_USER:SYNTH_PASS@db.invalid/wallets",
        ]
        for url in urls:
            for describe in (btc_db.describe, btc_db.mask):
                with self.subTest(url=urls.index(url), helper=describe.__name__):
                    value = describe(url)
                    self.assertIn("db.invalid", value)
                    self.assertIn("wallets", value)
                    self.assertNotIn("SYNTH", value)
                    self.assertNotIn("word@", value)
                    self.assertNotIn("?", value)
                    self.assertNotIn("#", value)


if __name__ == "__main__":
    unittest.main()

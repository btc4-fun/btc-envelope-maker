"""Owner-only NFC proofs using disposable databases and synthetic witness bytes."""
from contextlib import closing
import importlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from bech32 import encode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from btc_envelope_maker import btc_db
from btc_envelope_maker.address_validation import PUBLIC_TEST_ADDRESSES

ADDRESSES = [encode("bc", 0, list(range(offset, offset + 20))) for offset in range(4)]


def module():
    try:
        return importlib.import_module("btc_envelope_maker.nfc_bindings")
    except ModuleNotFoundError:
        raise AssertionError("owner NFC binding module is missing") from None


class NfcBindings(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="nfc-proof-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.url = str(self.directory / "fixture.sqlite3")
        btc_db.save_rows(self.url, "wallets", [
            btc_db.Row(f"SYNTH_SERIAL_{i}", address, "synthetic timestamp", "2026-01-01 00:00:00 UTC")
            for i, address in enumerate(ADDRESSES[:3])
        ])
        with closing(sqlite3.connect(self.url)) as conn, conn:
            conn.execute("UPDATE wallets SET notes = ?, contact_value = ?", ("SYNTH_NOTE", "SYNTH_CONTACT"))

    def query(self, sql, params=()):
        with closing(sqlite3.connect(self.url)) as conn:
            return conn.execute(sql, params).fetchall()

    def csv(self, rows):
        path = self.directory / "captures.csv"
        path.write_text("uid,address,captured_at\n" + "".join(
            f"{uid},{address},2026-01-01T12:00:00Z\n" for uid, address in rows), encoding="utf-8")
        return path

    def test_import_requires_migration_then_assigns_and_replays(self):
        nfc = module()
        self.assertTrue(callable(getattr(nfc, "import_csv", None)), "CSV importer is missing")
        path = self.csv([("04ABCDEF", ADDRESSES[0]), ("04ABCDEF010203", ADDRESSES[1]),
                         ("04ABCDEF010203040506", ADDRESSES[2])])
        before = self.query("SELECT * FROM wallets ORDER BY serial")
        with self.assertRaises(btc_db.DbError):
            nfc.import_csv(self.url, path)
        self.assertNotIn("nfc_uid", [c[1] for c in self.query("PRAGMA table_info(wallets)")])
        nfc.migrate_nfc_uid(self.url)
        self.assertEqual(nfc.import_csv(self.url, path), (3, 0))
        self.assertEqual(nfc.import_csv(self.url, path), (0, 3))
        after = self.query("SELECT * FROM wallets ORDER BY serial")
        self.assertEqual([r[:-1] for r in after], before)
        self.assertEqual([r[-1] for r in after], ["04ABCDEF", "04ABCDEF010203", "04ABCDEF010203040506"])

    def test_csv_validation_rejects_entire_batch_before_connect(self):
        nfc = module()
        header = "uid,address,captured_at\n"
        good = f"04ABCDEF,{ADDRESSES[0]},2026-01-01T12:00:00Z\n"
        bad_uids = ["04abcdef", "04:AB:CD:EF", "04 AB CD EF", " 04ABCDEF", "04ABCDEF ",
                    "04ABCDE", "04ABCDEF00", "04ABCDEF0000", "G4ABCDEF", "０4ABCDEF", "", "A" * 100]
        invalid = [header + good + f"{uid},{ADDRESSES[1]},2026-01-01T12:00:00Z\n" for uid in bad_uids]
        invalid += [header + good + f"04AAAAAA,{addr},2026-01-01T12:00:00Z\n" for addr in (
            "bc1q" + "q" * 38, ADDRESSES[1].upper(), " " + ADDRESSES[1],
            *PUBLIC_TEST_ADDRESSES)]
        invalid += [header + f"04ABCDEF,{ADDRESSES[0]},{stamp}\n" for stamp in (
            "", "not a date", "2026-02-30T12:00:00Z", "2026-01-01", "2026-01-01T12:00:00",
            "2026-01-01T12:00:00Z ", "2026-01-01T12:00:00+00:99")]
        invalid += ["", header, header + good + good, header + good + f"04ABCDEF,{ADDRESSES[1]},2026-01-01T12:00:00Z\n",
                    header + good + f"04AAAAAA,{ADDRESSES[0]},2026-01-01T12:00:00Z\n",
                    "uid,address\n" + good, "uid,address,captured_at,secret\n" + good,
                    "uid,address,uid\n" + good, header + good.rstrip() + ",extra\n",
                    header + '"unterminated', header + good + "04AAAAAA\n"]
        path = self.directory / "bad.csv"
        for i, text in enumerate(invalid):
            with self.subTest(case=i):
                path.write_text(text, encoding="utf-8")
                with patch.object(btc_db, "_connect") as connect:
                    with self.assertRaises(btc_db.DbError):
                        nfc.import_csv(self.url, path)
                    connect.assert_not_called()

    def test_csv_byte_and_row_limits(self):
        nfc = module()
        path = self.csv([("04ABCDEF", ADDRESSES[0]), ("04AAAAAA", ADDRESSES[1])])
        for name, limit in (("MAX_CSV_BYTES", path.stat().st_size - 1), ("MAX_CSV_ROWS", 1)):
            with self.subTest(limit=name), patch.object(nfc, name, limit, create=True):
                with patch.object(btc_db, "_connect") as connect:
                    with self.assertRaises(btc_db.DbError):
                        nfc.import_csv(self.url, path)
                    connect.assert_not_called()
        nfc.migrate_nfc_uid(self.url)
        with patch.object(nfc, "MAX_CSV_BYTES", path.stat().st_size, create=True), patch.object(nfc, "MAX_CSV_ROWS", 2, create=True):
            self.assertEqual(nfc.import_csv(self.url, path), (2, 0))

    def test_conflicts_unknown_addresses_reject_before_any_update(self):
        nfc = module()
        nfc.migrate_nfc_uid(self.url)
        nfc.import_csv(self.url, self.csv([("04ABCDEF", ADDRESSES[0])]))
        before = self.query("SELECT * FROM wallets ORDER BY serial")
        for rejected in (("04AAAAAA", ADDRESSES[0]), ("04ABCDEF", ADDRESSES[2]),
                         ("04AAAAAA", ADDRESSES[3])):
            path = self.csv([("04BBBBBB", ADDRESSES[1]), rejected])
            updates = []
            connection = sqlite3.connect(self.url)
            connection.set_authorizer(lambda action, *args: (updates.append(action) or sqlite3.SQLITE_OK)
                                      if action == sqlite3.SQLITE_UPDATE else sqlite3.SQLITE_OK)
            with self.subTest(rejected=rejected), patch.object(btc_db, "_connect", return_value=connection):
                with self.assertRaises(btc_db.DbError):
                    nfc.import_csv(self.url, path)
            self.assertEqual(updates, [], "database validation must finish before first UPDATE")
            self.assertEqual(self.query("SELECT * FROM wallets ORDER BY serial"), before)

    def test_migration_rejects_incompatible_schema_without_changes(self):
        nfc = module()
        definitions = ("nfc_uid INTEGER", "nfc_uid TEXT NOT NULL DEFAULT ''",
                       "nfc_uid TEXT DEFAULT 'SYNTH'", "nfc_uid TEXT GENERATED ALWAYS AS (address) VIRTUAL")
        for definition in definitions:
            with self.subTest(definition=definition):
                with closing(sqlite3.connect(self.url)) as conn, conn:
                    conn.execute("DROP TABLE IF EXISTS incompatible")
                    conn.execute(f"CREATE TABLE incompatible (serial TEXT, address TEXT, jalali_datetime TEXT, created_utc TEXT, {definition})")
                before = self.query("SELECT sql FROM sqlite_master ORDER BY name")
                with self.assertRaises(btc_db.DbError):
                    nfc.migrate_nfc_uid(self.url, "incompatible")
                self.assertEqual(self.query("SELECT sql FROM sqlite_master ORDER BY name"), before)
        with closing(sqlite3.connect(self.url)) as conn, conn:
            conn.execute("CREATE TABLE not_ledger (address TEXT)")
        for table in ("missing", "not_ledger", 'wallets"; DROP TABLE wallets;--'):
            with self.assertRaises(btc_db.DbError):
                nfc.migrate_nfc_uid(self.url, table)

    def test_wrong_named_index_cannot_fake_migration_and_ddl_rolls_back(self):
        nfc = module()
        with closing(sqlite3.connect(self.url)) as conn, conn:
            conn.execute("CREATE INDEX wallets_nfc_uid_unique ON wallets(address)")
        before = self.query("SELECT * FROM wallets")
        with self.assertRaises(btc_db.DbError):
            nfc.migrate_nfc_uid(self.url)
        self.assertNotIn("nfc_uid", [c[1] for c in self.query("PRAGMA table_info(wallets)")])
        self.assertEqual(self.query("SELECT * FROM wallets"), before)

    def test_direct_cli_migrate_import_replay_and_private_errors(self):
        path = self.csv([("04ABCDEF", ADDRESSES[0])])
        script = ROOT / "btc_envelope_maker" / "nfc_bindings.py"
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "BTC_DB_URL")}
        def run(*args):
            return subprocess.run([sys.executable, str(script), *args], cwd=self.directory,
                                  env=env, capture_output=True, text=True, timeout=20)
        result = run("import", str(path), "--db", self.url)
        self.assertEqual(result.returncode, 1)
        result = run("migrate", "--db", self.url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NFC UID schema ready", result.stdout)
        result = run("import", str(path), "--db", self.url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 assigned, 0 already present", result.stdout)
        result = run("import", str(path), "--db", self.url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 assigned, 1 already present", result.stdout)
        self.assertEqual(self.query("SELECT nfc_uid FROM wallets WHERE address = ?", (ADDRESSES[0],)), [("04ABCDEF",)])
        for args in (("SYNTH_PRIVATE_ARGUMENT",), ("import", "SYNTH_PRIVATE_PATH", "--db", self.url),
                     ("migrate", "--db", "SYNTH_PRIVATE_BAD_URL")):
            result = run(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("SYNTH", result.stdout + result.stderr)

    def test_late_database_failure_rolls_back_all_bindings(self):
        nfc = module()
        nfc.migrate_nfc_uid(self.url)
        with closing(sqlite3.connect(self.url)) as conn, conn:
            conn.execute("CREATE TRIGGER reject_second BEFORE UPDATE OF nfc_uid ON wallets "
                         "WHEN NEW.serial = 'SYNTH_SERIAL_1' BEGIN SELECT RAISE(ABORT, 'SYNTH_PRIVATE_FAILURE'); END")
        before = self.query("SELECT * FROM wallets ORDER BY serial")
        with self.assertRaises(btc_db.DbError) as raised:
            nfc.import_csv(self.url, self.csv([("04ABCDEF", ADDRESSES[0]), ("04AAAAAA", ADDRESSES[1])]))
        self.assertNotIn("SYNTH", str(raised.exception))
        self.assertEqual(self.query("SELECT * FROM wallets ORDER BY serial"), before)

    def test_import_refuses_manually_added_nonunique_uid_column(self):
        nfc = module()
        with closing(sqlite3.connect(self.url)) as conn, conn:
            conn.execute("ALTER TABLE wallets ADD COLUMN nfc_uid TEXT")
        with self.assertRaises(btc_db.DbError):
            nfc.import_csv(self.url, self.csv([("04ABCDEF", ADDRESSES[0])]))
        self.assertEqual(self.query("SELECT nfc_uid FROM wallets"), [(None,)] * 3)

    def test_explicit_migration_preserves_rows_is_idempotent_and_unique(self):
        nfc = module()
        before = self.query("SELECT * FROM wallets ORDER BY serial")
        nfc.migrate_nfc_uid(self.url)
        nfc.migrate_nfc_uid(self.url)
        after = self.query("SELECT * FROM wallets ORDER BY serial")
        self.assertEqual(after, [row + (None,) for row in before])
        column = next(row for row in self.query('PRAGMA table_info("wallets")') if row[1] == "nfc_uid")
        self.assertEqual(column[2:4], ("TEXT", 0))
        with closing(sqlite3.connect(self.url)) as conn, conn:
            conn.execute("UPDATE wallets SET nfc_uid = ? WHERE address = ?", ("04ABCDEF", ADDRESSES[0]))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE wallets SET nfc_uid = ? WHERE address = ?", ("04ABCDEF", ADDRESSES[1]))


@unittest.skipUnless(os.environ.get("NFC_TEST_POSTGRES") == "1", "opt-in disposable local Docker PostgreSQL")
class LocalPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.name = "nfc-binding-proof-" + uuid.uuid4().hex[:12]
        cls.docker = ["docker", "--host", "unix:///var/run/docker.sock"]
        subprocess.run(cls.docker + ["run", "--detach", "--name", cls.name,
                       "--publish", "127.0.0.1::5432", "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
                       "--tmpfs", "/var/lib/postgresql", "postgres:18-bookworm"],
                       check=True, capture_output=True, text=True, timeout=30)
        cls.addClassCleanup(cls.remove_container)
        endpoint = subprocess.check_output(cls.docker + ["port", cls.name, "5432/tcp"], text=True).strip()
        if not endpoint.startswith("127.0.0.1:"):
            raise AssertionError("test PostgreSQL must bind loopback only")
        cls.url = "postgresql://postgres@" + endpoint + "/postgres"
        for _ in range(100):
            try:
                with psycopg.connect(cls.url, connect_timeout=1):
                    return
            except psycopg.OperationalError:
                time.sleep(0.1)
        raise AssertionError("disposable PostgreSQL TCP startup timed out")

    @classmethod
    def remove_container(cls):
        subprocess.run(cls.docker + ["rm", "--force", cls.name], check=True, capture_output=True, timeout=30)
        names = subprocess.check_output(cls.docker + ["ps", "--all", "--format", "{{.Names}}"], text=True).splitlines()
        if cls.name in names:
            raise AssertionError("disposable PostgreSQL container cleanup failed")

    def test_real_postgres_migration_import_replay_conflict_and_preservation(self):
        nfc = module()
        import psycopg
        btc_db.save_rows(self.url, "wallets", [btc_db.Row("SYNTH_0", ADDRESSES[0]), btc_db.Row("SYNTH_1", ADDRESSES[1])])
        with psycopg.connect(self.url) as conn:
            conn.execute("UPDATE wallets SET notes = %s", ("SYNTH_NOTE",))
            before = conn.execute("SELECT * FROM wallets ORDER BY serial").fetchall()
        directory = tempfile.TemporaryDirectory(prefix="nfc-pg-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "captures.csv"
        path.write_text(f"uid,address,captured_at\n04ABCDEF,{ADDRESSES[0]},2026-01-01T00:00:00Z\n", encoding="utf-8")
        with self.assertRaises(btc_db.DbError):
            nfc.import_csv(self.url, path)
        nfc.migrate_nfc_uid(self.url)
        nfc.migrate_nfc_uid(self.url)
        self.assertEqual(nfc.import_csv(self.url, path), (1, 0))
        self.assertEqual(nfc.import_csv(self.url, path), (0, 1))
        path.write_text(f"uid,address,captured_at\n04BBBBBB,{ADDRESSES[1]},2026-01-01T00:00:00Z\n04AAAAAA,{ADDRESSES[0]},2026-01-01T00:00:00Z\n", encoding="utf-8")
        with self.assertRaises(btc_db.DbError):
            nfc.import_csv(self.url, path)
        with psycopg.connect(self.url) as conn:
            after = conn.execute("SELECT * FROM wallets ORDER BY serial").fetchall()
            self.assertEqual([r[:-1] for r in after], before)
            self.assertEqual([r[-1] for r in after], ["04ABCDEF", None])
            with self.assertRaises(psycopg.errors.UniqueViolation):
                conn.execute("UPDATE wallets SET nfc_uid = %s WHERE address = %s", ("04ABCDEF", ADDRESSES[1]))


if __name__ == "__main__":
    unittest.main()

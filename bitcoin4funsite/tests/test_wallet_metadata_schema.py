"""Private schema evolution: disposable SQLite only; PostgreSQL is injected/fake."""
from __future__ import annotations

import contextlib
from dataclasses import fields
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from bech32 import encode

# Synthetic witness bytes, not generated wallets or public preview vectors.
SYNTHETIC_ADDRESS = encode("bc", 0, list(range(20)))
SYNTHETIC_ADDRESS_2 = encode("bc", 0, list(range(1, 21)))

GENERATOR_PATH = Path(__file__).resolve().parents[2] / "btc_envelope_maker"
sys.path.insert(0, str(GENERATOR_PATH))
import btc_db

CONTACT_COLUMNS = ("contact_type", "contact_value", "notes")
PUBLIC_COLUMNS = ("serial", "address", "jalali_datetime", "created_utc")


class SQLiteMetadataSchema(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="wallet-metadata-schema-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "disposable.sqlite3"
        self.url = str(self.path)

    @contextlib.contextmanager
    def database(self):
        # sqlite3's own context manager commits/rolls back but does not close.
        with contextlib.closing(sqlite3.connect(self.path)) as conn, conn:
            yield conn

    def columns(self, table="wallets"):
        with self.database() as conn:
            return {row[1]: row for row in conn.execute(f'PRAGMA table_info("{table}")')}

    def test_fresh_table_has_nullable_text_contact_columns_with_null_defaults(self):
        btc_db.check(self.url)
        columns = self.columns()
        self.assertEqual(tuple(columns), PUBLIC_COLUMNS + CONTACT_COLUMNS)
        for name in CONTACT_COLUMNS:
            with self.subTest(column=name):
                self.assertEqual(columns[name][2].upper(), "TEXT")
                self.assertEqual(columns[name][3], 0)
                self.assertIn(columns[name][4], (None, "NULL"))
        btc_db.save_rows(self.url, "wallets", [btc_db.Row("fixture-1", SYNTHETIC_ADDRESS)])
        with self.database() as conn:
            self.assertEqual(conn.execute("SELECT contact_type, contact_value, notes FROM wallets").fetchall(),
                             [(None, None, None)])

    def create_old_table(self):
        with self.database() as conn:
            conn.execute("CREATE TABLE wallets (serial TEXT PRIMARY KEY, address TEXT NOT NULL UNIQUE, "
                         "jalali_datetime TEXT, created_utc TEXT)")
            conn.executemany("INSERT INTO wallets VALUES (?, ?, ?, ?)", [
                ("fixture-1", "public-address-1", "unchanged timestamp text", None),
                ("fixture-2", "public-address-2", "", "2026-01-01 00:00:00 UTC"),
            ])

    def migrate(self, table="wallets"):
        self.assertTrue(callable(getattr(btc_db, "migrate_contact_columns", None)),
                        "explicit admin migration API is missing")
        return btc_db.migrate_contact_columns(self.url, table)

    def test_existing_schema_migration_is_repeatable_without_row_loss_or_rebuild(self):
        self.create_old_table()
        with self.database() as conn:
            before = conn.execute("SELECT rowid, * FROM wallets ORDER BY serial").fetchall()
            rootpage = conn.execute("SELECT rootpage FROM sqlite_master WHERE name='wallets'").fetchone()
        self.assertIsNone(self.migrate())
        self.assertIsNone(self.migrate())
        self.assertEqual(tuple(self.columns()), PUBLIC_COLUMNS + CONTACT_COLUMNS)
        with self.database() as conn:
            self.assertEqual(conn.execute("SELECT rowid, serial, address, jalali_datetime, created_utc "
                                          "FROM wallets ORDER BY serial").fetchall(), before)
            self.assertEqual(conn.execute("SELECT rootpage FROM sqlite_master WHERE name='wallets'").fetchone(), rootpage)
            self.assertEqual(conn.execute("SELECT contact_type, contact_value, notes FROM wallets").fetchall(),
                             [(None, None, None), (None, None, None)])

    def test_incompatible_existing_contact_type_aborts_without_adding_columns(self):
        self.create_old_table()
        with self.database() as conn:
            conn.execute("ALTER TABLE wallets ADD COLUMN notes INTEGER")
            conn.execute("UPDATE wallets SET notes=42 WHERE serial='fixture-1'")
            before = conn.execute("SELECT rowid, * FROM wallets ORDER BY serial").fetchall()
        with self.assertRaisesRegex(btc_db.DbError, "incompatible"):
            self.migrate()
        self.assertEqual(tuple(self.columns()), PUBLIC_COLUMNS + ("notes",))
        with self.database() as conn:
            self.assertEqual(conn.execute("SELECT rowid, * FROM wallets ORDER BY serial").fetchall(), before)

    def test_incompatible_nullability_or_default_aborts_without_ddl(self):
        for declaration in ("TEXT NOT NULL DEFAULT 'synthetic-private-default'",
                            "TEXT DEFAULT 'synthetic-private-default'"):
            with self.subTest(declaration=declaration):
                with self.database() as conn:
                    conn.execute("DROP TABLE IF EXISTS wallets")
                self.create_old_table()
                with self.database() as conn:
                    conn.execute("ALTER TABLE wallets ADD COLUMN notes " + declaration)
                with self.assertRaisesRegex(btc_db.DbError, "incompatible") as raised:
                    self.migrate()
                self.assertNotIn("synthetic-private-default", str(raised.exception))
                self.assertNotIn("contact_type", self.columns())

    def test_malformed_existing_table_is_not_enriched_with_private_columns(self):
        with self.database() as conn:
            conn.execute("CREATE TABLE wallets (unrelated TEXT)")
        with self.assertRaises(btc_db.DbError):
            self.migrate()
        self.assertEqual(tuple(self.columns()), ("unrelated",))

    def test_explicit_cli_migrates_existing_table_without_connection_or_metadata_output(self):
        self.create_old_table()
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                result = btc_db.main(["migrate-contact", "--db", self.url])
            except SystemExit as exc:
                self.fail(f"migrate-contact command is unavailable (parser exit {exc.code})")
        self.assertEqual(result, 0)
        self.assertIn("contact metadata", output.getvalue())
        self.assertNotIn(self.url, output.getvalue())
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(tuple(self.columns()), PUBLIC_COLUMNS + CONTACT_COLUMNS)

    def test_partial_migration_preserves_existing_private_values_exactly(self):
        self.create_old_table()
        private_note = "synthetic private note\nunchanged Unicode: نمونه"
        with self.database() as conn:
            conn.execute("ALTER TABLE wallets ADD COLUMN notes TEXT DEFAULT NULL")
            conn.execute("UPDATE wallets SET notes=? WHERE serial='fixture-1'", (private_note,))
            before = conn.execute("SELECT rowid, * FROM wallets ORDER BY serial").fetchall()
        self.migrate()
        self.migrate()
        with self.database() as conn:
            self.assertEqual(conn.execute("SELECT rowid, serial, address, jalali_datetime, created_utc, notes "
                                          "FROM wallets ORDER BY serial").fetchall(), before)
            self.assertEqual(conn.execute("SELECT contact_type, contact_value FROM wallets").fetchall(),
                             [(None, None), (None, None)])

    def test_injected_mid_migration_failure_rolls_back_real_sqlite_ddl(self):
        self.create_old_table()
        with self.database() as conn:
            before = conn.execute("SELECT rowid, * FROM wallets ORDER BY serial").fetchall()
        statements = []
        real_connect = btc_db._connect

        class FailingCursor:
            def __init__(self, cursor):
                self.cursor = cursor

            def execute(self, sql, params=()):
                statements.append(sql)
                if "ADD COLUMN contact_value" in sql:
                    raise sqlite3.OperationalError("SYNTHETIC_PRIVATE_INJECTED_ERROR")
                return self.cursor.execute(sql, params)

            def fetchall(self):
                return self.cursor.fetchall()

            def fetchone(self):
                return self.cursor.fetchone()

        class FailingConnection:
            def __init__(self, connection):
                self.connection = connection

            def cursor(self):
                return FailingCursor(self.connection.cursor())

            def __getattr__(self, name):
                return getattr(self.connection, name)

        def connect(kind, target):
            return FailingConnection(real_connect(kind, target))

        with patch.object(btc_db, "_connect", side_effect=connect):
            with self.assertRaises(btc_db.DbError) as raised:
                self.migrate()
        self.assertNotIn("SYNTHETIC_PRIVATE_INJECTED_ERROR", str(raised.exception))
        self.assertTrue(any("ADD COLUMN contact_type" in sql for sql in statements))
        self.assertEqual(tuple(self.columns()), PUBLIC_COLUMNS)
        with self.database() as conn:
            self.assertEqual(conn.execute("SELECT rowid, * FROM wallets ORDER BY serial").fetchall(), before)

    def test_check_and_generator_insert_do_not_migrate_existing_table(self):
        self.create_old_table()
        with patch.object(btc_db, "migrate_contact_columns", side_effect=AssertionError("must be explicit")):
            btc_db.check(self.url)
            self.assertEqual(btc_db.save_rows(self.url, "wallets", [btc_db.Row("fixture-3", SYNTHETIC_ADDRESS)]),
                             (1, 0))
        self.assertEqual(tuple(self.columns()), PUBLIC_COLUMNS)

    def test_public_row_csv_import_and_list_never_expose_or_overwrite_private_metadata(self):
        self.assertEqual(tuple(field.name for field in fields(btc_db.Row)), PUBLIC_COLUMNS)
        with self.assertRaises(TypeError):
            btc_db.Row("fixture-1", "public-address-1", contact_type="email")
        btc_db.check(self.url)
        public_address = SYNTHETIC_ADDRESS
        btc_db.save_rows(self.url, "wallets", [btc_db.Row("fixture-1", public_address)])
        private = ("email", "synthetic-private-contact@example.invalid", "synthetic private notes")
        with self.database() as conn:
            conn.execute("UPDATE wallets SET contact_type=?, contact_value=?, notes=? WHERE serial='fixture-1'", private)
        ledger = Path(self.directory.name) / "public-ledger.csv"
        ledger.write_text("serial,address,jalali_datetime,created_utc,contact_type,contact_value,notes\n"
                          f"fixture-1,{public_address},,,phone,synthetic-overwrite,synthetic-overwrite\n"
                          f"fixture-2,{SYNTHETIC_ADDRESS_2},,,phone,synthetic-overwrite,synthetic-overwrite\n", encoding="utf-8")
        rows = btc_db.read_ledger(ledger)
        self.assertEqual(rows, [btc_db.Row("fixture-1", public_address), btc_db.Row("fixture-2", SYNTHETIC_ADDRESS_2)])
        self.assertNotIn("synthetic-overwrite", repr(rows))
        self.assertEqual(btc_db.save_rows(self.url, "wallets", rows, skip_existing=True), (1, 1))
        self.migrate()
        with self.database() as conn:
            self.assertEqual(conn.execute("SELECT contact_type, contact_value, notes FROM wallets "
                                          "WHERE serial='fixture-1'").fetchone(), private)
            self.assertEqual(conn.execute("SELECT contact_type, contact_value, notes FROM wallets "
                                          "WHERE serial='fixture-2'").fetchone(), (None, None, None))
        public_rows = btc_db.list_rows(self.url)
        self.assertEqual(len(public_rows), 2)
        self.assertTrue(all(len(row) == len(PUBLIC_COLUMNS) for row in public_rows))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(btc_db.main(["list", "--db", self.url]), 0)
        for value in private:
            self.assertNotIn(value, output.getvalue())
            self.assertNotIn(value, repr(public_rows))

    def test_missing_table_is_not_created_by_migration(self):
        with self.assertRaises(btc_db.DbError):
            self.migrate()
        self.assertEqual(self.columns(), {})

    def test_custom_validated_target_does_not_change_default_table(self):
        self.create_old_table()
        with self.database() as conn:
            conn.execute("CREATE TABLE target_wallets AS SELECT * FROM wallets")
            before = conn.execute("SELECT * FROM target_wallets ORDER BY serial").fetchall()
        self.migrate("target_wallets")
        self.assertEqual(tuple(self.columns()), PUBLIC_COLUMNS)
        self.assertEqual(tuple(self.columns("target_wallets")), PUBLIC_COLUMNS + CONTACT_COLUMNS)
        with self.database() as conn:
            self.assertEqual(conn.execute("SELECT serial, address, jalali_datetime, created_utc "
                                          "FROM target_wallets ORDER BY serial").fetchall(), before)

    def test_view_with_matching_columns_is_not_a_migratable_table(self):
        self.create_old_table()
        with self.database() as conn:
            conn.execute("ALTER TABLE wallets RENAME TO backing")
            for name in CONTACT_COLUMNS:
                conn.execute(f"ALTER TABLE backing ADD COLUMN {name} TEXT DEFAULT NULL")
            conn.execute("CREATE VIEW wallets AS SELECT * FROM backing")
        with self.assertRaises(btc_db.DbError):
            self.migrate()

    def test_postgres_fresh_ddl_includes_nullable_private_text_columns(self):
        ddl = btc_db._ddl("postgres", "wallets")
        for name in CONTACT_COLUMNS:
            self.assertIn(f"{name} TEXT DEFAULT NULL", ddl)
        self.assertIn("created_utc TIMESTAMPTZ", ddl)


class InvalidMetadataTableName(unittest.TestCase):
    def test_invalid_table_names_fail_before_connect_without_echoing_input(self):
        for table in ("wallets;DROP TABLE wallets", "public.wallets", "", "wallets\n",
                      "a" * 64, "synthetic-private-table!", 'wallets"', "wallets value"):
            with self.subTest(table=table):
                with patch.object(btc_db, "_connect") as connect:
                    with self.assertRaises(btc_db.DbError) as raised:
                        btc_db.migrate_contact_columns("postgresql://synthetic.invalid/never-connect", table)
                connect.assert_not_called()
                if table:
                    self.assertNotIn(table, str(raised.exception))


class FakePostgresConnection:
    """SQL-call recorder only; deliberately never opens a database connection."""
    def __init__(self, private_columns=None, fail_alter=None, missing=False):
        self.calls = []
        self.commits = self.rollbacks = self.closes = 0
        self.private_columns = private_columns or []
        self.fail_alter = fail_alter
        self.missing = missing
        self.result = []

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "FROM pg_catalog.pg_class" in sql:
            self.result = [] if self.missing else [("fixture_schema", "wallets_archive")]
        elif "FROM pg_catalog.pg_attribute" in sql:
            self.result = [(name, True, False, None, "", "") for name in PUBLIC_COLUMNS] + self.private_columns
        else:
            self.result = []
        if sql.startswith("ALTER TABLE") and self.fail_alter and self.fail_alter in sql:
            raise RuntimeError("SYNTHETIC_PRIVATE_DATABASE_ERROR")
        return self

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


class PostgresMetadataSchema(unittest.TestCase):
    def test_migration_uses_bounded_transaction_validated_target_only_and_no_value_reads(self):
        connection = FakePostgresConnection()
        with patch.object(btc_db, "_connect", return_value=connection) as connect:
            btc_db.migrate_contact_columns("postgresql://synthetic.invalid/never-connect", "wallets_archive")
        connect.assert_called_once_with("postgres", "postgresql://synthetic.invalid/never-connect")
        self.assertEqual(connection.calls[:2], [
            ("SET LOCAL lock_timeout = '2s'", None),
            ("SET LOCAL statement_timeout = '10s'", None),
        ])
        self.assertTrue(any(params == ("wallets_archive",) for sql, params in connection.calls
                            if "FROM pg_catalog.pg_class" in sql))
        self.assertIn(('LOCK TABLE ONLY "fixture_schema"."wallets_archive" IN ACCESS EXCLUSIVE MODE', None), connection.calls)
        alterations = [sql for sql, _ in connection.calls if sql.startswith("ALTER TABLE")]
        self.assertEqual(alterations, [
            f'ALTER TABLE ONLY "fixture_schema"."wallets_archive" ADD COLUMN IF NOT EXISTS {name} TEXT DEFAULT NULL'
            for name in CONTACT_COLUMNS
        ])
        for sql, _ in connection.calls:
            self.assertNotIn("CREATE TABLE", sql)
            self.assertNotIn("DROP", sql)
            self.assertNotIn("UPDATE", sql)
            if sql.startswith("SELECT"):
                self.assertIn("pg_catalog.", sql)
                self.assertNotIn("SELECT *", sql)
        self.assertEqual((connection.commits, connection.rollbacks, connection.closes), (1, 0, 1))


    def test_postgres_existing_private_columns_are_checked_on_every_rerun(self):
        columns = [(name, True, False, None, "", "") for name in CONTACT_COLUMNS]
        for _ in range(2):
            connection = FakePostgresConnection(private_columns=columns)
            with patch.object(btc_db, "_connect", return_value=connection):
                btc_db.migrate_contact_columns("postgresql://synthetic.invalid/never-connect", "wallets_archive")
            self.assertEqual((connection.commits, connection.rollbacks, connection.closes), (1, 0, 1))
            self.assertEqual(len([sql for sql, _ in connection.calls if "ADD COLUMN IF NOT EXISTS" in sql]), 3)

    def test_postgres_incompatible_types_defaults_nullability_and_generated_columns_fail_closed(self):
        invalid = [
            ("notes", False, False, None, "", ""),
            ("notes", True, True, None, "", ""),
            ("notes", True, False, "'synthetic-private-default'::text", "", ""),
            ("notes", True, False, None, "", "s"),
            ("notes", True, False, None, "a", ""),
        ]
        for column in invalid:
            with self.subTest(case=invalid.index(column)):
                connection = FakePostgresConnection(private_columns=[column])
                with patch.object(btc_db, "_connect", return_value=connection):
                    with self.assertRaisesRegex(btc_db.DbError, "incompatible") as raised:
                        btc_db.migrate_contact_columns("postgresql://synthetic.invalid/never-connect", "wallets_archive")
                self.assertNotIn("synthetic-private-default", str(raised.exception))
                self.assertFalse(any(sql.startswith("ALTER TABLE") for sql, _ in connection.calls))
                self.assertEqual((connection.commits, connection.rollbacks, connection.closes), (0, 1, 1))

    def test_postgres_mid_ddl_error_rolls_back_and_redacts_database_error(self):
        connection = FakePostgresConnection(fail_alter="contact_value")
        with patch.object(btc_db, "_connect", return_value=connection):
            with self.assertRaises(btc_db.DbError) as raised:
                btc_db.migrate_contact_columns("postgresql://synthetic.invalid/never-connect", "wallets_archive")
        self.assertNotIn("SYNTHETIC_PRIVATE_DATABASE_ERROR", str(raised.exception))
        self.assertEqual((connection.commits, connection.rollbacks, connection.closes), (0, 1, 1))
        self.assertEqual(len([sql for sql, _ in connection.calls if "ADD COLUMN IF NOT EXISTS" in sql]), 2)

    def test_postgres_missing_table_does_not_create_or_alter_any_table(self):
        connection = FakePostgresConnection(missing=True)
        with patch.object(btc_db, "_connect", return_value=connection):
            with self.assertRaises(btc_db.DbError):
                btc_db.migrate_contact_columns("postgresql://synthetic.invalid/never-connect", "wallets_archive")
        self.assertFalse(any(sql.startswith(("ALTER", "CREATE", "LOCK")) for sql, _ in connection.calls))
        self.assertEqual((connection.commits, connection.rollbacks, connection.closes), (0, 1, 1))

    def test_connection_error_is_redacted_by_migration_and_cli(self):
        with patch.object(btc_db, "_connect", side_effect=btc_db.DbError("SYNTHETIC_PRIVATE_CONNECTION_ERROR")):
            with self.assertRaises(btc_db.DbError) as raised:
                btc_db.migrate_contact_columns("postgresql://synthetic.invalid/never-connect")
            self.assertNotIn("SYNTHETIC_PRIVATE_CONNECTION_ERROR", str(raised.exception))
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(btc_db.main(["migrate-contact", "--db", "postgresql://synthetic.invalid/never-connect"]), 1)
            self.assertEqual(output.getvalue(), "")
            self.assertNotIn("SYNTHETIC_PRIVATE_CONNECTION_ERROR", errors.getvalue())


if __name__ == "__main__":
    unittest.main()

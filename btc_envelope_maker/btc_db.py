#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
btc_db.py - tiny database layer for btc_envelope_maker.

The public ledger contains only serial/address and timestamps. The database may
also hold nullable PRIVATE contact_type, contact_value and notes (TEXT) for an
administrator's use. They are not public ledger data: Row, CSV import and list
never accept, select or export them. Never store recovery words or private keys.

Connection strings
  SQLite   : sqlite:///wallets.db          (relative path)
             sqlite:////home/me/wallets.db (absolute path: four slashes)
             or just a path ending in .db / .sqlite / .sqlite3
  Postgres : postgresql://user:password@host:5432/dbname      (needs:  pip install "psycopg[binary]")

Fresh tables include the three private columns, default NULL. Existing tables
are NOT upgraded by check() or save_rows(); use the explicit owner/admin
migrate-contact command. This module does not grant access to private columns:
keep public database roles restricted to the public columns they need.

Stand-alone use (from this repository; needs bech32, + psycopg for Postgres):
  python btc_db.py import out/batch_0587k4530/ledger.csv --db "postgresql://..."
  python btc_db.py list --db "sqlite:///wallets.db"
  python btc_db.py migrate-contact --db "sqlite:///wallets.db"  # owner/admin only
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from urllib.parse import unquote, urlsplit

DEFAULT_TABLE = "wallets"
ENV_VAR = "BTC_DB_URL"
TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
# Support direct `python btc_db.py` as well as imports from the repository root.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bitcoin4funsite.address_validation import valid_inventory_address


class DbError(Exception):
    pass


def _safe_errors(function):
    """Also contain cleanup/driver failures that bypass inner error handlers."""
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except DbError:
            raise
        except Exception:
            raise DbError("database operation failed; details withheld") from None
    return guarded


@dataclass(frozen=True)
class Row:
    """Public ledger input only: no contact metadata, recovery words or keys."""
    serial: str
    address: str
    jalali_datetime: str = ""
    created_utc: str = ""          # "YYYY-MM-DD HH:MM:SS UTC" (same text as in ledger.csv)


# --------------------------------------------------------------------------------------
def check_table(table: str) -> str:
    if not TABLE_RE.fullmatch(table or ""):
        raise DbError("invalid table name (1-63 ASCII letters, digits and _; cannot start with a digit)")
    return table


def parse_url(url: str) -> tuple[str, str]:
    """-> ('sqlite', path) or ('postgres', normalized_url)"""
    u = (url or "").strip()
    if not u:
        raise DbError("empty database connection string")
    low = u.lower()
    if low.startswith("sqlite:"):
        rest = u[len("sqlite:"):]
        path = rest[3:] if rest.startswith("///") else rest[2:] if rest.startswith("//") else rest
        path = os.path.expanduser(unquote(path))
        if not path or path == ":memory:":
            raise DbError("an in-memory SQLite database would be lost immediately; give a file path")
        return "sqlite", path
    m = re.match(r"^(postgres|postgresql)(\+\w+)?://", u, re.I)
    if m:
        normalized = "postgresql://" + u[m.end():]
        try:
            if any(ord(c) < 32 or ord(c) == 127 for c in u):
                raise ValueError
            parts = urlsplit(normalized)
            _ = parts.hostname, parts.port  # force bracket/port validation
        except ValueError:
            raise DbError("invalid database connection string") from None
        return "postgres", normalized
    if "://" not in u and low.endswith((".db", ".sqlite", ".sqlite3")):
        return "sqlite", os.path.expanduser(u)
    raise DbError("unsupported connection string. Use sqlite:///file.db or postgresql://user:pass@host/db")


def mask(url: str) -> str:
    """Compatibility alias for the safe description, never a masked raw URL."""
    return describe(url)


def describe(url: str) -> str:
    """Construct display text from safe components, never userinfo/query/fragment."""
    kind, target = parse_url(url)
    if kind == "sqlite":
        return "sqlite: local database"
    try:
        parts = urlsplit(target)
        host = parts.hostname or "local"
        port = parts.port
        database = parts.path.removeprefix("/")
        # Unsafe or ambiguous components are omitted, not decoded for display.
        if re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host) is None:
            host = "[host omitted]"
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,63}", database) is None:
            database = "[database omitted]"
        return f"postgres: {host}{':' + str(port) if port is not None else ''}/{database}"
    except (ValueError, TypeError):
        raise DbError("invalid database connection string") from None


@_safe_errors
def _connect(kind: str, target: str):
    if kind == "sqlite":
        parent = Path(target).resolve().parent
        if not parent.is_dir():
            raise DbError("SQLite parent folder does not exist")
        try:
            return sqlite3.connect(target, timeout=10)
        except sqlite3.Error:
            raise DbError("cannot open SQLite file") from None
    try:
        import psycopg as pg                      # psycopg 3
    except ImportError:
        try:
            import psycopg2 as pg                 # psycopg 2
        except ImportError:
            raise DbError('PostgreSQL needs a driver:  pip install "psycopg[binary]"') from None
    try:
        return pg.connect(target, connect_timeout=10)
    except Exception:
        raise DbError("cannot connect to PostgreSQL; details withheld") from None


def _ddl(kind: str, table: str) -> str:
    ts = "TEXT" if kind == "sqlite" else "TIMESTAMPTZ"
    return (f"CREATE TABLE IF NOT EXISTS {table} (serial TEXT PRIMARY KEY, address TEXT NOT NULL UNIQUE, "
            f"jalali_datetime TEXT, created_utc {ts}, contact_type TEXT DEFAULT NULL, "
            "contact_value TEXT DEFAULT NULL, notes TEXT DEFAULT NULL)")


@_safe_errors
def migrate_contact_columns(url: str, table: str = DEFAULT_TABLE) -> None:
    """Explicit administrator-only migration of private metadata on an existing table.

    Never called by check(), save_rows(), or the website. It neither reads wallet
    values nor updates/rebuilds rows. Run with the table owner's DDL privileges;
    private metadata is not part of Row or the public ledger.

    The table must already exist with the four public ledger columns. Existing
    private columns must be nullable TEXT with a NULL/no default, not generated.
    PostgreSQL uses SET LOCAL lock_timeout=2s and statement_timeout=10s, and
    resolves the validated unqualified name through the connection search_path.
    Success returns None; incompatible schema or failure raises a value-free
    DbError and rolls back. No permissions are granted or changed.
    """
    check_table(table)
    kind, target = parse_url(url)
    try:
        conn = _connect(kind, target)
    except Exception:
        raise DbError("cannot connect for contact metadata migration") from None
    try:
        cur = conn.cursor()
        if kind == "sqlite":
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT type FROM sqlite_master WHERE name = ? COLLATE NOCASE", (table,))
            if cur.fetchone() != ("table",):
                raise DbError("existing wallet table not found; nothing was changed")
            cur.execute(f'PRAGMA table_info("{table}")')
            columns = {row[1].lower(): row for row in cur.fetchall()}
            if not {"serial", "address", "jalali_datetime", "created_utc"}.issubset(columns):
                raise DbError("existing table is missing public ledger columns; nothing was changed")
            for name in ("contact_type", "contact_value", "notes"):
                if name in columns:
                    column = columns[name]
                    default = column[4]
                    if (column[2].strip().upper() != "TEXT" or column[3] or column[5]
                            or (default is not None and default.strip().upper() != "NULL")):
                        raise DbError("incompatible contact metadata schema; nothing was changed")
            for name in ("contact_type", "contact_value", "notes"):
                if name not in columns:
                    cur.execute(f'ALTER TABLE "{table}" ADD COLUMN {name} TEXT DEFAULT NULL')
        else:
            cur.execute("SET LOCAL lock_timeout = '2s'")
            cur.execute("SET LOCAL statement_timeout = '10s'")
            # Resolve the normal search-path target once, then pin every operation
            # to its quoted schema/table. No wallet values or unrelated tables read.
            cur.execute("SELECT n.nspname, c.relname FROM pg_catalog.pg_class c "
                        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE c.oid = pg_catalog.to_regclass(%s) AND c.relkind = 'r'", (table,))
            relation = cur.fetchone()
            if relation is None:
                raise DbError("existing wallet table not found; nothing was changed")
            qualified = ".".join('"' + name.replace('"', '""') + '"' for name in relation)
            cur.execute(f"LOCK TABLE ONLY {qualified} IN ACCESS EXCLUSIVE MODE")
            cur.execute("SELECT a.attname, a.atttypid = 'pg_catalog.text'::pg_catalog.regtype, "
                        "a.attnotnull, pg_catalog.pg_get_expr(d.adbin, d.adrelid), "
                        "a.attidentity, a.attgenerated FROM pg_catalog.pg_attribute a "
                        "LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
                        "WHERE a.attrelid = pg_catalog.to_regclass(%s) "
                        "AND a.attnum > 0 AND NOT a.attisdropped", (qualified,))
            columns = {row[0]: row for row in cur.fetchall()}
            if not {"serial", "address", "jalali_datetime", "created_utc"}.issubset(columns):
                raise DbError("existing table is missing public ledger columns; nothing was changed")
            for name in ("contact_type", "contact_value", "notes"):
                if name in columns:
                    _, is_text, not_null, default, identity, generated = columns[name]
                    if (not is_text or not_null or identity or generated
                            or default not in (None, "NULL::text")):
                        raise DbError("incompatible contact metadata schema; nothing was changed")
            for name in ("contact_type", "contact_value", "notes"):
                cur.execute(f"ALTER TABLE ONLY {qualified} ADD COLUMN IF NOT EXISTS {name} TEXT DEFAULT NULL")
        conn.commit()
    except DbError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        # Database exceptions can contain private values or connection details.
        raise DbError("contact metadata migration failed; nothing was changed") from None
    finally:
        conn.close()


def _created_value(kind: str, text: str):
    if not text:
        return None
    try:
        d = dt.datetime.strptime(text.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if kind == "sqlite" else d


# --------------------------------------------------------------------------------------
@_safe_errors
def check(url: str, table: str = DEFAULT_TABLE) -> None:
    """Create a fresh table if absent; never migrate an existing table (pre-flight)."""
    check_table(table)
    kind, target = parse_url(url)
    conn = _connect(kind, target)
    try:
        conn.cursor().execute(_ddl(kind, table))
        conn.commit()
    except Exception:
        conn.rollback()
        raise DbError("database check failed; details withheld") from None
    finally:
        conn.close()


@_safe_errors
def save_rows(url: str, table: str, rows: list[Row], *, skip_existing: bool = False) -> tuple[int, int]:
    """Insert rows in ONE transaction (all or nothing). Returns (inserted, already_present).

    Only public ledger columns are written. Existing tables are never migrated;
    existing private metadata is neither read nor overwritten.

    skip_existing=False: any duplicate serial/address is an error and nothing is written.
    skip_existing=True : a serial that is already stored with the SAME address is skipped (re-import is safe);
                         the same serial with a DIFFERENT address is an error."""
    check_table(table)
    # Validate the complete batch before opening/creating any database.
    for row in rows:
        if not valid_inventory_address(row.address):
            raise DbError("invalid inventory address or public test vector; nothing was written")
    kind, target = parse_url(url)
    conn = _connect(kind, target)
    ph = "?" if kind == "sqlite" else "%s"
    ins = f"INSERT INTO {table} (serial, address, jalali_datetime, created_utc) VALUES ({ph}, {ph}, {ph}, {ph})"
    inserted = skipped = 0
    try:
        cur = conn.cursor()
        cur.execute(_ddl(kind, table))
        for r in rows:
            vals = (r.serial, r.address, r.jalali_datetime or None, _created_value(kind, r.created_utc))
            if not skip_existing:
                cur.execute(ins, vals)
                inserted += 1
                continue
            cur.execute(ins + " ON CONFLICT (serial) DO NOTHING", vals)
            if cur.rowcount == 1:
                inserted += 1
            else:
                cur.execute(f"SELECT address FROM {table} WHERE serial = {ph}", (r.serial,))
                got = cur.fetchone()
                if got is None or got[0] != r.address:
                    raise DbError("serial already exists with a DIFFERENT address; nothing was written")
                skipped += 1
        conn.commit()
    except DbError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise DbError("database save failed; transaction rolled back; details withheld") from None
    finally:
        conn.close()
    return inserted, skipped


@_safe_errors
def list_rows(url: str, table: str = DEFAULT_TABLE, limit: int = 20) -> list[tuple]:
    check_table(table)
    kind, target = parse_url(url)
    conn = _connect(kind, target)
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT serial, address, jalali_datetime, created_utc FROM {table} "
                    f"ORDER BY created_utc DESC, serial LIMIT {int(limit)}")
        return cur.fetchall()
    except Exception:
        raise DbError("database list failed; details withheld") from None
    finally:
        conn.close()


@_safe_errors
def read_ledger(path: Path) -> list[Row]:
    if not Path(path).exists():
        raise DbError("ledger file not found")
    rows: list[Row] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, d in enumerate(csv.DictReader(f), start=2):
            serial, addr = (d.get("serial") or "").strip(), (d.get("address") or "").strip()
            if not serial or not valid_inventory_address(addr):
                raise DbError(f"ledger line {n}: invalid serial/address or public test vector")
            rows.append(Row(serial, addr, (d.get("jalali_datetime") or "").strip(),
                            (d.get("created_utc") or "").strip()))
    if not rows:
        raise DbError("ledger contains no rows")
    return rows


def resolve_url(cli: str | None, config_value: str = "") -> str:
    """Priority: --db  >  environment variable BTC_DB_URL  >  db_url in config.toml"""
    return (cli or os.environ.get(ENV_VAR) or config_value or "").strip()


# --------------------------------------------------------------------------------------
class _PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unknown tokens and invalid argument values.
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid command arguments; use --help\n")


def main(argv: list[str] | None = None) -> int:
    ap = _PrivateArgumentParser(prog="btc_db.py", description="Store / inspect serial + public address records")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, helptext in (("import", "load a ledger.csv into the database (safe to repeat)"),
                           ("list", "show the newest public records"),
                           ("migrate-contact", "administrator only: add private metadata columns to an existing table")):
        p = sub.add_parser(name, help=helptext)
        if name == "import":
            p.add_argument("ledger", help="path to ledger.csv")
        elif name == "list":
            p.add_argument("--limit", type=int, default=20)
        p.add_argument("--db", help=f"connection string (or set {ENV_VAR})")
        p.add_argument("--table", default=DEFAULT_TABLE)
    a = ap.parse_args(argv)
    try:
        url = resolve_url(a.db)
        if not url:
            raise DbError(f"give --db or set the environment variable {ENV_VAR}")
        if a.cmd == "import":
            ins, skip = save_rows(url, a.table, read_ledger(Path(a.ledger)), skip_existing=True)
            print(f"{ins} saved, {skip} already present  ->  table '{a.table}' ({describe(url)})")
        elif a.cmd == "migrate-contact":
            migrate_contact_columns(url, a.table)
            print("private contact metadata schema ready (no values read or written)")
        else:
            for r in list_rows(url, a.table, a.limit):
                print("  ".join("" if v is None else str(v) for v in r))
        return 0
    except DbError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

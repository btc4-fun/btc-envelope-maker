#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
btc_db.py - tiny database layer for btc_envelope_maker.

It stores ONLY the serial number and the PUBLIC address (plus the creation time).
It never sees recovery words or private keys: the Row type below has no such field.

Connection strings
  SQLite   : sqlite:///wallets.db          (relative path)
             sqlite:////home/me/wallets.db (absolute path: four slashes)
             or just a path ending in .db / .sqlite / .sqlite3
  Postgres : postgresql://user:password@host:5432/dbname      (needs:  pip install "psycopg[binary]")

Table (created if missing):  serial TEXT PRIMARY KEY, address TEXT UNIQUE, jalali_datetime, created_utc

Stand-alone use (works on any computer, needs only the standard library, + psycopg for Postgres):
  python btc_db.py import out/batch_0587k4530/ledger.csv --db "postgresql://..."
  python btc_db.py list --db "sqlite:///wallets.db"
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
from pathlib import Path
from urllib.parse import unquote

DEFAULT_TABLE = "wallets"
ENV_VAR = "BTC_DB_URL"
TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
ADDR_RE = re.compile(r"^bc1q[02-9ac-hj-np-z]{38}$")      # Native SegWit (P2WPKH), bech32 alphabet


class DbError(Exception):
    pass


@dataclass(frozen=True)
class Row:
    """What gets stored. There is deliberately no field for secrets."""
    serial: str
    address: str
    jalali_datetime: str = ""
    created_utc: str = ""          # "YYYY-MM-DD HH:MM:SS UTC" (same text as in ledger.csv)


# --------------------------------------------------------------------------------------
def check_table(table: str) -> str:
    if not TABLE_RE.match(table or ""):
        raise DbError(f"invalid table name '{table}' (letters, digits and _ only)")
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
        return "postgres", "postgresql://" + u[m.end():]
    if "://" not in u and low.endswith((".db", ".sqlite", ".sqlite3")):
        return "sqlite", os.path.expanduser(u)
    raise DbError("unsupported connection string. Use sqlite:///file.db or postgresql://user:pass@host/db")


def mask(url: str) -> str:
    """Hide the password so it never appears on screen / in logs."""
    return re.sub(r"(://[^:/@\s]+:)[^@\s]*(@)", r"\1***\2", url or "")


def describe(url: str) -> str:
    kind, target = parse_url(url)
    return f"sqlite: {Path(target).resolve()}" if kind == "sqlite" else f"postgres: {mask(target)}"


def _connect(kind: str, target: str):
    if kind == "sqlite":
        parent = Path(target).resolve().parent
        if not parent.is_dir():
            raise DbError(f"folder does not exist: {parent}")
        try:
            return sqlite3.connect(target, timeout=10)
        except sqlite3.Error as e:
            raise DbError(f"cannot open SQLite file: {e}") from None
    try:
        import psycopg as pg                      # psycopg 3
    except ImportError:
        try:
            import psycopg2 as pg                 # psycopg 2
        except ImportError:
            raise DbError('PostgreSQL needs a driver:  pip install "psycopg[binary]"') from None
    try:
        return pg.connect(target, connect_timeout=10)
    except Exception as e:
        first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        raise DbError(f"cannot connect to PostgreSQL: {first}") from None


def _ddl(kind: str, table: str) -> str:
    ts = "TEXT" if kind == "sqlite" else "TIMESTAMPTZ"
    return (f"CREATE TABLE IF NOT EXISTS {table} (serial TEXT PRIMARY KEY, address TEXT NOT NULL UNIQUE, "
            f"jalali_datetime TEXT, created_utc {ts})")


def _created_value(kind: str, text: str):
    if not text:
        return None
    try:
        d = dt.datetime.strptime(text.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if kind == "sqlite" else d


# --------------------------------------------------------------------------------------
def check(url: str, table: str = DEFAULT_TABLE) -> None:
    """Connect and make sure the table exists (used as a pre-flight check)."""
    check_table(table)
    kind, target = parse_url(url)
    conn = _connect(kind, target)
    try:
        conn.cursor().execute(_ddl(kind, table))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise DbError(f"database error: {e}") from None
    finally:
        conn.close()


def save_rows(url: str, table: str, rows: list[Row], *, skip_existing: bool = False) -> tuple[int, int]:
    """Insert rows in ONE transaction (all or nothing). Returns (inserted, already_present).

    skip_existing=False: any duplicate serial/address is an error and nothing is written.
    skip_existing=True : a serial that is already stored with the SAME address is skipped (re-import is safe);
                         the same serial with a DIFFERENT address is an error."""
    check_table(table)
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
                    raise DbError(f"serial {r.serial} already exists in '{table}' with a DIFFERENT address - "
                                  f"stopped, nothing was written")
                skipped += 1
        conn.commit()
    except DbError:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        raise DbError(f"database error: {first}\n"
                      f"  (the table '{table}' must have the columns serial, address, jalali_datetime, created_utc; "
                      f"nothing was written)") from None
    finally:
        conn.close()
    return inserted, skipped


def list_rows(url: str, table: str = DEFAULT_TABLE, limit: int = 20) -> list[tuple]:
    check_table(table)
    kind, target = parse_url(url)
    conn = _connect(kind, target)
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT serial, address, jalali_datetime, created_utc FROM {table} "
                    f"ORDER BY created_utc DESC, serial LIMIT {int(limit)}")
        return cur.fetchall()
    except Exception as e:
        raise DbError(f"database error: {str(e).strip().splitlines()[0]}") from None
    finally:
        conn.close()


def read_ledger(path: Path) -> list[Row]:
    if not Path(path).exists():
        raise DbError(f"file not found: {path}")
    rows: list[Row] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, d in enumerate(csv.DictReader(f), start=2):
            serial, addr = (d.get("serial") or "").strip(), (d.get("address") or "").strip()
            if not serial or not ADDR_RE.match(addr):
                raise DbError(f"{path}, line {n}: bad serial/address ('{serial}', '{addr}')")
            rows.append(Row(serial, addr, (d.get("jalali_datetime") or "").strip(),
                            (d.get("created_utc") or "").strip()))
    if not rows:
        raise DbError(f"no rows in {path}")
    return rows


def resolve_url(cli: str | None, config_value: str = "") -> str:
    """Priority: --db  >  environment variable BTC_DB_URL  >  db_url in config.toml"""
    return (cli or os.environ.get(ENV_VAR) or config_value or "").strip()


# --------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Store / inspect serial + public address records")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, helptext in (("import", "load a ledger.csv into the database (safe to repeat)"),
                           ("list", "show the newest records")):
        p = sub.add_parser(name, help=helptext)
        if name == "import":
            p.add_argument("ledger", help="path to ledger.csv")
        else:
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
        else:
            for r in list_rows(url, a.table, a.limit):
                print("  ".join("" if v is None else str(v) for v in r))
        return 0
    except DbError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

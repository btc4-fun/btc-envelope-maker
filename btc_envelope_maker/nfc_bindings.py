"""Explicit owner-side migration and NFC UID binding; never replaces serials.

Run as owner/admin, never from public website startup::

    python btc_envelope_maker/nfc_bindings.py migrate --db sqlite:///wallets.db
    python btc_envelope_maker/nfc_bindings.py import captures.csv --db sqlite:///wallets.db

CSV header is exactly uid,address,captured_at (UTF-8, optional BOM); maximum
1 MiB and 5000 rows. UID is uppercase contiguous hex, 8/14/20 characters.
Addresses use the canonical inventory validator (excludes preview vectors).
captured_at must be an ISO-8601 timestamp with seconds and timezone; it is
validated, NOT persisted: this migration adds only nfc_uid, never repurposes
created_utc or private metadata. Retain the capture CSV as the owner's audit
record. A UID is cloneable identification, not authentication or a secret.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import sys

if __package__ in (None, ""):
    import btc_db
else:
    from . import btc_db

MAX_CSV_BYTES = 1024 * 1024
MAX_CSV_ROWS = 5000


def valid_uid(value: object) -> bool:
    """Canonical 4, 7 or 10 byte UID, uppercase hex; never normalize input."""
    return (isinstance(value, str) and len(value) in (8, 14, 20)
            and re.fullmatch(r"[0-9A-F]+", value) is not None)


def _read_csv(path):
    with open(path, "rb") as source:
        data = source.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise btc_db.DbError("CSV exceeds byte limit")
    with io.StringIO(data.decode("utf-8-sig"), newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != ["uid", "address", "captured_at"]:
            raise btc_db.DbError("CSV must have exactly uid,address,captured_at columns")
        rows, uids, addresses = [], set(), set()
        for row in reader:
            if len(rows) >= MAX_CSV_ROWS:
                raise btc_db.DbError("CSV exceeds row limit")
            uid, address, captured = row["uid"], row["address"], row["captured_at"]
            if (None in row or not valid_uid(uid) or not btc_db.valid_inventory_address(address)
                    or not isinstance(captured, str)
                    or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])", captured) is None):
                raise btc_db.DbError("invalid CSV UID, inventory address or capture timestamp")
            dt.datetime.fromisoformat(captured)
            if uid in uids or address in addresses:
                raise btc_db.DbError("duplicate UID or address within CSV")
            uids.add(uid)
            addresses.add(address)
            rows.append(row)
    if not rows:
        raise btc_db.DbError("CSV contains no captures")
    return rows


def _sqlite_columns(cur, table):
    cur.execute("SELECT type FROM sqlite_master WHERE name = ? COLLATE NOCASE", (table,))
    if cur.fetchone() != ("table",):
        raise btc_db.DbError("existing wallet table required")
    cur.execute(f'PRAGMA table_xinfo("{table}")')
    columns = {row[1].lower(): row for row in cur.fetchall()}
    if not {"serial", "address", "jalali_datetime", "created_utc"}.issubset(columns):
        raise btc_db.DbError("existing public ledger schema required")
    if "nfc_uid" in columns:
        c = columns["nfc_uid"]
        if (c[2].upper() != "TEXT" or c[3] or c[5] or c[6]
                or (c[4] is not None and c[4].upper() != "NULL")):
            raise btc_db.DbError("incompatible NFC UID schema")
    return columns


def _sqlite_unique(cur, table):
    cur.execute(f'PRAGMA index_list("{table}")')
    indexes = cur.fetchall()
    for index in indexes:
        if not index[2] or index[4]:
            continue
        name = index[1].replace('"', '""')
        cur.execute(f'PRAGMA index_info("{name}")')
        if [row[2] for row in cur.fetchall()] == ["nfc_uid"]:
            return True
    return False


def _postgres_target(cur, table, migration=False):
    cur.execute("SET LOCAL lock_timeout = '2s'")
    cur.execute("SET LOCAL statement_timeout = '10s'")
    cur.execute("SELECT n.nspname, c.relname FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.oid = pg_catalog.to_regclass(%s) AND c.relkind = 'r'", (table,))
    relation = cur.fetchone()
    if relation is None:
        raise btc_db.DbError("existing wallet table required")
    qualified = ".".join('"' + name.replace('"', '""') + '"' for name in relation)
    # Owner batches are rare; table locking makes validation and updates one
    # serial operation, including competitors binding the same UID/address.
    mode = "ACCESS EXCLUSIVE" if migration else "SHARE ROW EXCLUSIVE"
    cur.execute(f"LOCK TABLE ONLY {qualified} IN {mode} MODE")
    return qualified


def _postgres_columns(cur, qualified):
    cur.execute("SELECT a.attname, a.atttypid = 'pg_catalog.text'::pg_catalog.regtype, "
                "a.attnotnull, pg_catalog.pg_get_expr(d.adbin, d.adrelid), "
                "a.attidentity, a.attgenerated FROM pg_catalog.pg_attribute a "
                "LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
                "WHERE a.attrelid = pg_catalog.to_regclass(%s) "
                "AND a.attnum > 0 AND NOT a.attisdropped", (qualified,))
    columns = {row[0]: row for row in cur.fetchall()}
    if not {"serial", "address", "jalali_datetime", "created_utc"}.issubset(columns):
        raise btc_db.DbError("existing public ledger schema required")
    if "nfc_uid" in columns:
        _, text, not_null, default, identity, generated = columns["nfc_uid"]
        if not text or not_null or identity or generated or default not in (None, "NULL::text"):
            raise btc_db.DbError("incompatible NFC UID schema")
    return columns


def _postgres_unique(cur, qualified):
    cur.execute("SELECT 1 FROM pg_catalog.pg_index i "
                "JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid "
                "AND a.attnum = i.indkey[0] "
                "WHERE i.indrelid = pg_catalog.to_regclass(%s) "
                "AND a.attname = 'nfc_uid' AND i.indisunique AND i.indisvalid "
                "AND i.indisready AND i.indimmediate AND i.indnkeyatts = 1 "
                "AND i.indpred IS NULL AND i.indexprs IS NULL", (qualified,))
    return cur.fetchone() is not None


@btc_db._safe_errors
def migrate_nfc_uid(url: str, table: str = btc_db.DEFAULT_TABLE) -> None:
    """Add nullable UNIQUE nfc_uid to an existing owner-managed ledger."""
    btc_db.check_table(table)
    kind, target = btc_db.parse_url(url)
    conn = btc_db._connect(kind, target)
    try:
        cur = conn.cursor()
        if kind == "sqlite":
            cur.execute("BEGIN IMMEDIATE")
            columns = _sqlite_columns(cur, table)
            if "nfc_uid" not in columns:
                cur.execute(f'ALTER TABLE "{table}" ADD COLUMN nfc_uid TEXT DEFAULT NULL')
            cur.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS "{table}_nfc_uid_unique" ON "{table}" (nfc_uid)')
            if not _sqlite_unique(cur, table):
                raise btc_db.DbError("NFC UID unique index required")
        else:
            qualified = _postgres_target(cur, table, migration=True)
            columns = _postgres_columns(cur, qualified)
            if "nfc_uid" not in columns:
                cur.execute(f"ALTER TABLE ONLY {qualified} ADD COLUMN nfc_uid TEXT DEFAULT NULL")
            if not _postgres_unique(cur, qualified):
                cur.execute(f"ALTER TABLE ONLY {qualified} ADD UNIQUE (nfc_uid)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@btc_db._safe_errors
def import_csv(url: str, path, table: str = btc_db.DEFAULT_TABLE) -> tuple[int, int]:
    """Bind existing addresses; return (assigned, already_present). No migration."""
    btc_db.check_table(table)
    rows = _read_csv(path)
    kind, target = btc_db.parse_url(url)
    conn = btc_db._connect(kind, target)
    assigned = skipped = 0
    try:
        cur = conn.cursor()
        if kind == "sqlite":
            cur.execute("BEGIN IMMEDIATE")
            qualified, ph = f'"{table}"', "?"
            ready = "nfc_uid" in _sqlite_columns(cur, table) and _sqlite_unique(cur, table)
        else:
            qualified, ph = _postgres_target(cur, table), "%s"
            ready = "nfc_uid" in _postgres_columns(cur, qualified) and _postgres_unique(cur, qualified)
        if not ready:
            raise btc_db.DbError("explicit NFC migration required before import")
        pending = []
        for row in rows:
            cur.execute(f'SELECT nfc_uid FROM {qualified} WHERE address = {ph}', (row["address"],))
            matches = cur.fetchall()
            if len(matches) != 1:
                raise btc_db.DbError("unknown or ambiguous inventory address; nothing was written")
            existing = matches[0]
            if existing == (row["uid"],):
                skipped += 1
            else:
                if existing[0] is not None:
                    raise btc_db.DbError("address already bound to a different UID; nothing was written")
                cur.execute(f'SELECT 1 FROM {qualified} WHERE nfc_uid = {ph}', (row["uid"],))
                if cur.fetchone() is not None:
                    raise btc_db.DbError("UID already bound; nothing was written")
                pending.append(row)
        for row in pending:
            cur.execute(f'UPDATE {qualified} SET nfc_uid = {ph} WHERE address = {ph} AND nfc_uid IS NULL',
                        (row["uid"], row["address"]))
            if cur.rowcount != 1:
                raise btc_db.DbError("binding changed concurrently; nothing was written")
            assigned += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return assigned, skipped


def main(argv: list[str] | None = None) -> int:
    parser = btc_db._PrivateArgumentParser(description="Owner-only NFC UID migration/import")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("migrate", "import"):
        command = commands.add_parser(name)
        command.add_argument("--db", help="database URL, or BTC_DB_URL environment variable")
        command.add_argument("--table", default=btc_db.DEFAULT_TABLE)
        if name == "import":
            command.add_argument("csv", help="uid,address,captured_at CSV")
    args = parser.parse_args(argv)
    try:
        url = btc_db.resolve_url(args.db)
        if args.command == "migrate":
            migrate_nfc_uid(url, args.table)
            print("NFC UID schema ready (existing serials and metadata preserved)")
        else:
            assigned, skipped = import_csv(url, args.csv, args.table)
            print(f"{assigned} assigned, {skipped} already present")
        return 0
    except btc_db.DbError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

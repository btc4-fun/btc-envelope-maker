"""Durable, shared lookup admission; persisted identities are keyed digests."""
import hashlib
import hmac
import ipaddress
import math
import os
import re
import sqlite3
import time
from contextlib import closing

MAX_ENTRIES = 10000
EXPIRY_SECONDS = 60


class LookupLimitUnavailable(Exception):
    """The lookup gate cannot safely decide admission."""


class LookupLimiter:
    """One inquiry per canonical IP every fifteen seconds, across workers."""

    def __init__(self, state_file=None, secret=None, clock=time.time):
        try:
            path = os.fspath(state_file if state_file is not None else os.environ.get(
                'LOOKUP_STATE_FILE', '/var/lib/btc4fun/lookup.sqlite3'))
            key = secret if secret is not None else os.environ.get('CONTACT_SECRET')
            if isinstance(key, str):
                key = key.encode('utf-8')
            if (not isinstance(key, bytes) or len(key) < 32 or not callable(clock)
                    or not isinstance(path, str) or not path or '\0' in path
                    or path == ':memory:' or path.startswith('file:')):
                raise ValueError
            self.state_file = path
            self.secret = key
            self.clock = clock
        except Exception:
            raise LookupLimitUnavailable('Lookup temporarily unavailable') from None

    def admit(self, client_ip, serial, *, qr=False):
        if (not isinstance(client_ip, str) or not 1 <= len(client_ip) <= 45
                or '%' in client_ip or not isinstance(serial, str)
                or not 1 <= len(serial) <= 64
                or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', serial) is None
                or not isinstance(qr, bool)):
            raise ValueError('Invalid lookup arguments')
        try:
            client_ip = str(ipaddress.ip_address(client_ip))
        except ValueError:
            raise ValueError('Invalid lookup arguments') from None
        ip_hash = hmac.new(self.secret, b'lookup-ip\0' + client_ip.encode(), hashlib.sha256).hexdigest()
        serial_hash = hmac.new(self.secret, b'lookup-serial\0' + serial.encode(), hashlib.sha256).hexdigest()
        try:
            return self._admit(ip_hash, serial_hash, qr)
        except Exception:
            raise LookupLimitUnavailable('Lookup temporarily unavailable') from None

    def _admit(self, ip_hash, serial_hash, qr):
        with closing(sqlite3.connect(self.state_file, timeout=0.5, isolation_level=None)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('CREATE TABLE IF NOT EXISTS lookup_admissions ('
                           'ip_hash TEXT PRIMARY KEY, serial_hash TEXT NOT NULL, '
                           'admitted_at REAL NOT NULL) WITHOUT ROWID')
                now = self.clock()
                if (isinstance(now, bool) or not isinstance(now, (int, float))
                        or not math.isfinite(now)):
                    raise ValueError
                db.execute('DELETE FROM lookup_admissions WHERE admitted_at <= ?',
                           (now - EXPIRY_SECONDS,))
                row = db.execute('SELECT serial_hash, admitted_at FROM lookup_admissions '
                                 'WHERE ip_hash = ?', (ip_hash,)).fetchone()
                if row is not None and now < row[1] + 15:
                    result = (0 if qr and hmac.compare_digest(row[0], serial_hash)
                              else min(15, max(1, math.ceil(row[1] + 15 - now))))
                else:
                    if row is None and db.execute(
                            'SELECT count(*) FROM lookup_admissions').fetchone()[0] >= MAX_ENTRIES:
                        raise LookupLimitUnavailable('Lookup temporarily unavailable')
                    db.execute('INSERT INTO lookup_admissions VALUES (?, ?, ?) '
                               'ON CONFLICT(ip_hash) DO UPDATE SET '
                               'serial_hash=excluded.serial_hash, admitted_at=excluded.admitted_at',
                               (ip_hash, serial_hash, now))
                    result = 0
                db.commit()
                return result
            except Exception:
                db.rollback()
                raise

"""Stdlib-only, at-most-once contact notification admission.

Contract: ContactService() is lazy (no network, secret, or DB access at init).
token() returns a signed nonce valid for 900 seconds. submit(form, client_ip)
returns {'status': 'sent', 'notification_id': ...} only after a matching ntfy ack.
Keep notification_id internal; expose only ContactError.code to the browser:
  invalid       invalid fields, honeypot, or rendered UTF-8 body >4096 bytes
  csrf          missing, tampered, future, or expired CSRF token
  replayed      token already admitted; delivery may be pending/uncertain/sent
  rate_limited  >=3 client admissions or >=30 global admissions in 3600 seconds
  unavailable   configuration/storage/publish problem; delivery is NOT known to
                have failed. Never automatically retry. A fresh form is an
                explicit new attempt and can duplicate an uncertain delivery.

Deployment envfile must export CONTACT_SECRET (random, >=32 UTF-8 bytes) and
BTC_CONTACT_NTFY_TOKEN. CONTACT_STATE_FILE defaults to the persistent path below;
its parent directory must already exist and be writable only by the service.
All workers must share that file and stable secret. IP provenance, request size,
duplicate parameters, Origin checks and multipart rejection belong to the app.
CR is rejected, including CRLF; the app may normalize textarea CRLF to LF first.
Only token/IP hashes, timestamps and admission state persist, never contact data.
Expiry cleanup on admission bounds the table to 30 rows; no GET/token rows exist.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import unicodedata
import urllib.request
from collections.abc import Mapping
from contextlib import closing

# Resolve only the fixed local sibling, including in standalone file-spec loads.
_http_spec = importlib.util.spec_from_file_location('btc4fun_bounded_http', Path(__file__).resolve().with_name('bounded_http.py'))
assert _http_spec is not None and _http_spec.loader is not None
_bounded_http = importlib.util.module_from_spec(_http_spec)
_http_spec.loader.exec_module(_bounded_http)

DEFAULT_STATE_FILE = '/var/lib/btc4fun/contact.sqlite3'
NTFY_URL = 'https://ntfy.linxu.ir/'
MAX_RESPONSE_BYTES = 8192
MAX_MESSAGE_BYTES = 4096
TOKEN_TTL = 900
RATE_WINDOW = 3600
CLIENT_LIMIT = 3
GLOBAL_LIMIT = 30
DB_TIMEOUT = 5


class ContactError(Exception):
    """A fixed, safe public error code, never upstream exception text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _load_token():
    # The deployment envfile supplies this process variable. Never read request
    # values or credentials from a browser, URL, or repository configuration.
    return _valid_bearer(os.environ.get('BTC_CONTACT_NTFY_TOKEN', ''))


def _valid_bearer(token):
    if not isinstance(token, str) or not 1 <= len(token) <= 4096 or re.fullmatch(r'[A-Za-z0-9._~+/-]+=*', token) is None:
        raise ContactError('unavailable')
    return token


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ContactError('unavailable')


def _ack_id(ack):
    if not isinstance(ack, dict) or ack.get('event') != 'message' or ack.get('topic') != 'btc4fun':
        raise ContactError('unavailable')
    notification_id = ack.get('id')
    if not isinstance(notification_id, str) or not notification_id.strip():
        raise ContactError('unavailable')
    return notification_id


def _publish_json(payload, token):
    try:
        data = _bounded_http.request_bytes(
            NTFY_URL, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), method='POST',
            headers={'Authorization': 'Bearer ' + _valid_bearer(token),
                     'Content-Type': 'application/json', 'Accept': 'application/json'},
            max_bytes=MAX_RESPONSE_BYTES, timeout=4,
        )
        ack = json.loads(data)
        _ack_id(ack)
        return ack
    except Exception:
        raise ContactError('unavailable') from None


def _visible_text(value, maximum, *, multiline=False):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ContactError('invalid')
    if any(unicodedata.category(c) in {'Cc', 'Cs'} and not (multiline and c in '\n\t') for c in value):
        raise ContactError('invalid')
    if not any(unicodedata.category(c)[0] in 'LNPS' for c in value):
        raise ContactError('invalid')
    return value.strip()


def _payload(form):
    if not isinstance(form, Mapping) or set(form) - {'name', 'mobile', 'message', 'csrf_token', 'website'}:
        raise ContactError('invalid')
    if form.get('website', '') != '':
        raise ContactError('invalid')
    name = _visible_text(form.get('name'), 80)
    message = _visible_text(form.get('message'), 2000, multiline=True)
    mobile = form.get('mobile', '')
    if not isinstance(mobile, str) or len(mobile) > 32 or re.fullmatch(r'[\d+(). -]*', mobile) is None:
        raise ContactError('invalid')
    body = 'Name: ' + name + '\nMobile: ' + mobile.strip() + '\n\n' + message
    if len(body.encode('utf-8')) > MAX_MESSAGE_BYTES:
        raise ContactError('invalid')
    return {'topic': 'btc4fun', 'title': 'BTC4FUN contact', 'priority': 3,
            'markdown': False, 'message': body}


class ContactService:
    """Inject publish(payload, token), token_loader(), and clock() for offline tests."""

    def __init__(self, *, publish=_publish_json, token_loader=_load_token, clock=time.time):
        self.publish = publish
        self.token_loader = token_loader
        self.clock = clock
        self.state_file = os.environ.get('CONTACT_STATE_FILE', DEFAULT_STATE_FILE)

    def token(self):
        secret = self._secret()
        unsigned = '1.' + str(int(self.clock())) + '.' + secrets.token_hex(32)
        signature = hmac.new(secret, b'csrf\0' + unsigned.encode('ascii'), hashlib.sha256).hexdigest()
        return unsigned + '.' + signature

    @staticmethod
    def _secret():
        secret = os.environ.get('CONTACT_SECRET', '')
        try:
            encoded = secret.encode('utf-8')
        except (AttributeError, UnicodeError):
            raise ContactError('unavailable') from None
        if not secret.strip() or len(encoded) < 32:
            raise ContactError('unavailable')
        return encoded

    @staticmethod
    def _verify_token(token, secret, now):
        if not isinstance(token, str) or re.fullmatch(r'1\.[0-9]{1,12}\.[0-9a-f]{64}\.[0-9a-f]{64}', token) is None:
            raise ContactError('csrf')
        unsigned, signature = token.rsplit('.', 1)
        expected = hmac.new(secret, b'csrf\0' + unsigned.encode('ascii'), hashlib.sha256).hexdigest()
        issued = int(token.split('.')[1])
        if not hmac.compare_digest(signature, expected) or not 0 <= now - issued < TOKEN_TTL:
            raise ContactError('csrf')

    def _admit(self, token, client_ip, secret):
        if not isinstance(self.state_file, str) or not os.path.isabs(self.state_file):
            raise ContactError('unavailable')
        token_hash = hashlib.sha256(token.encode('ascii')).hexdigest()
        ip_hash = hmac.new(secret, b'ip\0' + client_ip.encode('ascii'), hashlib.sha256).hexdigest()
        try:
            with closing(sqlite3.connect(self.state_file, timeout=DB_TIMEOUT)) as connection:
                with connection:
                    connection.execute('BEGIN IMMEDIATE')
                    # Check again AFTER any lock wait, not with a stale admission clock.
                    now = self.clock()
                    self._verify_token(token, secret, now)
                    connection.execute('CREATE TABLE IF NOT EXISTS admissions (token_hash TEXT PRIMARY KEY, ip_hash TEXT NOT NULL, admitted_at REAL NOT NULL, expires_at REAL NOT NULL, state TEXT NOT NULL)')
                    connection.execute('CREATE INDEX IF NOT EXISTS admissions_expiry ON admissions(expires_at)')
                    connection.execute('DELETE FROM admissions WHERE expires_at <= ?', (now,))
                    if connection.execute('SELECT 1 FROM admissions WHERE token_hash = ?', (token_hash,)).fetchone():
                        raise ContactError('replayed')
                    count, client_count = connection.execute(
                        'SELECT COUNT(*), COALESCE(SUM(ip_hash = ?), 0) FROM admissions', (ip_hash,),
                    ).fetchone()
                    if count >= GLOBAL_LIMIT or client_count >= CLIENT_LIMIT:
                        raise ContactError('rate_limited')
                    connection.execute('INSERT INTO admissions VALUES (?, ?, ?, ?, ?)', (
                        token_hash, ip_hash, now, now + RATE_WINDOW, 'admitted',
                    ))
                # Leaving the transaction above commits before returning to the sender.
        except sqlite3.Error:
            raise ContactError('unavailable') from None
        return token_hash

    def _finish(self, token_hash, state):
        # Admission already protects against duplicates. A failed status update must
        # never delete it, retry publication, or turn a verified ack into failure.
        try:
            with closing(sqlite3.connect(self.state_file, timeout=DB_TIMEOUT)) as connection:
                with connection:
                    connection.execute('UPDATE admissions SET state = ? WHERE token_hash = ?', (state, token_hash))
        except sqlite3.Error:
            pass

    def submit(self, form, client_ip):
        secret = self._secret()
        payload = _payload(form)
        self._verify_token(form.get('csrf_token'), secret, self.clock())
        try:
            if not isinstance(client_ip, str) or len(client_ip) > 45 or '%' in client_ip:
                raise ValueError
            address = ipaddress.ip_address(client_ip)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            client_ip = str(address)
        except ValueError:
            raise ContactError('invalid') from None
        try:
            token = _valid_bearer(self.token_loader())
        except Exception:
            raise ContactError('unavailable') from None
        token_hash = self._admit(form['csrf_token'], client_ip, secret)
        try:
            ack = self.publish(payload, token)
            notification_id = _ack_id(ack)
        except Exception:
            self._finish(token_hash, 'uncertain')
            raise ContactError('unavailable') from None
        self._finish(token_hash, 'sent')
        return {'status': 'sent', 'notification_id': notification_id}

"""Offline contact proofs: synthetic credentials, scratch-only real SQLite."""
from __future__ import annotations

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

PATH = Path(__file__).resolve().parents[1] / 'contact.py'
SECRET = 'synthetic-contact-secret-for-offline-tests-only'
BEARER = 'tk_synthetic_offline_contact_only'


def load_module():
    if not PATH.is_file():
        raise AssertionError('server-side contact module missing')
    spec = importlib.util.spec_from_file_location('btc4fun_contact', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContactContract(unittest.TestCase):
    def setUp(self):
        scratch = os.environ.get('TMPDIR')
        self.directory = tempfile.TemporaryDirectory(prefix='contact-tests-', dir=scratch)
        self.addCleanup(self.directory.cleanup)
        self.db = Path(self.directory.name) / 'contact.sqlite3'
        self.environment = patch.dict(os.environ, {
            'CONTACT_SECRET': SECRET,
            'BTC_CONTACT_NTFY_TOKEN': BEARER,
            'CONTACT_STATE_FILE': str(self.db),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.now = [1_000_000.0]
        self.calls = []

    def publisher(self, payload, token):
        self.calls.append((payload, token))
        return {'event': 'message', 'topic': 'btc4fun', 'id': 'synthetic-notification-id'}

    def service(self, **kwargs):
        self.module = load_module()
        return self.module.ContactService(
            publish=kwargs.pop('publish', self.publisher),
            clock=lambda: self.now[0], **kwargs,
        )

    def form(self, service, **overrides):
        form = dict(name='Synthetic Sender', mobile='+98 (912) 000-0000',
                    message='Synthetic offline message.', csrf_token=service.token(), website='')
        form.update(overrides)
        return form

    def error_code(self, callback, expected):
        with self.assertRaises(self.module.ContactError) as caught:
            callback()
        self.assertEqual(caught.exception.code, expected)
        self.assertEqual(str(caught.exception), expected)
        self.assertNotIn(SECRET, repr(caught.exception))
        self.assertNotIn(BEARER, repr(caught.exception))
        return caught.exception

    def test_signed_token_tamper_expiry_future_and_foreign_secret_are_rejected(self):
        service = self.service()
        token = service.token()
        self.assertNotEqual(token, service.token())
        form = self.form(service)
        for invalid in ['', None, [], 'x' * 1000, token[:-1] + ('0' if token[-1] != '0' else '1')]:
            with self.subTest(value=repr(invalid)[:30]):
                self.error_code(lambda: service.submit(dict(form, csrf_token=invalid), '192.0.2.10'), 'csrf')
        self.now[0] += 900
        self.error_code(lambda: service.submit(dict(form, csrf_token=token), '192.0.2.10'), 'csrf')
        self.now[0] -= 901
        self.error_code(lambda: service.submit(dict(form, csrf_token=token), '192.0.2.10'), 'csrf')
        self.now[0] += 1
        with patch.dict(os.environ, {'CONTACT_SECRET': 'different-synthetic-secret-of-sufficient-length'}):
            self.error_code(lambda: service.submit(dict(form, csrf_token=token), '192.0.2.10'), 'csrf')
        self.assertEqual(self.calls, [])
        self.now[0] += 899
        self.assertEqual(service.submit(dict(form, csrf_token=token), '192.0.2.10')['status'], 'sent')

    def test_missing_or_empty_secret_never_uses_a_fallback(self):
        service = self.service()
        for value in [None, '', '   ']:
            with self.subTest(value=value):
                with patch.dict(os.environ):
                    if value is None:
                        os.environ.pop('CONTACT_SECRET', None)
                    else:
                        os.environ['CONTACT_SECRET'] = value
                    self.error_code(service.token, 'unavailable')
                    self.error_code(lambda: service.submit({}, '192.0.2.10'), 'unavailable')
        self.assertEqual(self.calls, [])

    def test_success_returns_internal_ack_without_credentials_or_content(self):
        service = self.service()
        form = self.form(service)
        outcome = service.submit(form, '192.0.2.10')
        self.assertEqual(outcome, {'status': 'sent', 'notification_id': 'synthetic-notification-id'})
        self.assertEqual(len(self.calls), 1)
        payload, token = self.calls[0]
        self.assertEqual(token, BEARER)
        self.assertEqual(payload['topic'], 'btc4fun')
        self.assertEqual(payload['title'], 'BTC4FUN contact')
        self.assertEqual(payload['priority'], 3)
        self.assertIs(payload['markdown'], False)
        for field in ['name', 'mobile', 'message']:
            self.assertIn(form[field], payload['message'])
        self.assertNotIn(BEARER, repr(outcome))
        self.assertNotIn(form['name'], repr(outcome))
        self.assertTrue(self.db.is_file())

    def test_invalid_fields_and_honeypot_never_publish_or_consume_admission(self):
        service = self.service()
        form = self.form(service)
        invalid = [
            {'name': ''}, {'name': ' '}, {'name': 'n' * 81}, {'name': 'a\nb'},
            {'name': 'a\tb'}, {'name': '\u200b\u200c'}, {'name': ['bad']},
            {'mobile': '1' * 33}, {'mobile': 'https://other.invalid'}, {'mobile': '+98\r0'},
            {'mobile': None}, {'message': ''}, {'message': ' \t\n'},
            {'message': 'm' * 2001}, {'message': '\u200b\u200c\ufeff'},
            {'message': '\u0301'}, {'message': ['bad']}, {'message': '\ud800'},
            {'website': 'https://bot.invalid'}, {'website': ' '}, {'website': []},
            {'endpoint': 'https://attacker.invalid/'},
        ]
        invalid += [{'message': 'visible' + chr(i)} for i in range(32) if i not in (9, 10)]
        invalid += [{'message': 'visible' + chr(i)} for i in (127, 128, 159)]
        for override in invalid:
            with self.subTest(fields=repr(override)):
                self.error_code(lambda: service.submit(dict(form, **override), '192.0.2.10'), 'invalid')
        for missing in ['name', 'message']:
            bad = dict(form)
            bad.pop(missing)
            self.error_code(lambda: service.submit(bad, '192.0.2.10'), 'invalid')
        self.error_code(lambda: service.submit([], '192.0.2.10'), 'invalid')
        self.assertEqual(self.calls, [])
        self.assertEqual(service.submit(form, '192.0.2.10')['status'], 'sent')

    def test_valid_boundaries_unicode_and_optional_mobile(self):
        service = self.service()
        for index, fields in enumerate([
            {'name': 'n' * 80, 'mobile': '0' * 32, 'message': 'm' * 2000},
            {'name': 'مریم', 'mobile': '', 'message': 'سلام\nپیام\tآزمایشی\u200cاست'},
            {'name': 'n', 'mobile': '+۹۸ (۹۱۲) ۰۰۰-۰۰۰۰', 'message': 'm'},
        ]):
            with self.subTest(fields=index):
                self.assertEqual(service.submit(self.form(service, **fields), f'192.0.2.{index}')['status'], 'sent')

    def test_final_rendered_message_is_bounded_to_4096_utf8_bytes(self):
        service = self.service()
        form = self.form(service, name='n', mobile='', message='ع' * 2000)
        service.submit(form, '192.0.2.10')
        overhead = len(self.calls[-1][0]['message'].encode('utf-8')) - 4000
        form = self.form(service, name='ن' * 80, mobile='0' * 32, message='ع' * 2000)
        self.error_code(lambda: service.submit(form, '192.0.2.10'), 'invalid')
        # Exactly 4096 bytes using four-byte characters plus single-byte padding.
        available = 4096 - overhead
        message = '😀' * (available // 4) + 'a' * (available % 4)
        service.submit(self.form(service, name='n', mobile='', message=message), '192.0.2.11')
        self.assertEqual(len(self.calls[-1][0]['message'].encode('utf-8')), 4096)
        self.error_code(lambda: service.submit(self.form(service, name='n', mobile='', message=message + 'a'), '192.0.2.11'), 'invalid')

    def rows(self):
        with closing(sqlite3.connect(self.db)) as connection:
            return connection.execute('SELECT token_hash, ip_hash, admitted_at, expires_at, state FROM admissions').fetchall()

    def test_persistent_replay_and_ip_rate_limit_survive_service_recreation(self):
        service = self.service()
        first = self.form(service)
        service.submit(first, '192.0.2.10')
        # Retain the same module: public exception identity is intentionally stable.
        second = self.module.ContactService(publish=self.publisher, clock=lambda: self.now[0])
        self.error_code(lambda: second.submit(first, '192.0.2.11'), 'replayed')
        for _ in range(2):
            second.submit(self.form(second), '192.0.2.10')
        self.error_code(lambda: second.submit(self.form(second), '192.0.2.10'), 'rate_limited')
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(self.rows()), 3)

    def test_sliding_window_cleanup_does_not_reenable_expired_token(self):
        service = self.service()
        first = self.form(service)
        for offset in [0, 100, 200]:
            self.now[0] = 1_000_000 + offset
            service.submit(first if offset == 0 else self.form(service), '192.0.2.10')
        self.now[0] = 1_003_599
        self.error_code(lambda: service.submit(self.form(service), '192.0.2.10'), 'rate_limited')
        self.now[0] += 1
        service.submit(self.form(service), '192.0.2.10')
        self.assertEqual(len(self.rows()), 3)
        self.error_code(lambda: service.submit(self.form(service), '192.0.2.10'), 'rate_limited')
        self.now[0] = 1_007_200
        service.submit(self.form(service), '192.0.2.11')
        self.assertEqual(len(self.rows()), 1)
        self.error_code(lambda: service.submit(first, '192.0.2.10'), 'csrf')

    def test_global_30_hour_limit_and_privacy_only_schema(self):
        service = self.service()
        first = self.form(service)
        for index in range(30):
            service.submit(first if index == 0 else self.form(service), f'192.0.2.{index}')
        self.error_code(lambda: service.submit(self.form(service), '198.51.100.1'), 'rate_limited')
        self.assertEqual(len(self.calls), 30)
        rows = self.rows()
        self.assertEqual(len(rows), 30)
        self.assertEqual(rows[0][0], hashlib.sha256(first['csrf_token'].encode()).hexdigest())
        self.assertEqual(rows[0][1], hmac.new(SECRET.encode(), b'ip\0' + b'192.0.2.0', hashlib.sha256).hexdigest())
        for row in rows:
            self.assertEqual(len(row[0]), 64)
            self.assertEqual(len(row[1]), 64)
            self.assertEqual(row[4], 'sent')
        with closing(sqlite3.connect(self.db)) as connection:
            columns = [r[1] for r in connection.execute('PRAGMA table_info(admissions)')]
            self.assertEqual(columns, ['token_hash', 'ip_hash', 'admitted_at', 'expires_at', 'state'])
            dump = '\n'.join(connection.iterdump())
        for value in [SECRET, BEARER, first['csrf_token'], first['message'], first['name'], first['mobile'], '192.0.2.0']:
            self.assertNotIn(value, dump)

    def test_same_token_concurrent_workers_publish_only_once_after_durable_admission(self):
        entered = threading.Event()
        release = threading.Event()
        def paused(payload, token):
            # A separate real connection sees committed admission BEFORE publish.
            rows = self.rows()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][4], 'admitted')
            entered.set()
            self.assertTrue(release.wait(5))
            return self.publisher(payload, token)
        service = self.service(publish=paused)
        second = self.module.ContactService(publish=self.publisher, clock=lambda: self.now[0])
        form = self.form(service)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(service.submit, form, '192.0.2.10')
            try:
                self.assertTrue(entered.wait(5))
                self.error_code(lambda: second.submit(form, '192.0.2.10'), 'replayed')
            finally:
                release.set()
            self.assertEqual(future.result(timeout=5)['status'], 'sent')
        self.assertEqual(len(self.calls), 1)

    def test_concurrent_distinct_admissions_enforce_ip_and_global_caps(self):
        service = self.service()
        for global_case, count, expected in [(False, 12, 3), (True, 40, 30)]:
            if global_case:
                self.now[0] += 3600
            barrier = threading.Barrier(count)
            forms = [self.form(service) for _ in range(count)]
            def attempt(index):
                worker = self.module.ContactService(publish=self.publisher, clock=lambda: self.now[0])
                barrier.wait(timeout=10)
                try:
                    worker.submit(forms[index], f'198.51.100.{index}' if global_case else '192.0.2.10')
                    return 'sent'
                except self.module.ContactError as error:
                    return error.code
            with ThreadPoolExecutor(max_workers=count) as pool:
                statuses = list(pool.map(attempt, range(count)))
            self.assertEqual(statuses.count('sent'), expected)
            self.assertEqual(statuses.count('rate_limited'), count - expected)
            self.assertEqual(len(self.rows()), expected)

    def test_ipv6_aliases_share_client_budget_and_invalid_ip_is_sanitized(self):
        service = self.service()
        for ip in ['2001:db8::1', '2001:0db8:0:0:0:0:0:1', '2001:DB8::1']:
            service.submit(self.form(service), ip)
        self.error_code(lambda: service.submit(self.form(service), '2001:db8::1'), 'rate_limited')
        for ip in ['', None, 'SYNTHETIC_PRIVATE_INPUT\n']:
            self.error_code(lambda: service.submit(self.form(service), ip), 'invalid')

    def test_ambiguous_publish_failure_is_unavailable_and_never_automatically_retried(self):
        attempts = []
        def failing(payload, token):
            attempts.append(1)
            raise RuntimeError('SYNTHETIC_PRIVATE_CONTENT ' + BEARER)
        service = self.service(publish=failing)
        form = self.form(service)
        self.error_code(lambda: service.submit(form, '192.0.2.10'), 'unavailable')
        self.assertEqual(self.rows()[0][4], 'uncertain')
        self.error_code(lambda: service.submit(form, '192.0.2.10'), 'replayed')
        self.assertEqual(len(attempts), 1)
        self.error_code(lambda: service.submit(self.form(service), '192.0.2.10'), 'unavailable')
        self.assertEqual(len(attempts), 2, 'fresh form explicitly retries once, not automatically')

    def test_bad_ack_is_never_success_or_retryable_with_the_same_token(self):
        bad_acks = [None, [], {}, {'event': 'open', 'topic': 'btc4fun', 'id': 'i'},
                    {'event': 'message', 'topic': 'other', 'id': 'i'},
                    {'event': 'message', 'topic': 'btc4fun', 'id': ''},
                    {'event': 'message', 'topic': 'btc4fun', 'id': 123},
                    {'event': 'message', 'topic': 'btc4fun', 'id': ' \n'}]
        service = self.service()
        for index, ack in enumerate(bad_acks):
            service.publish = lambda payload, token: ack
            form = self.form(service)
            self.error_code(lambda: service.submit(form, f'192.0.2.{index}'), 'unavailable')
            self.error_code(lambda: service.submit(form, f'192.0.2.{index}'), 'replayed')
        self.assertEqual({r[4] for r in self.rows()}, {'uncertain'})

    def test_database_failure_is_sanitized_and_does_not_publish(self):
        service = self.service()
        service.state_file = str(Path(self.directory.name) / 'missing-parent' / 'state.sqlite3')
        self.error_code(lambda: service.submit(self.form(service), '192.0.2.10'), 'unavailable')
        self.assertEqual(self.calls, [])

    def test_ephemeral_database_paths_are_refused(self):
        service = self.service()
        for path in ['', ':memory:', 'file:state?mode=memory&cache=shared']:
            service.state_file = path
            with patch.object(self.module.sqlite3, 'connect', side_effect=AssertionError('ephemeral database must be refused before opening')):
                self.error_code(lambda: service.submit(self.form(service), '192.0.2.10'), 'unavailable')
        self.assertEqual(self.calls, [])

    def test_secret_requires_at_least_32_bytes_and_rejects_surrogates(self):
        service = self.service()
        for secret in ['weak', 'x' * 31, '\ud800' * 32]:
            with patch.object(self.module.os, 'environ', {'CONTACT_SECRET': secret}):
                self.error_code(service.token, 'unavailable')

    def test_token_expiry_is_rechecked_after_real_sqlite_writer_lock_wait(self):
        service = self.service()
        form = self.form(service)
        # Bootstrap schema using a different token before blocking this admission.
        service.submit(self.form(service), '192.0.2.11')
        begin_started = threading.Event()
        real_connect = self.module.sqlite3.connect
        def observed_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connection.set_trace_callback(lambda sql: begin_started.set() if sql == 'BEGIN IMMEDIATE' else None)
            return connection
        with closing(real_connect(self.db)) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            with ThreadPoolExecutor(max_workers=1) as pool:
                with patch.object(self.module.sqlite3, 'connect', side_effect=observed_connect):
                    future = pool.submit(service.submit, form, '192.0.2.10')
                    self.assertTrue(begin_started.wait(5))
                    self.now[0] += 900
                    blocker.rollback()
                    self.error_code(lambda: future.result(timeout=5), 'csrf')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.rows()), 1)

    def test_state_update_failure_keeps_admission_and_does_not_retry_or_override_ack(self):
        service = self.service()
        first = self.form(service)
        real_connect = self.module.sqlite3.connect
        def publisher_with_failed_update(payload, token):
            # The production admission connection is already closed here.
            self.module.sqlite3.connect = Mock(side_effect=sqlite3.OperationalError('SYNTHETIC_PRIVATE_DB_ERROR'))
            return self.publisher(payload, token)
        service.publish = publisher_with_failed_update
        try:
            self.assertEqual(service.submit(first, '192.0.2.10')['status'], 'sent')
        finally:
            self.module.sqlite3.connect = real_connect
        self.assertEqual(self.rows()[0][4], 'admitted')
        self.error_code(lambda: service.submit(first, '192.0.2.10'), 'replayed')
        self.assertEqual(len(self.calls), 1)


    def test_token_loader_uses_only_server_environment_and_refuses_header_injection(self):
        service = self.service()
        form = self.form(service)
        for value in [None, '', ' ', 'token\r\nHeader: injected', 'nonascii-ع', 'x' * 4097]:
            with self.subTest(value=repr(value)[:40]), patch.dict(os.environ):
                if value is None:
                    os.environ.pop('BTC_CONTACT_NTFY_TOKEN', None)
                else:
                    os.environ['BTC_CONTACT_NTFY_TOKEN'] = value
                self.error_code(lambda: service.submit(form, '192.0.2.10'), 'unavailable')
        self.assertFalse(self.db.exists(), 'missing credentials must not consume tokens')
        self.assertEqual(self.calls, [])
        service.submit(form, '192.0.2.10')

    def test_transport_uses_fixed_root_post_bearer_json_and_four_second_timeout(self):
        service = self.service()
        ack = {'event': 'message', 'topic': 'btc4fun', 'id': 'network-synthetic-id'}
        with patch.object(self.module._bounded_http, 'request_bytes', return_value=json.dumps(ack).encode()) as request:
            result = self.module._publish_json(self.calls_payload(service), BEARER)
        self.assertEqual(result, ack)
        self.assertEqual(request.call_args.args, ('https://ntfy.linxu.ir/',))
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs['method'], 'POST')
        self.assertEqual(kwargs['headers'], {'Authorization': 'Bearer ' + BEARER,
                                          'Content-Type': 'application/json', 'Accept': 'application/json'})
        payload = json.loads(kwargs['data'])
        self.assertEqual(set(payload), {'topic', 'title', 'priority', 'markdown', 'message'})
        self.assertEqual(payload['topic'], 'btc4fun')
        self.assertEqual(payload['title'], 'BTC4FUN contact')
        self.assertEqual(payload['priority'], 3)
        self.assertIs(payload['markdown'], False)
        self.assertEqual(kwargs['timeout'], 4)
        self.assertEqual(kwargs['max_bytes'], 8192)

    def calls_payload(self, service):
        service.submit(self.form(service), '192.0.2.10')
        return self.calls[-1][0]

    def test_transport_rejects_invalid_json_ack_and_sanitizes_worker_errors(self):
        service = self.service()
        payload = self.calls_payload(service)
        valid = json.dumps({'event': 'message', 'topic': 'btc4fun', 'id': 'i'}).encode()
        cases = [b'not-json', b'\xff', b'[]', b'{}',
                 json.dumps({'event': 'message', 'topic': 'other', 'id': 'i'}).encode()]
        for body in cases:
            with patch.object(self.module._bounded_http, 'request_bytes', return_value=body):
                self.error_code(lambda: self.module._publish_json(payload, BEARER), 'unavailable')
        with patch.object(self.module._bounded_http, 'request_bytes', return_value=valid + b' ' * (8192 - len(valid))):
            self.assertEqual(self.module._publish_json(payload, BEARER)['id'], 'i')
        with patch.object(self.module._bounded_http, 'request_bytes', side_effect=TimeoutError('SYNTHETIC_PRIVATE_NETWORK_ERROR ' + BEARER)):
            self.error_code(lambda: self.module._publish_json(payload, BEARER), 'unavailable')
        for status in [301, 302, 303, 307, 308]:
            self.error_code(lambda: self.module.NoRedirect().redirect_request(None, None, status, 'moved', {}, 'https://elsewhere.invalid/'), 'unavailable')


if __name__ == '__main__':
    unittest.main()

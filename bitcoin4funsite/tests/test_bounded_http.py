"""Isolated loopback-only transport proofs; never use upstream services."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name):
    spec = importlib.util.spec_from_file_location('proof_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def loopback_server(*, trickle=True, body=None, status=200, chunked=False, header_trickle=False):
    stop = threading.Event()
    disconnected = threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.do_GET()

        def do_GET(self):
            requests.append(self.path)
            response_body = body if body is not None else b'{"event":"message","topic":"btc4fun","id":"fixture"}'
            try:
                if header_trickle:
                    header = b'HTTP/1.1 200 OK\r\nX-Fixture: ' + b'x' * 55 + b'\r\n\r\n'
                    for byte in header:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if stop.wait(0.11):
                            return
                    return
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                if 300 <= status < 400:
                    self.send_header('Location', '/redirect-target')
                if chunked:
                    self.send_header('Transfer-Encoding', 'chunked')
                else:
                    self.send_header('Content-Length', str(len(response_body)))
                self.end_headers()
                if trickle:
                    # Every byte arrives well inside the old 4-second idle limit.
                    for byte in response_body:
                        part = bytes([byte])
                        self.wfile.write(b'1\r\n' + part + b'\r\n' if chunked else part)
                        self.wfile.flush()
                        if stop.wait(0.11):
                            return
                    if chunked:
                        self.wfile.write(b'0\r\n\r\n')
                        self.wfile.flush()
                else:
                    self.wfile.write(response_body)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = False
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02})
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/', requests, disconnected
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if thread.is_alive():
            raise AssertionError('loopback fixture leaked its serving thread')


class WholeOperationDeadline(unittest.TestCase):
    @contextmanager
    def observe_worker(self, http):
        real_popen = http.subprocess.Popen
        workers = []
        def start(*args, **kwargs):
            worker = real_popen(*args, **kwargs)
            workers.append(worker)
            self.assertEqual(kwargs['env'], {})
            self.assertFalse(kwargs['shell'])
            self.assertEqual(args[0], [http.sys.executable, '-I', '-B', http.WORKER_PATH, '--worker'])
            self.assertTrue(Path(http.WORKER_PATH).is_absolute())
            return worker
        with patch.object(http.subprocess, 'Popen', side_effect=start):
            yield workers
        self.assertEqual(len(workers), 1)
        worker = workers[0]
        self.assertIsNotNone(worker.returncode, 'worker must be reaped before return')
        with self.assertRaises(ChildProcessError):
            os.waitpid(worker.pid, os.WNOHANG)

    def test_contact_continuously_trickling_ack_has_whole_operation_deadline(self):
        contact = load_module('contact')
        threads = {thread.ident for thread in threading.enumerate()}
        with tempfile.TemporaryDirectory(prefix='contact-deadline-', dir=os.environ.get('TMPDIR')) as directory, patch.dict(os.environ, {
            'CONTACT_SECRET': 'SYNTHETIC_LOOPBACK_SECRET_' * 2,
            'CONTACT_STATE_FILE': str(Path(directory) / 'state.sqlite3'),
        }), loopback_server() as (url, requests, disconnected):
            service = contact.ContactService(token_loader=lambda: 'SYNTHETIC_LOOPBACK_ONLY')
            form = {'name': 'Fixture', 'message': 'Harmless isolated fixture', 'csrf_token': service.token()}
            with patch.object(contact, 'NTFY_URL', url):
                started = time.monotonic()
                with self.observe_worker(contact._bounded_http), self.assertRaises(contact.ContactError) as caught:
                    service.submit(form, '192.0.2.10')
                elapsed = time.monotonic() - started
            self.assertEqual(caught.exception.code, 'unavailable')
            self.assertLess(elapsed, 4.6, 'contact ack has the same 4-second whole-operation limit')
            self.assertGreater(elapsed, 3.5)
            self.assertTrue(disconnected.wait(1))
            with self.assertRaises(contact.ContactError) as replayed:
                service.submit(form, '192.0.2.10')
            self.assertEqual(replayed.exception.code, 'replayed')
            connection = sqlite3.connect(Path(directory) / 'state.sqlite3')
            try:
                self.assertEqual(connection.execute('SELECT state FROM admissions').fetchall(), [('uncertain',)])
            finally:
                connection.close()
            self.assertEqual(requests, ['/'], 'uncertain publication must not retry')
        self.assertEqual({thread.ident for thread in threading.enumerate()}, threads)

    def test_market_continuously_trickling_response_has_whole_operation_deadline(self):
        market = load_module('market')
        threads = {thread.ident for thread in threading.enumerate()}
        with loopback_server() as (url, requests, disconnected):
            with patch.object(market, 'PRICE_URL', url):
                started = time.monotonic()
                with self.observe_worker(market._bounded_http), self.assertRaises(market.MarketUnavailable):
                    market._fetch_json(url, 'SYNTHETIC_LOOPBACK_ONLY')
                elapsed = time.monotonic() - started
            self.assertLess(elapsed, 4.6, '4 seconds total, not 4 seconds per socket read')
            self.assertGreater(elapsed, 3.5)
            self.assertTrue(disconnected.wait(1), 'deadline must close the worker socket')
            self.assertEqual(requests, ['/'])
        self.assertEqual({thread.ident for thread in threading.enumerate()}, threads)

    def test_chunked_body_and_trickling_headers_share_the_deadline(self):
        http = load_module('bounded_http')
        for mode in [{'chunked': True}, {'header_trickle': True}]:
            with self.subTest(mode=mode), loopback_server(**mode) as (url, requests, disconnected):
                started = time.monotonic()
                with self.observe_worker(http), self.assertRaises(http.BoundedHTTPError):
                    http.request_bytes(url)
                self.assertLess(time.monotonic() - started, 4.6)
                self.assertTrue(disconnected.wait(1))
                self.assertEqual(requests, ['/'])

    def test_exact_response_caps_succeed_and_one_extra_byte_fails(self):
        http = load_module('bounded_http')
        for cap in [8192, 262144]:
            for extra in [0, 1]:
                with self.subTest(cap=cap, extra=extra), loopback_server(trickle=False, body=b'x' * (cap + extra)) as (url, requests, _):
                    with self.observe_worker(http):
                        if extra:
                            with self.assertRaises(http.BoundedHTTPError):
                                http.request_bytes(url, max_bytes=cap)
                        else:
                            self.assertEqual(http.request_bytes(url, max_bytes=cap), b'x' * cap)
                    self.assertEqual(requests, ['/'])

    def test_redirects_and_error_status_are_refused_without_a_second_request(self):
        http = load_module('bounded_http')
        for status in [301, 302, 303, 307, 308, 500]:
            with self.subTest(status=status), loopback_server(trickle=False, status=status) as (url, requests, _):
                with self.observe_worker(http), self.assertRaises(http.BoundedHTTPError) as caught:
                    http.request_bytes(url, headers={'Authorization': 'Bearer SYNTHETIC_LOOPBACK_ONLY'})
                self.assertEqual(str(caught.exception), 'HTTP request unavailable')
                self.assertEqual(requests, ['/'])


if __name__ == '__main__':
    unittest.main()

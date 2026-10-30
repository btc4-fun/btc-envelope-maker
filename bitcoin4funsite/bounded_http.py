"""Stdlib HTTP with a killable whole-operation deadline, not an idle timeout.

Only a fixed local worker is executed, with an empty environment and no shell.
Request metadata (including credentials/content) travels through stdin only.
The worker writes at most max_bytes to stdout; errors have no stderr or body.
A timeout kills and reaps the worker: no background reader threads or retries.
Callers retain destination allowlists, JSON parsing and domain validation.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

MAX_BYTES = 262144
MAX_REQUEST_BYTES = 65536
WORKER_PATH = str(Path(__file__).resolve())


class BoundedHTTPError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BoundedHTTPError('HTTP request unavailable')


def request_bytes(url, *, headers=None, data=None, method='GET', max_bytes=MAX_BYTES, timeout=4):
    """Return a bounded successful body; never expose worker error details."""
    deadline = time.monotonic() + timeout
    try:
        if not 0 < max_bytes <= MAX_BYTES or not 0 < timeout <= 4:
            raise ValueError
        descriptor = json.dumps({
            'url': url, 'headers': headers or {}, 'method': method,
            'data': None if data is None else base64.b64encode(data).decode('ascii'),
            'max_bytes': max_bytes, 'timeout': timeout,
        }).encode('utf-8')
        if len(descriptor) > MAX_REQUEST_BYTES:
            raise ValueError
        with subprocess.Popen(
            [sys.executable, '-I', '-B', WORKER_PATH, '--worker'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={}, shell=False, close_fds=True,
        ) as worker:
            try:
                body, _ = worker.communicate(descriptor, timeout=max(0, deadline - time.monotonic()))
            except BaseException:
                worker.kill()
                worker.communicate()
                raise
            if worker.returncode != 0 or len(body) > max_bytes or time.monotonic() > deadline:
                raise ValueError
        return body
    except Exception:
        raise BoundedHTTPError('HTTP request unavailable') from None


def _read_response(descriptor):
    maximum = descriptor['max_bytes']
    if not isinstance(maximum, int) or not 0 < maximum <= MAX_BYTES:
        raise ValueError
    data = descriptor['data']
    request = urllib.request.Request(
        descriptor['url'], headers=descriptor['headers'], method=descriptor['method'],
        data=None if data is None else base64.b64decode(data, validate=True),
    )
    # Default HTTPSHandler retains certificate/hostname verification. Redirects
    # are refused even for same-origin destinations, before forwarding headers.
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=descriptor['timeout']) as response:
        if not 200 <= response.status < 300:
            raise ValueError
        body = response.read(maximum + 1)
        if len(body) > maximum:
            raise ValueError
        return body


def _worker():
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            return 1
        body = _read_response(json.loads(raw))
        sys.stdout.buffer.write(body)
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(_worker() if sys.argv[1:] == ['--worker'] else 1)

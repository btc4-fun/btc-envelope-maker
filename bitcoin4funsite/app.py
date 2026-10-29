from __future__ import annotations

import os
import io
import re
from pathlib import Path

from bech32 import decode as decode_segwit
from flask import Flask, Response, abort, jsonify, render_template, request
import psycopg
import qrcode
import qrcode.image.svg

SERIAL_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')


def database_lookup(serial):
    password_file = os.environ.get('BTC_DB_PASSWORD_FILE', '/run/secrets/db_password')
    password = Path(password_file).read_text().rstrip('\r\n')
    with psycopg.connect(
        host=os.environ.get('BTC_DB_HOST', 'nextcloud-aio-database'),
        port=int(os.environ.get('BTC_DB_PORT', '5432')),
        dbname=os.environ.get('BTC_DB_NAME', 'd_bitcoin4fun'),
        user=os.environ['BTC_DB_USER'],
        password=password,
        connect_timeout=4,
        application_name='bitcoin4fun-readonly',
        options='-c default_transaction_read_only=on -c statement_timeout=3000 -c lock_timeout=1000',
    ) as connection:
        connection.read_only = True
        with connection.cursor() as cursor:
            cursor.execute('SELECT serial, address FROM public.wallets WHERE serial = %s LIMIT 1', (serial,))
            row = cursor.fetchone()
    return {'serial': row[0], 'address': row[1]} if row else None


def create_app(config=None):
    app = Flask(__name__, root_path=str(Path(__file__).resolve().parent))
    if config:
        app.config.update(config)

    @app.before_request
    def validate_api_serial():
        if request.path.startswith('/api/wallets/'):
            serial = request.path.removeprefix('/api/wallets/').removesuffix('/qr.svg')
            if SERIAL_RE.fullmatch(serial) is None:
                return jsonify(error='invalid_serial'), 400

    @app.after_request
    def security_headers(response):
        response.headers['Content-Security-Policy'] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
            "img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; object-src 'none'"
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), payment=()'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        if request.path.startswith('/api/') or request.endpoint in {'lookup_page', 'serial_page'}:
            response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/guide')
    def guide():
        return render_template('guide.html')

    @app.get('/kids')
    def kids():
        return render_template('kids.html')

    @app.get('/terms')
    def terms():
        return render_template('terms.html')

    @app.get('/lookup')
    def lookup_page():
        serial = request.args.get('serial', '')
        if serial and SERIAL_RE.fullmatch(serial) is None:
            abort(400)
        return render_lookup(serial)

    @app.get('/s/<serial>')
    @app.get('/<serial>')
    def serial_page(serial):
        if SERIAL_RE.fullmatch(serial) is None:
            abort(404)
        return render_lookup(serial)

    def render_lookup(serial):
        wallet = None
        error = None
        if serial:
            response = lookup_response(serial)
            if isinstance(response, tuple):
                error = response[0].get_json()['error']
            else:
                wallet = response.get_json()
        return render_template('lookup.html', serial=serial, wallet=wallet, lookup_error=error)

    @app.get('/healthz')
    def health():
        return jsonify(status='ok')

    def lookup_response(serial):
        if SERIAL_RE.fullmatch(serial) is None:
            return jsonify(error='invalid_serial'), 400
        try:
            record = app.config.get('WALLET_LOOKUP', database_lookup)(serial)
            if record is None:
                return jsonify(error='not_found'), 404
            address = record['address']
            if not isinstance(address, str) or len(address) != 42 or re.fullmatch(r'bc1q[02-9ac-hj-np-z]{38}', address) is None:
                raise ValueError('Malformed public Bitcoin address')
            version, program = decode_segwit('bc', address)
            if version != 0 or program is None or len(program) != 20 or not address.startswith('bc1q'):
                raise ValueError('Invalid public Bitcoin address')
            return jsonify(serial=serial, address=address, explorer_url='https://mempool.space/address/' + address)
        except Exception:
            app.logger.warning('Public wallet lookup unavailable')
            return jsonify(error='unavailable'), 503

    @app.get('/api/wallets/<path:serial>')
    def wallet(serial):
        return lookup_response(serial)

    @app.get('/api/wallets/<serial>/qr.svg')
    def wallet_qr(serial):
        response = lookup_response(serial)
        if isinstance(response, tuple):
            return response
        image = qrcode.make(response.get_json()['address'], image_factory=qrcode.image.svg.SvgPathImage, border=4)
        output = io.BytesIO()
        image.save(output)
        return Response(output.getvalue(), mimetype='image/svg+xml')

    return app

from __future__ import annotations

import os
import io
import re
import ipaddress
from pathlib import Path

from bech32 import decode as decode_segwit
from flask import Flask, Response, abort, jsonify, redirect, render_template, request
import psycopg
import qrcode
import qrcode.image.svg
from market import MarketService

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
    app.extensions['market_service'] = app.config.get('MARKET_SERVICE') or MarketService()
    app.config['MAX_CONTENT_LENGTH'] = 16384

    @app.before_request
    def validate_api_serial():
        # Operator-supplied wallet originals are never public guide assets.
        if (request.endpoint == 'static' and
                Path(request.view_args.get('filename', '')).name.lower() in {'privatekey.png', 'publickey.png'}):
            abort(404)
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
        # Native POSTs from no-referrer pages can carry Origin:null in Chromium.
        # Keep same-origin metadata for the contact form, never for external links.
        response.headers['Referrer-Policy'] = 'same-origin' if request.endpoint == 'contact' else 'no-referrer'
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
    @app.get('/t')
    def terms():
        return render_template('terms.html')

    @app.get('/satoshi')
    def satoshi():
        return render_template('satoshi.html')

    @app.get('/costs')
    def costs():
        return render_template('costs.html')

    def contact_service():
        if 'contact_service' not in app.extensions:
            service = app.config.get('CONTACT_SERVICE')
            if service is None:
                from contact import ContactService
                service = ContactService()
            app.extensions['contact_service'] = service
        return app.extensions['contact_service']

    def contact_client_ip():
        peer = ipaddress.ip_address(request.remote_addr or '127.0.0.1')
        # Caddy appends the real connecting IP. Never trust a user-supplied first hop.
        forwarded = request.headers.get('X-Forwarded-For', '')
        if (peer.is_private or peer.is_loopback) and forwarded:
            try:
                return str(ipaddress.ip_address(forwarded.split(',')[-1].strip()))
            except ValueError:
                pass
        return str(peer)

    @app.route('/contact', methods=['GET', 'POST'])
    def contact():
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            if origin and origin not in {'https://btc4.fun', 'https://go.btc4.fun'}:
                abort(403)
            if request.mimetype != 'application/x-www-form-urlencoded':
                abort(415)
            if any(len(request.form.getlist(key)) != 1 for key in request.form):
                abort(400)
            if set(request.form) - {'name', 'mobile', 'message', 'csrf_token', 'website'}:
                abort(400)
            form = request.form.to_dict()
            if 'message' in form:
                form['message'] = form['message'].replace('\r\n', '\n')
            try:
                contact_service().submit(form, contact_client_ip())
                return redirect('/contact?sent=1', code=303)
            except Exception as error:
                code = getattr(error, 'code', 'unavailable')
                messages = {
                    'invalid': 'نام، راه تماس و متن پیام را بررسی کنید؛ فقط پرسش عمومی و بدون اطلاعات محرمانه بفرستید.',
                    'csrf': 'اعتبار فرم تمام شده یا معتبر نیست. صفحه را دوباره باز کنید.',
                    'replayed': 'این فرم قبلاً استفاده شده است؛ برای جلوگیری از پیام تکراری دوباره ارسال نمی‌شود.',
                    'rate_limited': 'تعداد پیام‌ها زیاد است؛ لطفاً بعداً تلاش کنید یا ایمیل بفرستید.',
                }
                message = messages.get(code, 'نتیجهٔ ارسال مشخص نیست؛ پیام خودکار تکرار نمی‌شود. برای پیگیری از ایمیل استفاده کنید.')
                status = 429 if code == 'rate_limited' else 400 if code in messages else 503
                return render_template('contact.html', contact_error=message, contact_token=None), status
        try:
            token = contact_service().token()
            return render_template('contact.html', contact_token=token, contact_sent=request.args.get('sent') == '1')
        except Exception:
            return render_template('contact.html', contact_token=None, contact_error='فرم فعلاً در دسترس نیست؛ از ایمیل استفاده کنید.')

    @app.get('/api/market')
    def market_data():
        try:
            snapshot = app.extensions['market_service'].snapshot()
            from pricing import quote_table
            quote = quote_table(snapshot['raw_prices']['btc_toman'], snapshot['raw_prices']['usdt_toman'], snapshot['fee_rate'])
            raw_rates = {name: snapshot['raw_prices'][name] for name in ('btc_toman', 'usdt_toman')}
            return jsonify(**quote, raw_rates=raw_rates, status=snapshot['status'], fetched_at=snapshot['fetched_at'], source=snapshot['source'])
        except Exception:
            app.logger.warning('Public market information unavailable')
            return jsonify(error='market_unavailable'), 503

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
        status = 200
        retry_after = None
        if serial:
            response = lookup_response(serial)
            if isinstance(response, tuple):
                error = response[0].get_json()['error']
                if response[1] in (429, 503):
                    status = response[1]
                    retry_after = response[0].headers.get('Retry-After')
            else:
                wallet = response.get_json()
        html = render_template('lookup.html', serial=serial, wallet=wallet, lookup_error=error,
                               lookup_retry_after=retry_after)
        return html, status, ({'Retry-After': retry_after} if retry_after else {})

    @app.get('/healthz')
    def health():
        return jsonify(status='ok')

    def lookup_response(serial, *, qr=False):
        if SERIAL_RE.fullmatch(serial) is None:
            return jsonify(error='invalid_serial'), 400
        try:
            if 'lookup_limiter' not in app.extensions:
                limiter = app.config.get('LOOKUP_LIMITER')
                if limiter is None:
                    from lookup_limit import LookupLimiter
                    limiter = LookupLimiter()
                app.extensions['lookup_limiter'] = limiter
            retry = app.extensions['lookup_limiter'].admit(contact_client_ip(), serial, qr=qr)
            if retry:
                response = jsonify(error='rate_limited', retry_after=retry)
                response.headers['Retry-After'] = str(retry)
                return response, 429
        except Exception:
            app.logger.warning('Public lookup admission unavailable')
            return jsonify(error='unavailable'), 503
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
        response = lookup_response(serial, qr=True)
        if isinstance(response, tuple):
            return response
        image = qrcode.make(response.get_json()['address'], image_factory=qrcode.image.svg.SvgPathImage, border=4)
        output = io.BytesIO()
        image.save(output)
        return Response(output.getvalue(), mimetype='image/svg+xml')

    return app

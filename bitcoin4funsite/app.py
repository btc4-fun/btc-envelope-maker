from __future__ import annotations

import os
import io
import json
import re
import ipaddress
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from address_validation import valid_address
from flask import Flask, Response, abort, jsonify, redirect, render_template, request
import psycopg
import qrcode
import qrcode.image.svg
from market import MarketService

# Generator serial_stem: YY + month (1..b) + day (1..u) + hour
# (midnight=z, otherwise 1..m) + decimal MMSS or case-sensitive base60 MS.
# Prefix is operator-defined; retain the existing website's ASCII/64-char
# envelope, accepting any prefix within it and any positive base36 index width.
# This is shape admission, not a proof of issuance or a unique parse.
# Two accepted shapes after the optional operator prefix:
#   legacy (9-char stem): YY(2) + M + D + H + (MMSS digits | MS base60) + index
#   short  (5-char stem): Y(1,base36) + M + D + H + X(1,base36) + index
# Both are shape admission only, not a proof of issuance or a unique parse.
SERIAL_PATTERN = (
    r'(?=[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$)[A-Za-z0-9_\-]*'
    r'(?:'
    r'[0-9]{2}[0-9ab][0-9a-u][0-9a-mz](?:[0-5][0-9][0-5][0-9]|[0-9a-zA-X]{2})[0-9a-z]+'
    r'|'
    r'[0-9a-z][0-9ab][0-9a-u][0-9a-mz][0-9a-z][0-9a-z]+'
    r')'
)
SERIAL_RE = re.compile(SERIAL_PATTERN)

# Allowed hosts for the optional public site/image URLs (must mirror the generator).
PUBLIC_URL_HOSTS = frozenset({'btc4.fun', 'btc.saeb.id.ir', 'b.tc4fun.ir'})
SITE_KEY_RE = re.compile(r'[A-Za-z0-9._-]{1,64}')
_URL_RE = re.compile(r'https://[^\s/]+(?:/[^\s]*)?')
# Control/format characters: same admission rule as contact text, plus bidi marks.
_UNSAFE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]')


def _public_text(value, maximum):
    """Return a stripped string or None; drop anything unsafe/oversized."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > maximum or _UNSAFE.search(text):
        return None
    return text


def _public_url(value):
    """Allow only absolute https URLs on the allowlisted hosts, with no port or userinfo."""
    text = _public_text(value, 512)
    if text is None or _URL_RE.fullmatch(text) is None:
        return None
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    if (parts.scheme != 'https' or parts.hostname is None
            or parts.hostname.lower() not in PUBLIC_URL_HOSTS
            or port is not None or parts.username or parts.password):
        return None
    return text


LINK_KEY_RE = re.compile(r'[a-z0-9][a-z0-9._-]{0,31}')
MAX_LABEL_CHARS = 32
MAX_PUBLIC_LINKS = 20
# A contact route may be an https site or a mailto:/tel: address.
LINK_SCHEMES = ('https', 'mailto', 'tel')
_EMAIL_RE = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')
_PHONE_RE = re.compile(r'[+0-9][0-9 ().-]*')


def _link_href(value):
    """A public link value: https anywhere, mailto:/tel:, or a bare email/phone.

    A public link is the seller's own profile page (Instagram, Telegram, ...),
    so unlike site_url/image_url it is NOT limited to our hosts: only the shape
    is checked. A bare email or phone (no scheme) becomes mailto:/tel:.
    """
    text = _public_text(value, 512)
    if text is None:
        return None
    if any(c.isspace() for c in text) and '@' not in text and _PHONE_RE.fullmatch(text) is None:
        return None
    scheme = text.split(':', 1)[0].lower()
    if scheme in ('mailto', 'tel'):
        target = text.split(':', 1)[1].strip()
        if not target:
            return None
        if scheme == 'tel':
            if _PHONE_RE.fullmatch(target) is None:
                return None
            digits = re.sub(r'[ ().-]', '', target)
            return 'tel:' + digits if len(digits) >= 5 else None
        return 'mailto:' + target if _EMAIL_RE.fullmatch(target) else None
    if '@' in text and '/' not in text:
        return 'mailto:' + text if _EMAIL_RE.fullmatch(text) else None
    if _PHONE_RE.fullmatch(text):
        digits = re.sub(r'[ ().-]', '', text)
        return 'tel:' + digits if len(digits) >= 5 else None
    # A seller's own page; any host is fine, but the shape must be safe. A host
    # with an underscore (e.g. a t.me alias) is accepted on purpose.
    if scheme != 'https':
        return None
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    if not parts.netloc or parts.username or parts.password or port is not None:
        return None
    return text


def _link_label(raw_key):
    """An ASCII slug (lowercased) or short human text such as a Persian name."""
    label = _public_text(raw_key, MAX_LABEL_CHARS)
    if label is None:
        return None
    return label.lower() if LINK_KEY_RE.fullmatch(label.lower()) else label


def _public_links(value):
    """Optional label/value public links (instagram, telegram, ...) or None.

    Stored as JSON text in one column. A label is an ASCII slug or short human
    text; a value is any absolute https URL, a mailto:/tel: route, or a bare
    email/phone. Unsafe or rejected entries are dropped one by one so a single
    bad link never hides the rest.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = json.loads(text)
        except ValueError:
            return None
    if not isinstance(value, dict):
        return None
    links = {}
    for raw_key, raw_value in value.items():
        label = _link_label(raw_key)
        if label is None or label in links:
            continue
        href = _link_href(raw_value)
        if href is not None:
            links[label] = href
        if len(links) >= MAX_PUBLIC_LINKS:
            break
    return links or None


def public_payload(record):
    """Build the optional `public` dict, or None when there is nothing to show.

    Shape: {"notes": str|null, "site": {"key", "url"} } plus "image_url" and
    "links" (a key/value map) when set. site_key and site_url are published
    together or not at all."""
    if not isinstance(record, dict):
        return None
    notes = _public_text(record.get('public_notes'), 500)
    site_key = _public_text(record.get('site_key'), 64)
    site_url = _public_url(record.get('site_url'))
    image_url = _public_url(record.get('image_url'))
    links = _public_links(record.get('public_links'))
    if site_key is not None and (SITE_KEY_RE.fullmatch(site_key) is None or site_url is None):
        site_key = site_url = None
    site = {'key': site_key, 'url': site_url} if site_key is not None else None
    if notes is None and site is None and image_url is None and links is None:
        return None
    payload: dict = {'notes': notes}
    if site is not None:
        payload['site'] = site
    if image_url is not None:
        payload['image_url'] = image_url
    if links is not None:
        payload['links'] = links
    return payload


def database_lookup(serial, *, by_tag=False, by_address=False):
    if by_tag and by_address:
        raise ValueError('Ambiguous lookup mode')
    # Identifiers are fixed here; request values are always bound parameters.
    column = 'address' if by_address else 'nfc_uid' if by_tag else 'serial'
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
            if by_tag:
                cursor.execute('SELECT serial, address FROM public.wallets WHERE nfc_uid = %s LIMIT 1', (serial,))
                row = cursor.fetchone()
                return {'serial': row[0], 'address': row[1]} if row else None
            # Only the optional PUBLIC columns may be selected; private
            # contact_type/contact_value/notes are never read by the website.
            cursor.execute(f'SELECT serial, address, public_notes, site_key, site_url, image_url, '
                           f'public_links FROM public.wallets WHERE {column} = %s LIMIT 1', (serial,))
            row = cursor.fetchone()
    if not row:
        return None
    return {'serial': row[0], 'address': row[1], 'public_notes': row[2],
            'site_key': row[3], 'site_url': row[4], 'image_url': row[5],
            'public_links': row[6]}


def create_app(config=None):
    app = Flask(__name__, root_path=str(Path(__file__).resolve().parent))
    app.config['TAG_LOOKUP_ENABLED'] = os.environ.get('TAG_LOOKUP_ENABLED') == '1'
    if config:
        app.config.update(config)
    def proxy_network(value):
        network = ipaddress.ip_network(value.strip(), strict=False)
        # Convert only networks wholly contained in the IPv4-mapped range.
        if (isinstance(network, ipaddress.IPv6Network) and network.prefixlen >= 96
                and network.network_address.ipv4_mapped is not None):
            return ipaddress.ip_network((network.network_address.ipv4_mapped,
                                         network.prefixlen - 96))
        return network

    trusted_proxies = tuple(proxy_network(value)
                            for value in app.config.get('TRUSTED_PROXIES',
                                os.environ.get('TRUSTED_PROXIES', '')).split(',') if value.strip())
    app.extensions['market_service'] = app.config.get('MARKET_SERVICE') or MarketService()
    app.config['MAX_CONTENT_LENGTH'] = 16384

    @app.context_processor
    def seo_context():
        # Canonicals are fixed to the public informational allowlist. Never
        # derive this URL from Host or another request-controlled value.
        canonical_paths = {
            '/': 'https://btc4.fun/',
            '/guide': 'https://btc4.fun/guide',
            '/security': 'https://btc4.fun/security',
            '/terms': 'https://btc4.fun/terms',
            '/t': 'https://btc4.fun/terms',
            '/download': 'https://btc4.fun/download',
            '/costs': 'https://btc4.fun/costs',
            '/aml': 'https://btc4.fun/aml',
        }
        return {'canonical_url': canonical_paths.get(request.path)}

    @app.before_request
    def validate_api_serial():
        if request.endpoint in {'lookup_page', 'serial_page', 'wallet', 'wallet_qr'}:
            allowed = {'serial', 'balance'} if request.endpoint == 'lookup_page' else {'balance'}
            if request.endpoint == 'wallet_qr':
                allowed = set()
            if (set(request.args) - allowed
                    or any(len(request.args.getlist(key)) != 1 for key in request.args)
                    or ('balance' in request.args and request.args['balance'] != '1')
                    or (request.endpoint == 'lookup_page' and 'balance' in request.args
                        and not request.args.get('serial'))):
                return jsonify(error='invalid_lookup_request'), 400
        if request.path.startswith('/api/addresses/'):
            # Validate the raw (still percent-encoded) path segment so control
            # characters and malformed percent-escapes can never reach routing.
            raw = request.path.removeprefix('/api/addresses/')
            if re.fullmatch(r'[\x21-\x7e]+', raw) is None:
                return jsonify(error='invalid_address'), 400
        if (request.endpoint == 'address_serial'
                and request.view_args and isinstance(request.view_args.get('address'), str)
                and not valid_address(request.view_args['address'])):
            return jsonify(error='invalid_address'), 400
        if request.endpoint == 'address_serial' and request.query_string:
            # Without the flag the response stays exactly the historical 3-key
            # body. With it, accept only a single balance=1.
            if (set(request.args) != {'balance'} or len(request.args.getlist('balance')) != 1
                    or request.args['balance'] != '1'):
                return jsonify(error='invalid_lookup_request'), 400
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
        if (request.path.startswith('/api/')
                or request.endpoint in {'lookup_page', 'serial_page', 'contact'}):
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
        # The child-friendly explainer was merged into the adult guide.
        return redirect('/guide', code=301)

    @app.get('/security')
    def security():
        return render_template('security.html')

    @app.get('/download')
    def download():
        return render_template('download.html')

    @app.get('/terms')
    @app.get('/t')
    def terms():
        return render_template('terms.html')

    @app.get('/aml')
    def aml():
        return render_template('aml.html')

    @app.get('/satoshi')
    def satoshi():
        # Keep old bookmarks useful after folding the unit explainer into the guide.
        return redirect('/guide#satoshi', code=301)

    @app.get('/robots.txt')
    def robots():
        return Response('User-agent: *\nAllow: /\nDisallow: /lookup\nDisallow: /s/\nDisallow: /api/\nSitemap: https://btc4.fun/sitemap.xml\n', mimetype='text/plain')

    @app.get('/sitemap.xml')
    def sitemap():
        pages = ('/', '/guide', '/security', '/terms', '/download', '/costs', '/aml')
        body = ''.join(f'<url><loc>https://btc4.fun{path}</loc></url>' for path in pages)
        return Response('<?xml version="1.0" encoding="UTF-8"?>'
                        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        + body + '</urlset>', mimetype='application/xml')

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
        peer = ipaddress.ip_address(request.remote_addr or '')
        if isinstance(peer, ipaddress.IPv6Address) and peer.ipv4_mapped is not None:
            peer = peer.ipv4_mapped
        # Only explicitly configured connecting peers may assert a forwarded IP.
        if any(peer in network for network in trusted_proxies):
            value = request.headers.get('X-Forwarded-For', '').split(',')[-1].strip()
            try:
                if '%' not in value:
                    return str(ipaddress.ip_address(value))
            except ValueError:
                pass
        return str(peer)

    @app.route('/contact', methods=['GET', 'POST'])
    def contact():
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            if origin not in {'https://btc4.fun', 'https://go.btc4.fun'}:
                abort(403)
            if request.mimetype != 'application/x-www-form-urlencoded':
                abort(415)
            if any(len(request.form.getlist(key)) != 1 for key in request.form):
                abort(400)
            if set(request.form) - {'name', 'mobile', 'message', 'csrf_token', 'website', 'captcha_answer'}:
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
                    'captcha': 'پاسخ جمع درست نیست. فرم را دوباره باز کنید و پاسخ را بنویسید.',
                    'csrf': 'اعتبار فرم تمام شده یا معتبر نیست. صفحه را دوباره باز کنید.',
                    'replayed': 'این فرم قبلاً استفاده شده است؛ برای جلوگیری از پیام تکراری دوباره ارسال نمی‌شود.',
                    'rate_limited': 'تعداد پیام‌ها زیاد است؛ لطفاً بعداً تلاش کنید یا ایمیل بفرستید.',
                }
                message = messages.get(code, 'نتیجهٔ ارسال مشخص نیست؛ پیام خودکار تکرار نمی‌شود. برای پیگیری از ایمیل استفاده کنید.')
                status = 429 if code == 'rate_limited' else 400 if code in messages else 503
                return render_template('contact.html', contact_error=message, contact_token=None), status
        try:
            token = contact_service().token()
            return render_template('contact.html', contact_token=token, contact_question=contact_service().question(token),
                                   contact_sent=request.args.get('sent') == '1')
        except Exception:
            return render_template('contact.html', contact_token=None, contact_error='فرم فعلاً در دسترس نیست؛ از ایمیل استفاده کنید.')

    @app.get('/api/market')
    def market_data():
        try:
            snapshot = app.extensions['market_service'].snapshot()
            from pricing import quote_table
            quote = quote_table(snapshot['raw_prices']['btc_toman'], snapshot['raw_prices']['usdt_toman'], snapshot['fee_rate'])
            raw_rates = {name: snapshot['raw_prices'][name] for name in ('btc_toman', 'usdt_toman')}
            quote_options = {}
            for speed in ('economy', 'medium', 'fast'):
                rate = snapshot['fee_rate'] if speed == 'economy' else snapshot.get('fee_rates', {}).get(speed)
                try:
                    quote_options[speed] = {
                        variant: quote_table(**raw_rates, fee_rate=rate, include_tag=enabled)
                        for variant, enabled in (('no_tag', False), ('with_tag', True))
                    }
                except ValueError:
                    quote_options[speed] = None
            return jsonify(**quote, quote_options=quote_options, raw_rates=raw_rates,
                           status=snapshot['status'], fetched_at=snapshot['fetched_at'], source=snapshot['source'])
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
                body = response[0].get_json()
                if 'balance_error' in body:
                    wallet = body
                else:
                    error = body['error']
                if response[1] in (429, 503):
                    status = response[1]
                    retry_after = response[0].headers.get('Retry-After')
            else:
                wallet = response.get_json()
        html = render_template('lookup.html', serial=serial, wallet=wallet, lookup_error=error,
                               lookup_retry_after=retry_after, serial_pattern=SERIAL_PATTERN)
        return html, status, ({'Retry-After': retry_after} if retry_after else {})

    @app.get('/healthz')
    def health():
        return jsonify(status='ok')

    @app.get('/api/tags/<path:uid>')
    def tag_activity(uid):
        if app.config.get('TAG_LOOKUP_ENABLED') is not True:
            return jsonify(error='tag_lookup_disabled'), 503
        from tag_access import TagLimiter, TagAudit
        started = time.monotonic()
        audit_failed = False
        error_recorder: Callable[[int], None] | None = None
        try:
            client_ip = contact_client_ip()
            audit = app.config.get('TAG_AUDIT') or TagAudit()

            def record(status):
                nonlocal audit_failed
                # Route pattern avoids persisting arbitrary path/query secrets.
                try:
                    audit.record(client_ip=client_ip, method=request.method,
                                 path='/api/tags/:uid', status=status,
                                 duration_ms=(time.monotonic() - started) * 1000,
                                 headers=request.headers)
                except Exception:
                    audit_failed = True
                    raise

            def finish(body, status, headers=None):
                record(status)
                return jsonify(body), status, headers or {}

            cursor = request.args.get('after_txid')
            if (re.fullmatch(r'(?:[0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})', uid) is None
                    or set(request.args) - {'after_txid'}
                    or len(request.args.getlist('after_txid')) > 1
                    or (cursor is not None and re.fullmatch(r'[0-9a-f]{64}', cursor) is None)):
                return jsonify(error='invalid_tag_request'), 400
            limiter = app.config.get('TAG_LIMITER') or TagLimiter()
            retry = limiter.admit(client_ip)
            if retry:
                return jsonify(error='rate_limited', retry_after=retry), 429, {'Retry-After': str(retry)}
            # Accepted requests prove audit writability before data/network access.
            record(102)
            error_recorder = record
            lookup = app.config.get('TAG_LOOKUP')
            wallet = lookup(uid) if lookup else database_lookup(uid, by_tag=True)
            if wallet is None:
                return finish({'error': 'not_found'}, 404)
            if not valid_address(wallet['address']) or SERIAL_RE.fullmatch(wallet['serial']) is None:
                raise ValueError('Invalid public wallet')
            service = app.config.get('TAG_ACTIVITY')
            if service is None:
                from chain_activity import ChainActivity
                service = ChainActivity()
            activity = service.snapshot(wallet['address'], after_txid=cursor)
            return finish(dict(activity, serial=wallet['serial']), 200)
        except Exception:
            # Best effort final error record, never retry a possibly-written line.
            # If audit itself failed, no public data is returned.
            if error_recorder is not None and not audit_failed:
                try:
                    error_recorder(503)
                except Exception:
                    pass
            app.logger.warning('Tag inquiry unavailable')
            return jsonify(error='tag_unavailable'), 503

    @app.get('/api/addresses/<path:address>')
    def address_serial(address):
        admission = lookup_admission('address_' + address, qr=False)
        if admission is not None:
            return admission
        try:
            lookup = app.config.get('ADDRESS_LOOKUP')
            record = lookup(address) if lookup is not None else database_lookup(address, by_address=True)
            if record is None:
                return jsonify(error='not_found'), 404
            serial = record['serial']
            if record['address'] != address or SERIAL_RE.fullmatch(serial) is None:
                raise ValueError('Invalid public wallet')
            body = dict(address=address, serial=serial, lookup_url='https://btc4.fun/s/' + serial)
            if request.args.get('balance') == '1':
                # Same balance object as /api/wallets?balance=1.
                service = app.config.get('SERIAL_BALANCE')
                if service is None:
                    from chain_activity import ChainActivity
                    service = ChainActivity()
                try:
                    body['balance'] = service.balance(address)
                except Exception:
                    app.logger.warning('Public address balance unavailable')
                    return jsonify(**body, error='balance_unavailable'), 503
                public = public_payload(record)
                if public is not None:
                    body['public'] = public
            return jsonify(body)
        except Exception:
            app.logger.warning('Public address lookup unavailable')
            return jsonify(error='unavailable'), 503

    def lookup_admission(serial, *, qr=False):
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

    def lookup_response(serial, *, qr=False):
        if SERIAL_RE.fullmatch(serial) is None:
            return jsonify(error='invalid_serial'), 400
        admission = lookup_admission(serial, qr=qr)
        if admission is not None:
            return admission
        try:
            record = app.config.get('WALLET_LOOKUP', database_lookup)(serial)
            if record is None:
                return jsonify(error='not_found'), 404
            address = record['address']
            if not valid_address(address):
                raise ValueError('Invalid public Bitcoin address')
            public = dict(serial=serial, address=address, explorer_url='https://mempool.space/address/' + address)
            if not qr and request.args.get('balance') == '1':
                service = app.config.get('SERIAL_BALANCE')
                if service is None:
                    from chain_activity import ChainActivity
                    service = ChainActivity()
                try:
                    public['balance'] = service.balance(address)
                except Exception:
                    app.logger.warning('Public serial balance unavailable')
                    return jsonify(**public, balance_error='unavailable'), 503
                extra = public_payload(record)
                if extra is not None:
                    public['public'] = extra
            # The browser page renders optional metadata from this same lookup;
            # attach it only where the caller asked for it (never to the 3-key
            # /api/addresses body, whose shape the released app depends on).
            if request.path.startswith('/s/') or request.path.startswith('/lookup'):
                extra = public_payload(record)
                if extra is not None:
                    public['public'] = extra
            return jsonify(public)
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

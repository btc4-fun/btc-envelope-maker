"""Public payment details: exact operator-provided values, no transfers."""
from pathlib import Path
import io
import json
import subprocess
import sys
import unittest

import qrcode
import qrcode.image.svg
from jinja2 import Environment, FileSystemLoader, select_autoescape
from test_ui_contract import Document

ROOT = Path(__file__).resolve().parents[1]
CARD = '6219861819062158'
SHEBA = '930560611828006181828601'


class PaymentContract(unittest.TestCase):
    def test_qr_assets_encode_exact_numbers_and_are_served_locally(self):
        sys.path.insert(0, str(ROOT))
        from app import create_app
        client = create_app({'TESTING': True}).test_client()
        for key, value in (('card', CARD), ('sheba', SHEBA)):
            with self.subTest(kind=key):
                response = client.get('/static/payment-' + key + '.svg')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'image/svg+xml')
                expected = io.BytesIO()
                qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage,
                            border=4).save(expected)
                self.assertEqual(response.data, expected.getvalue())
                response.close()

    def test_click_copy_switch_keyboard_and_failure_paths(self):
        env = Environment(loader=FileSystemLoader(ROOT / 'templates'),
                          autoescape=select_autoescape(['html']))
        doc = Document(env.get_template('costs.html').render())
        attrs = {a['id']: a for _, a in doc.elements if a.get('id', '').startswith('payment-')}
        harness = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const attrs = JSON.parse(process.argv[2]);
const nodes = Object.fromEntries(Object.entries(attrs).map(([id, a]) => [id, {
  attributes: {...a}, dataset: {copy: a['data-copy']}, listeners: {},
  textContent: '', src: a.src, hidden: false,
  getAttribute(k) { return this.attributes[k] ?? null; },
  setAttribute(k,v) { this.attributes[k] = String(v); },
  addEventListener(k,f) { (this.listeners[k] ||= []).push(f); },
  async emit(k, key) { for (const f of this.listeners[k] || []) await f({key, preventDefault(){}}); }
}]));
global.document = {getElementById: id => nodes[id] || null};
Object.defineProperty(global, 'navigator', {value: {}, configurable: true});
global.fetch = () => {throw Error('No network calls for payment interactions');};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
(async () => {
  const status = nodes['payment-status'];
  for (const [key, value] of [['card', '6219861819062158'], ['sheba', '930560611828006181828601']]) {
    const button = nodes['payment-copy-' + key];
    delete navigator.clipboard;
    await button.emit('click');
    assert.match(status.textContent, /دستی/);
    navigator.clipboard = {writeText: async () => {throw Error('Denied');}};
    await button.emit('click');
    assert.match(status.textContent, /دستی/);
    let copied;
    navigator.clipboard = {writeText: async text => {copied = text;}};
    await button.emit('click');
    assert.equal(copied, value);
    assert.match(status.textContent, /کپی شد/);
  }
  const qr = nodes['payment-qr'];
  for (const key of ['sheba','card','sheba']) {
    await nodes['payment-show-' + key].emit('click');
    assert.equal(qr.src, '/static/payment-' + key + '.svg');
    assert.equal(nodes['payment-show-' + key].attributes['aria-pressed'], 'true');
    assert.equal(nodes['payment-show-' + (key === 'card' ? 'sheba' : 'card')].attributes['aria-pressed'], 'false');
    await qr.emit('load');
    assert.equal(qr.hidden, false);
    assert.match(nodes['payment-qr-caption'].textContent, key === 'card' ? /کارت/ : /شبا/);
  }
  await qr.emit('error');
  assert.equal(qr.hidden, true);
  assert.match(nodes['payment-qr-caption'].textContent, /دسترس نیست/);
  await nodes['payment-show-card'].emit('keydown', ' ');
  assert.equal(qr.src, '/static/payment-card.svg');
  await qr.emit('load');
  assert.equal(qr.hidden, false);
})().catch(e => {console.error(e); process.exitCode = 1;});
'''
        result = subprocess.run(['node', '-e', harness, str(ROOT / 'static/site.js'),
                                 json.dumps(attrs)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_payment_details_and_warnings_are_shared_and_readable_without_js(self):
        env = Environment(loader=FileSystemLoader(ROOT / 'templates'),
                          autoescape=select_autoescape(['html']))
        for name in ('costs.html', 'terms.html', 'guide.html'):
            with self.subTest(page=name):
                source = env.get_template(name).render()
                doc = Document(source)
                self.assertIn('id="payment-details"', source)
                self.assertIn('صائب ملایی', source)
                for key, value in (('card', CARD), ('sheba', SHEBA)):
                    button = doc.by_id('payment-copy-' + key)
                    self.assertEqual(button['data-copy'], value)
                    self.assertEqual(button['type'], 'button')
                    self.assertEqual(button['dir'], 'ltr')
                    self.assertIn(value, source)
                for phrase in ('اطلاعات پرداخت دیگری', 'از غریبه خرید', 'اگر متخصص نیستید',
                               'اصلاً خرید نکنید', 'حتی اگر موجودی داشته باشد',
                               'شخص اول', 'کلمات بازیابی', 'کیف پول تازه'):
                    self.assertIn(phrase, source)
                self.assertEqual(doc.by_id('payment-qr')['src'], '/static/payment-card.svg')
                self.assertEqual(doc.by_id('payment-status')['aria-live'], 'polite')
                for key in ('card', 'sheba'):
                    self.assertEqual(doc.by_id('payment-show-' + key)['href'],
                                     '/static/payment-' + key + '.svg')
                self.assertEqual(doc.by_id('payment-show-card')['aria-pressed'], 'true')
                self.assertEqual(doc.by_id('payment-show-sheba')['aria-pressed'], 'false')

    def test_home_has_one_merged_warning_without_full_payment_details(self):
        env = Environment(loader=FileSystemLoader(ROOT / 'templates'),
                          autoescape=select_autoescape(['html']))
        source = env.get_template('index.html').render()
        self.assertNotIn('id="payment-details"', source)
        self.assertNotIn(CARD, source)
        self.assertNotIn(SHEBA, source)
        self.assertNotIn('/static/payment-card.svg', source)
        self.assertEqual(source.count('از غریبه پاکت نخرید.'), 1)
        self.assertEqual(source.count('id="purchase-warning"'), 1)
        warning = source.split('id="purchase-warning"', 1)[1].split('</div>', 1)[0]
        for phrase in ('جعل', 'کیف پول دیگری', 'اگر متخصص نیستید', 'اصلاً خرید نکنید',
                       'حتی اگر موجودی داشته باشد', 'شخص اول', 'کیف پول تازه',
                       'اگر اطلاعات پرداخت با اطلاعات سایت یکی نیست، یعنی از غریبه خرید می‌کنید.'):
            self.assertIn(phrase, warning)
        self.assertIn('href="/costs#payment-details"', warning)
        for name in ('index.html', 'costs.html', 'terms.html', 'guide.html'):
            rendered = env.get_template(name).render()
            self.assertEqual(rendered.count('id="purchase-warning"'), 1, name)
            self.assertNotIn('href="/#payment-details"', rendered)


if __name__ == '__main__':
    unittest.main()

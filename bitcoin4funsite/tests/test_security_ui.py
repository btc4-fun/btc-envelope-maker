"""Offline security guidance and real client-script behavior (no answer collection)."""
import json
import re
from pathlib import Path
import subprocess
import unittest

from jinja2 import Environment, FileSystemLoader, select_autoescape
from test_ui_contract import Document

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ('secrets', 'public', 'device', 'apps', 'password', 'updates',
             'shared', 'compromise', 'links', 'knowledge')


class SecurityUI(unittest.TestCase):
    def render(self):
        path = ROOT / 'templates/security.html'
        self.assertTrue(path.is_file(), 'Missing security guidance page')
        env = Environment(loader=FileSystemLoader(ROOT / 'templates'),
                          autoescape=select_autoescape(['html']))
        return env.get_template('security.html').render()

    def test_questionnaire_is_accessible_local_and_validates_before_scoring(self):
        source = self.render()
        doc = Document(source)
        scripts = [a['src'] for t, a in doc.elements if t == 'script']
        self.assertIn('/static/security.js', scripts)
        self.assertNotIn('/static/security.js', Environment(
            loader=FileSystemLoader(ROOT / 'templates')).get_template('index.html').render())
        self.assertFalse(any(t == 'form' for t, a in doc.elements),
                         'No native submission path for sensitive answers')
        self.assertIn('hidden', doc.by_id('security-questionnaire'))
        self.assertEqual(doc.by_id('security-check')['type'], 'button')
        self.assertEqual(doc.by_id('security-status')['role'], 'status')
        self.assertEqual(doc.by_id('security-result')['tabindex'], '-1')
        for name in QUESTIONS:
            group = doc.by_id('security-' + name)
            self.assertIn('security-status', group['aria-describedby'])
            self.assertIn('id="legend-' + name + '"', source)
            radios = [a for t, a in doc.elements if t == 'input' and a.get('name') == name]
            self.assertGreaterEqual(len(radios), 2)
            for radio in radios:
                self.assertEqual(radio['type'], 'radio')
                self.assertNotIn('checked', radio)
                self.assertEqual(radio['autocomplete'], 'off')
                self.assertIn(('label', {'for': radio['id']}), doc.elements)
        self.run_script(r'''
assert.equal(ids['security-questionnaire'].hidden, false);
emit('security-check', 'click');
assert.equal(ids['security-result'].hidden, true);
assert.match(ids['security-status'].textContent, /همهٔ پرسش‌ها/);
assert.equal(ids['security-secrets'].attributes['aria-invalid'], 'true');
assert.equal(focused, radios.find(r => r.name === 'secrets').id);
for (const r of radios) r.checked = r.value === 'safe';
emit('security-check', 'click');
assert.equal(ids['security-secrets'].attributes['aria-invalid'], undefined);
assert.equal(ids['security-status'].textContent, '');
''')

    def test_educational_index_never_predicts_loss_or_permits_investment(self):
        self.run_script(r'''
const names = [...new Set(radios.map(r => r.name))];
for (const name of names) select(name, 'safe');
emit('security-check', 'click');
assert.equal(ids['security-result'].hidden, false);
assert.equal(focused, 'security-result');
assert.match(ids['security-score'].textContent, /شاخص احتیاط آموزشی: ۰ از ۱۰/);
assert.match(ids['security-advice'].textContent, /تضمین امنیت نیست/);
assert.equal(ids['security-result'].dataset.level, 'review');
for (const name of names) {
  for (const answer of ['risk', 'unknown']) {
    for (const other of names) select(other, 'safe');
    select(name, answer);
    emit('security-check', 'click');
    assert.match(ids['security-score'].textContent, /۱ از ۱۰/);
    const advice = ids['security-advice'].textContent;
    assert.match(advice, /توصیه به خرید نیست/);
    assert.match(advice, /اجازه‌ای برای گذاشتن پول زیاد نیست/);
    assert.doesNotMatch(advice, /[%٪]/);
    if (name !== 'knowledge') {
      assert.equal(ids['security-result'].dataset.level, 'stop');
      for (const instruction of ['باز نکنید', 'وارد نکنید', 'واریز نکنید', 'تا رفع']) assert.ok(advice.includes(instruction));
    } else {
      assert.equal(ids['security-result'].dataset.level, 'learn');
      assert.match(advice, /بدون پول واقعی/);
    }
    if (['compromise', 'links'].includes(name)) assert.match(advice, /به‌تنهایی ثابت نمی‌کند گوشی آلوده است/);
    const actions = {
      secrets: 'کیف پول تازه با کلمات تازه', public: 'جای خصوصی',
      device: 'دستگاه قابل اعتماد', apps: 'اجازهٔ نصب برنامه‌های ناشناس',
      password: 'قفل صفحه را روشن کنید', updates: 'به‌روز کنید',
      shared: 'گوشی مشترک', compromise: 'دستگاه‌های ناشناس را از حساب خارج کنید',
      links: 'رمز داده‌اید', knowledge: 'بدون پول واقعی'
    };
    assert.ok(advice.includes(actions[name]), name + ': missing practical next step');
    assert.doesNotMatch(advice, /نشست|افشاشده|مفاهیم|احتمال زیان|آلودگی فعلی/);
  }
}
for (const name of names) select(name, 'risk');
emit('security-check', 'click');
assert.match(ids['security-score'].textContent, /۱۰ از ۱۰/);
assert.equal(ids['security-result'].dataset.level, 'stop');
''')
        source = self.render()
        self.assertIn('هر موردی که نیاز به بررسی دارد یا درباره‌اش مطمئن نیستید، یکی حساب می‌شود', source)
        self.assertIn('این فقط یک شمارش ساده است، نه حساب علمی خطر', source)

    def test_edit_reset_and_reload_clear_results_and_answers(self):
        self.run_script(r'''
for (const r of radios) r.checked = r.value === 'safe';
emit('security-check', 'click');
select('secrets', 'risk');
emit('security-secrets-risk', 'change');
assert.equal(ids['security-result'].hidden, true, 'Never leave an outdated low result visible');
assert.equal(ids['security-score'].textContent, '');
assert.equal(ids['security-advice'].textContent, '');
emit('security-check', 'click');
assert.equal(ids['security-result'].dataset.level, 'stop');
emit('security-reset', 'click');
assert.ok(radios.every(r => !r.checked));
assert.equal(ids['security-result'].hidden, true);
assert.equal(ids['security-status'].textContent, '');
assert.equal(focused, 'security-secrets-safe');
for (const r of radios) r.checked = r.value === 'risk';
for (const handler of windowListeners.pageshow || []) handler({persisted:true});
assert.ok(radios.every(r => !r.checked), 'Clear browser back/forward restoration');
assert.equal(ids['security-result'].hidden, true);
''')
        css = (ROOT / 'static/site.css').read_text()
        self.assertIn('.security-option', css)
        self.assertIn('.security-questionnaire fieldset', css)
        self.assertIn('.security-questionnaire [aria-invalid=true]', css)

    def test_rejects_forged_and_partial_answers_without_stale_result(self):
        self.run_script(r'''
for (const r of radios) r.checked = r.value === 'safe';
emit('security-check', 'click');
select('knowledge', 'missing');
emit('security-check', 'click');
assert.equal(ids['security-result'].hidden, true);
assert.match(ids['security-status'].textContent, /همهٔ پرسش‌ها/);
select('knowledge', 'safe');
ids['security-secrets-safe'].value = 'tampered';
emit('security-check', 'click');
assert.equal(ids['security-result'].hidden, true);
assert.equal(focused, 'security-secrets-safe');
''')

    def run_script(self, assertions):
        path = ROOT / 'static/security.js'
        self.assertTrue(path.is_file(), 'Missing client-side safety questionnaire')
        attrs = [{'tag': t, **a} for t, a in Document(self.render()).elements if a.get('id')]
        harness = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let focused = null;
const windowListeners = {};
global.window = {addEventListener(k,f) { (windowListeners[k] ||= []).push(f); }};
const ids = Object.fromEntries(JSON.parse(process.argv[2]).map(a => [a.id, {
  id: a.id, name: a.name, value: a.value, attributes: {...a}, listeners: {},
  hidden: 'hidden' in a, checked: false, textContent: '', dataset: {},
  setAttribute(k,v) { this.attributes[k] = String(v); },
  getAttribute(k) { return this.attributes[k] ?? null; },
  removeAttribute(k) { delete this.attributes[k]; },
  focus() { focused = this.id; },
  addEventListener(k,f) { (this.listeners[k] ||= []).push(f); },
}]));
const radios = Object.values(ids).filter(n => n.attributes.type === 'radio');
function select(name, value) { for (const r of radios.filter(r => r.name === name)) r.checked = r.value === value; }
function emit(id, type) { for (const f of ids[id].listeners[type] || []) f({preventDefault(){}, target:ids[id]}); }
global.document = {
  getElementById: id => ids[id] || null,
  querySelectorAll: s => {
    assert.equal(s, '#security-questionnaire input[type="radio"]'); return radios;
  }
};
const forbidden = () => { throw Error('No answer transmission or persistence'); };
global.fetch = global.XMLHttpRequest = global.WebSocket = global.Image = forbidden;
Object.defineProperty(global, 'navigator', {value: {sendBeacon: forbidden}, configurable: true});
for (const k of ['localStorage','sessionStorage','indexedDB']) Object.defineProperty(global,k,{get:forbidden});
Object.defineProperty(document,'cookie',{get:forbidden,set:forbidden});
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
''' + assertions
        result = subprocess.run(['node', '-e', harness, str(path), json.dumps(attrs)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_ten_questions_use_plain_words_and_keep_answer_contract(self):
        source = self.render()
        doc = Document(source)
        anchors = {
            'secrets': ('عکس گرفته‌اید', 'کلمات کیف پول'),
            'public': ('کسی یا دوربینی', 'صفحه'),
            'device': ('دست‌کاری', 'بررسی‌نشده', 'بررسی امنیت گوشی لازم بوده و هنوز انجام نشده'),
            'apps': ('برنامه، فیلترشکن یا بازی', 'اجازه'),
            'password': ('قفل گوشی', 'تاریخ تولد'),
            'updates': ('به‌روزرسانی', 'قدیمی'),
            'shared': ('کودک یا فرد دیگری', 'برنامه نصب کند'),
            'compromise': ('حساب بانکی یا شبکهٔ اجتماعی', 'رسیدگی نشده'),
            'links': ('لینک مشکوک', 'رمز داده‌اید', 'رسیدگی نشده'),
            'knowledge': ('آدرس کیف پول', 'قیمت', 'پول'),
        }
        legends = dict(re.findall(r'<legend id="legend-([^"]+)">(.*?)</legend>', source))
        self.assertEqual(set(legends), set(QUESTIONS))
        for name, phrases in anchors.items():
            with self.subTest(question=name):
                for phrase in phrases:
                    self.assertIn(phrase, legends[name])
                self.assertNotRegex(legends[name], 'وصله|نشست|احراز|برگشت‌ناپذیری|مجوز حساس|ناشر')
                for sentence in re.split('[؟.!؛]', legends[name]):
                    self.assertLessEqual(len(sentence.split()), 24, sentence)
                radios = [a for t, a in doc.elements if t == 'input' and a.get('name') == name]
                self.assertEqual({r['value'] for r in radios}, {'safe', 'risk', 'unknown'})
                self.assertEqual(len(radios), 3)
                for radio in radios:
                    match = re.search(r'<label for="' + radio['id'] + r'">(.*?)</label>', source)
                    self.assertIsNotNone(match)
                    assert match is not None
                    label = match.group(1)
                    self.assertLessEqual(len(label.split()), 18, label)

    def test_static_guidance_corrects_misconceptions_without_javascript(self):
        source = self.render()
        doc = Document(source)
        for phrase in ('آیفون تضمین امنیت نیست', 'اندروید', 'داده‌های برنامه‌ها را از هم جدا',
                       'اپ استور', 'گوگل پلی', 'به‌تنهایی کافی نیست',
                       'عکس نگیرید', 'دوربین', 'وی‌پی‌ان', 'بازی',
                       'تاریخ تولد', 'شمارهٔ موبایل', 'کد ملی', 'تکراری',
                       'به‌روز', 'این احتیاط برای همه است، نه فقط کودکان',
                       'به‌تنهایی یعنی گوشی شما آلوده است؟ نه', 'حساب بانکی', 'لینک',
                       'برگرداندن پول ممکن نباشد', 'شاخص احتیاط آموزشی',
                       'احتمال از دست دادن پول نیست', 'توصیه به خرید نیست',
                       'اجازه‌ای برای گذاشتن پول زیاد نیست', 'عدد پایین تضمین امنیت نیست',
                       'باز نکنید', 'وارد نکنید', 'واریز نکنید',
                       'ارسال نمی‌شود', 'ذخیره نمی‌شود',
                       'کلید خصوصی و کلمات بازیابی، راز کیف پول شما هستند',
                       'نصب برنامه‌های ناشناس', 'دیدن صفحه', 'کنترل گوشی',
                       'دیگر به‌روزرسانی امنیتی نمی‌گیرد', 'رمز جدا',
                       'کد تأیید هم بخواهد', 'راز را حتی به فرد متخصص هم ندهید'):
            self.assertIn(phrase, source)
        self.assertIn('<noscript>', source)
        self.assertIn(('a', {'href': '/security', 'aria-current': 'page'}), doc.elements)
        for tag, attrs in doc.elements:
            self.assertFalse(any(k.startswith('on') for k in attrs))
            self.assertNotIn('style', attrs)
            if tag in ('script', 'img', 'link', 'iframe'):
                url = attrs.get('src', attrs.get('href', ''))
                self.assertTrue(url.startswith('/static/'), url)
        self.assertNotIn('<script>', source)


if __name__ == '__main__':
    unittest.main()

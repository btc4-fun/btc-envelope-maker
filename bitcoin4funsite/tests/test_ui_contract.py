"""Offline UI contracts; no real wallet data or external services are used."""
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def by_id(self, element_id):
        return next(attrs for _, attrs in self.elements if attrs.get("id") == element_id)


class UIContract(unittest.TestCase):
    def render(self, name, **context):
        path = ROOT / "templates" / name
        self.assertTrue(path.is_file(), f"Missing UI template: {name}")
        env = Environment(loader=FileSystemLoader(ROOT / "templates"),
                          autoescape=select_autoescape(["html"]))
        return env.get_template(name).render(**context)

    def test_home_is_accessible_self_hosted_persian_editorial(self):
        source = self.render("index.html")
        document = Document(source)
        self.assertIn(("html", {"lang": "fa", "dir": "rtl"}), document.elements)
        self.assertEqual(sum(tag == "h1" for tag, _ in document.elements), 1)
        self.assertIn('href="#main-content"', source)
        self.assertIn('id="main-content"', source)
        links = {attrs.get("href") for tag, attrs in document.elements if tag == "a"}
        self.assertTrue({"/", "/guide", "/kids", "/terms", "/lookup", "/satoshi", "/costs", "/contact"} <= links)
        self.assertIn("بیت‌کوین،", source)
        self.assertIn("در یک پاکت", source)
        self.assertIn("کلمات بازیابی", source)
        self.assertIn("btc4fun", source)
        self.assertIn("btc4.fun", source)
        self.assertIn("09113458375@btc4.fun", source)
        self.assertIn("https://github.com/sae13/btc4fun", source)
        self.assertNotIn("bitcoin4fun", source)
        self.assertNotIn("bitcoin4.fun", source)
        self.assertNotIn("/api/market", source)
        self.assertNotIn("calculator.js", source)
        for tag, attrs in document.elements:
            self.assertFalse(any(key.startswith("on") for key in attrs), attrs)
            for key in ("src", "poster"):
                if key in attrs:
                    self.assertTrue(attrs[key].startswith("/"), attrs)
            if tag == "link":
                self.assertEqual(attrs.get("rel"), "stylesheet")
                self.assertEqual(attrs.get("href"), "/static/site.css")
            if tag == "script":
                self.assertEqual(attrs.get("src"), "/static/site.js")
                self.assertIn("defer", attrs)
        css_path = ROOT / "static/site.css"
        self.assertTrue(css_path.is_file(), "Missing local visual design")
        css = css_path.read_text()
        self.assertIn("/static/fonts/Sahel.woff2", css)
        self.assertIn("/static/fonts/Sahel-Bold.woff2", css)
        self.assertIn("@media", css)
        self.assertIn(":focus-visible", css)
        self.assertNotRegex(css, r"https?://|@import")
        for script in re.findall(r"<script[^>]*>(.*?)</script>", source, re.S):
            self.assertFalse(script.strip(), "Scripts must be external for strict CSP")

    def test_header_prominently_links_to_short_terms_route(self):
        for template in ("index.html", "kids.html", "terms.html", "contact.html"):
            with self.subTest(template=template):
                source = self.render(template)
                header = source.split('<header class="site-header shell">', 1)[1].split('</header>', 1)[0]
                links = [attrs for tag, attrs in Document(header).elements
                         if tag == "a" and attrs.get("href") == "/t"]
                self.assertEqual(len(links), 1, "Terms belong in the main header navigation")
                self.assertIn("nav-terms", links[0].get("class", "").split())
                self.assertIn("شرایط استفاده", header)
                self.assertEqual(links[0].get("aria-current"), "page" if template == "terms.html" else None)

    def test_kids_label_is_consistent_in_navigation_home_and_breadcrumb(self):
        label = "راهنما برای ۷ ساله‌ها"
        for template in ("index.html", "kids.html"):
            with self.subTest(template=template):
                source = self.render(template)
                header = source.split('<header class="site-header shell">', 1)[1].split('</header>', 1)[0]
                self.assertRegex(header, r'<a href="/kids"[^>]*>' + label + r'</a>')
                self.assertNotIn("برای کوچک‌ترها", source)
                if template == "index.html":
                    main = source.split('<main id="main-content"', 1)[1].split('</main>', 1)[0]
                    card = re.search(r'<a class="path-card" href="/kids">(.*?)</a>', main, re.S)
                    self.assertIsNotNone(card)
                    self.assertIn("<h3>" + label + "</h3>", card.group(1))
                else:
                    self.assertRegex(source, r'<a class="breadcrumb"[^>]*>[^<]*<span[^>]*>/</span> ' + label + r'</a>')
                    self.assertEqual(next(attrs.get("aria-current") for tag, attrs in Document(header).elements
                                          if tag == "a" and attrs.get("href") == "/kids"), "page")

    def test_plain_safety_examples_are_shared_on_home_lookup_and_guide(self):
        for template in ('index.html', 'lookup.html', 'guide.html'):
            with self.subTest(template=template):
                source = self.render(template)
                self.assertIn('id="quick-guide"', source)
                self.assertIn('دوربین مداربسته', source)
                self.assertIn('از غریبه پاکت نخرید', source)
                self.assertIn('/static/guide-inner-example.png', source)
                self.assertIn('/static/guide-outer-example.png', source)
        terms = self.render('terms.html')
        for phrase in ('یک تراکنش واریز اولیه', 'مسئولیت فروشنده نسبت به شما تمام شده',
                       'تأییدنشده نهایی نیست', 'جعل', 'حقوق آمره'):
            self.assertIn(phrase, terms)

    def test_example_captions_match_original_design_with_secret_only_redaction(self):
        source = self.render('guide.html')
        self.assertIn('طرح اصلی پاکت', source)
        self.assertIn('همهٔ دوازده کلمه و کد بازیابی پوشانده شده‌اند', source)
        self.assertIn('آدرس و کدهای عمومی واقعی', source)
        self.assertIn('به آدرس این تصویر پول واریز نکنید', source)
        self.assertNotIn('آدرس، شمارهٔ سریال و کدهای تصویری حذف شده‌اند', source)

    def test_guide_starts_with_plain_inner_outer_and_stranger_warnings(self):
        source = self.render("guide.html")
        self.assertIn('<section id="quick-guide">', source)
        intro = source.split('<section id="quick-guide">', 1)[1].split('</section>', 1)[0]
        self.assertLess(source.index('id="quick-guide"'), source.index('id="two-things"'))
        for phrase in ("دوازده کلمه", "دوربین مداربسته", "خالی کند", "شماره حساب", "مخدوش",
                       "کلمات سالم", "استعلام سریال", "از غریبه پاکت نخرید", "جعل", "کیف پول دیگری",
                       "اگر متخصص نیستید", "در این سایت وارد نکنید"):
            self.assertIn(phrase, intro)
        images = [attrs for tag, attrs in Document(intro).elements if tag == "img"]
        self.assertEqual([attrs['src'] for attrs in images],
                         ['/static/guide-inner-example.png', '/static/guide-outer-example.png'])
        for attrs in images:
            self.assertTrue(attrs.get('alt'))
            self.assertTrue(attrs.get('width') and attrs.get('height'))
        self.assertNotIn('/static/privatekey.png', source)
        self.assertNotIn('/static/publickey.png', source)
        self.assertIn('https://btc4.fun/s/SERIAL', intro)
        self.assertIn('https://go.btc4.fun/SERIAL', intro)
        self.assertIn('نمونهٔ آموزشی', intro)

    def test_adult_guide_explains_safe_full_balance_handover(self):
        source = self.render("guide.html")
        document = Document(source)
        self.assertEqual(sum(tag == "h1" for tag, _ in document.elements), 1)
        for phrase in ("۱۲ یا ۲۴ کلمهٔ انگلیسی", "BIP39", "BIP84", "m/84'/0'/0'/0/0",
                       "بدون عبارت عبور", "آفلاین", "برنامهٔ معتبر", "تمام موجودی",
                       "کیف پول تازه", "شبکهٔ اصلی بیت‌کوین", "تأییدنشده", "کپی"):
            self.assertIn(phrase, source)
        self.assertRegex(source, r'<(?:code|p)[^>]*dir="ltr"[^>]*>m/84&#39;/0&#39;/0&#39;/0/0</(?:code|p)>|<(?:code|p)[^>]*dir="ltr"[^>]*>m/84\'/0\'/0\'/0/0</(?:code|p)>')
        self.assertIn("هرگز کلمات بازیابی را در این سایت", source)
        self.assertNotRegex(source, r'<(?:input|textarea)')
        self.assertIn('href="/lookup"', source)
        self.assertIn('href="/terms"', source)

    def test_age_seven_guide_is_supervised_learning_not_buying(self):
        source = self.render("kids.html")
        self.assertEqual(sum(tag == "h1" for tag, _ in Document(source).elements), 1)
        for phrase in ("یک بزرگ‌تر", "صندوق پست", "آدرس عمومی", "کلمات بازیابی", "کلید", "خرید", "سرمایه‌گذاری", "نفرست"):
            self.assertIn(phrase, source)
        self.assertIn('href="/guide"', source)
        self.assertNotRegex(source, r'<(?:input|textarea)')

    def test_terms_preserve_payment_risks_legal_rights_and_source_license(self):
        source = self.render("terms.html")
        self.assertEqual(sum(tag == "h1" for tag, _ in Document(source).elements), 1)
        for phrase in ("سرگرمی", "سرمایه‌گذاری", "ثروتمند", "شبکه", "آدرس", "هنگام تحویل",
                       "تأییدنشده", "حذف", "جایگزین", "کارمزد بسیار کم", "روزها یا بیشتر",
                       "رطوبت", "پشتیبان", "هیچ‌کس", "نگهداری", "پشتیبانی فنی مداوم",
                       "تضمین سود", "حقوق آمره", "غیرتجاری", "اجازهٔ قبلی نویسنده", "OSI"):
            self.assertIn(phrase, source)
        self.assertNotIn("سختی پایین شبکه", source)
        self.assertNotIn("متن‌باز", source)

    def test_lookup_form_has_safe_progressive_enhancement_contract(self):
        source = self.render("lookup.html")
        document = Document(source)
        form = document.by_id("lookup-form")
        self.assertEqual(form["action"], "/lookup")
        self.assertEqual(form["method"].lower(), "get")
        self.assertEqual(form["data-initial-serial"], "")
        field = document.by_id("serial")
        self.assertEqual(field["name"], "serial")
        self.assertEqual(field["dir"], "ltr")
        self.assertIn("required", field)
        self.assertEqual(document.by_id("lookup-status")["aria-live"], "polite")
        self.assertEqual(document.by_id("lookup-status")["aria-atomic"], "true")
        self.assertIn("hidden", document.by_id("lookup-result"))
        self.assertIn("<noscript>", source)
        self.assertIn("فقط شمارهٔ سریال", source)
        self.assertIn("سه پیوند اختیاری", source)
        self.assertIn("مرورگر هیچ درخواست خودکاری", source)
        self.assertNotRegex(source, r'<(?:img|iframe)[^>]+src="https?://')
        dangerous = '\"><img src=x onerror=alert(1)>'
        initial = Document(self.render("lookup.html", serial=dangerous))
        self.assertEqual(initial.by_id("serial")["value"], dangerous)
        self.assertEqual([attrs['src'] for tag, attrs in initial.elements if tag == 'img'],
                         ['/static/guide-inner-example.png', '/static/guide-outer-example.png'])
        self.assertFalse(any(key.startswith("on") for _, attrs in initial.elements for key in attrs))

    def run_lookup_script(self, scenario, initial="", initial_state="", retry_after=""):
        self.assertIsNotNone(shutil.which("node"), "Node is required for the offline JavaScript behavior contract")
        harness = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this.attributes={}; this.dataset={}; this.listeners={}; this.textContent=''; this.hidden=false; this.value=''; }
  setAttribute(key, value) { this.attributes[key]=String(value); }
  getAttribute(key) { return this.attributes[key] ?? null; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children=[...nodes]; this.textContent=''; }
  focus() { this.focused=true; }
  async emit(name) { await Promise.all((this.listeners[name] || []).map(handler => handler({preventDefault(){}}))); }
}
const ids=Object.fromEntries(['lookup-form','serial','lookup-submit','lookup-status','lookup-result'].map(id=>[id,new Element()]));
ids['lookup-form'].dataset.initialSerial=process.argv[2];
ids['lookup-form'].dataset.initialState=process.argv[3];
ids['lookup-form'].dataset.retryAfter=process.argv[5];
ids['lookup-form'].dataset.initialAddress='bc1qsyntheticpublicfixture';
ids['lookup-form'].dataset.initialExplorer='https://mempool.space/address/bc1qsyntheticpublicfixture';
ids.serial.value=process.argv[2];
ids.serial.setAttribute('pattern', process.argv[4]);
ids['lookup-result'].hidden=true;
global.document={getElementById:id=>ids[id] || null, createElement:tag=>new Element(tag)};
global.window={isSecureContext:true, location:{origin:'http://localhost'}};
let handler=async()=>{throw new Error('Unexpected request');};
const requests=[];
global.fetch=async(url, options)=>{requests.push({url,options}); return handler(url,options);};
Object.defineProperty(global,'navigator',{value:{}, configurable:true});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const all=()=>{const found=[]; const walk=node=>{found.push(node);node.children.forEach(walk);}; walk(ids['lookup-result']); return found;};
const submit=async serial=>{ids.serial.value=serial; await ids['lookup-form'].emit('submit'); await tick();};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
'''
        # Use the rendered production field, not a copied JS grammar.
        import importlib.util
        import sys
        sys.path.insert(0, str(ROOT))
        spec = importlib.util.spec_from_file_location('ui_serial_app', ROOT / 'app.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        html = module.create_app({'TESTING': True}).test_client().get('/lookup').text
        pattern = Document(html).by_id('serial')['pattern']
        result = subprocess.run(["node", "-e", harness + "\n(async()=>{\n" + scenario + "\n})().catch(error=>{console.error(error); process.exitCode=1;});", str(ROOT / "static/site.js"), initial, initial_state, pattern, retry_after], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lookup_waits_for_intent_and_rejects_invalid_without_network(self):
        self.run_lookup_script(r'''
await tick();
assert.equal(requests.length,0,'An idle lookup must make no request');
await submit('not a serial');
assert.equal(requests.length,0,'Invalid input must not leave the browser');
assert.equal(ids.serial.getAttribute('aria-invalid'),'true');
assert.equal(ids['lookup-status'].dataset.state,'error');
assert.match(ids['lookup-status'].textContent,/شمارهٔ سریال/);
assert.equal(ids['lookup-result'].hidden,true);
''')

    def test_lookup_fetches_only_same_origin_and_renders_public_result_safely(self):
        self.run_lookup_script(r'''
let finish;
handler=()=>new Promise(resolve=>{finish=resolve;});
ids.serial.value='Demo_7-20587k45300';
const pending=ids['lookup-form'].emit('submit');
await tick();
assert.equal(requests.length,1,'Submitting a valid serial must call the public API');
assert.equal(requests[0].url,'/api/wallets/Demo_7-20587k45300');
assert.equal(requests[0].options.credentials,'same-origin');
assert.equal(requests[0].options.redirect,'error');
assert.equal(ids['lookup-status'].dataset.state,'loading');
assert.equal(ids['lookup-result'].getAttribute('aria-busy'),'true');
const address='bc1qsyntheticpublicfixture';
finish({ok:true,status:200,json:async()=>({serial:'Demo_7-20587k45300',address,explorer_url:'https://mempool.space/address/'+address})});
await pending;
await tick();
assert.equal(ids['lookup-result'].hidden,false);
assert.equal(ids['lookup-result'].getAttribute('aria-busy'),'false');
assert.equal(ids['lookup-status'].dataset.state,'success');
assert.ok(all().some(node=>node.textContent==='Demo_7-20587k45300' && node.dir==='ltr'));
assert.ok(all().some(node=>node.textContent===address && node.dir==='ltr'));
const image=all().find(node=>node.tagName==='img');
assert.equal(image.src,'/api/wallets/Demo_7-20587k45300/qr.svg');
assert.ok(image.alt.length>8);
const link=all().find(node=>node.tagName==='a');
assert.equal(link.href,'https://mempool.space/address/'+address);
assert.equal(link.target,'_blank');
assert.equal(link.rel,'noopener noreferrer');
const explorers=all().filter(node=>node.tagName==='a');
assert.deepEqual(explorers.map(node=>node.href),[
  'https://mempool.space/address/'+address,
  'https://blockstream.info/address/'+address,
  'https://www.blockchain.com/explorer/addresses/btc/'+address
]);
for (const explorer of explorers) {
  assert.equal(explorer.target,'_blank');
  assert.equal(explorer.rel,'noopener noreferrer');
}
assert.equal(requests.length,1,'Explorer must not be prefetched');
''')

    def test_lookup_distinguishes_not_found_invalid_and_unavailable(self):
        self.run_lookup_script(r'''
for (const [code,pattern] of [[404,/پیدا نشد/],[400,/معتبر نیست/],[503,/دسترس نیست/]]) {
  handler=async()=>({ok:false,status:code});
  await submit('Sample70587k45300');
  assert.equal(ids['lookup-status'].dataset.state,'error');
  assert.match(ids['lookup-status'].textContent,pattern);
  assert.equal(ids['lookup-result'].hidden,true);
  assert.equal(ids['lookup-submit'].disabled,false);
}
handler=async()=>{throw new TypeError('Network unavailable');};
await submit('Sample70587k45300');
assert.match(ids['lookup-status'].textContent,/دسترس نیست/);
assert.equal(ids['lookup-result'].hidden,true);
''')

    def test_explicit_serial_page_starts_exactly_one_lookup(self):
        self.run_lookup_script(r'''
await tick();
assert.equal(requests.length,1,'An explicit serial page should start one lookup');
assert.equal(requests[0].url,'/api/wallets/Serial_710587k45300');
assert.equal(ids['lookup-submit'].disabled,false);
''', initial="Serial_710587k45300")

    def test_server_rendered_lookup_is_hydrated_without_duplicate_admission(self):
        self.run_lookup_script(r'''
await tick();
assert.equal(requests.length,0,'Server already looked up the initial serial');
assert.equal(ids['lookup-result'].hidden,false);
assert.equal(ids['lookup-status'].dataset.state,'success');
assert.ok(all().some(node=>node.textContent==='Serial_710587k45300'));
''', initial='Serial_710587k45300', initial_state='found')
        self.run_lookup_script(r'''
await tick();
assert.equal(requests.length,0,'Do not retry an initial limited lookup');
assert.match(ids['lookup-status'].textContent,/پنج استعلام در شصت ثانیه/);
assert.equal(ids['lookup-result'].hidden,true);
assert.match(ids['lookup-status'].textContent,/۴۳ ثانیه/);
''', initial='Serial_710587k45300', initial_state='rate_limited', retry_after='43')

    def test_lookup_explains_server_rate_limit_without_automatic_retry(self):
        self.run_lookup_script(r'''
handler=async()=>({ok:false,status:429,headers:{get:name=>name==='Retry-After'?'37':null}});
await submit('Sample70587k45300');
assert.match(ids['lookup-status'].textContent,/۳۷ ثانیه/);
assert.match(ids['lookup-status'].textContent,/پنج استعلام در شصت ثانیه/);
assert.equal(requests.length,1);
assert.equal(ids['lookup-result'].hidden,true);
assert.equal(ids['lookup-submit'].disabled,false);
''')

    def test_rate_wait_header_is_bounded_and_never_rendered_as_markup(self):
        self.run_lookup_script(r'''
for (const value of [null, '', '0', '61', '-1', '1.5', 'NaN', '<img src=x>', '9'.repeat(10000)]) {
  handler=async()=>({ok:false,status:429,headers:{get:()=>value}});
  await submit('Sample70587k45300');
  assert.match(ids['lookup-status'].textContent,/کمی صبر کنید/);
  assert.ok(!ids['lookup-status'].textContent.includes('<img'));
}
assert.equal(requests.length,9);
''')

    def test_lookup_rejects_untrusted_payloads_without_rendering_or_external_urls(self):
        self.run_lookup_script(r'''
const address='bc1q'+'q'.repeat(38);
for (const payload of [
  {serial:'OtherSerial',address,explorer_url:'https://mempool.space/address/'+address},
  {serial:'Safe70587k45300',address:'<img src=x onerror=alert(1)>',explorer_url:'https://mempool.space/'},
  {serial:'Safe70587k45300',address,explorer_url:'javascript:alert(1)'},
  {serial:'Safe70587k45300',address,explorer_url:'https://evil.example/address/'+address},
  null
]) {
  handler=async()=>({ok:true,status:200,json:async()=>payload});
  await submit('Safe70587k45300');
  assert.equal(ids['lookup-result'].hidden,true,'Malformed public data must not be displayed');
  assert.equal(all().filter(node=>['a','img'].includes(node.tagName)).length,0);
  assert.equal(ids['lookup-status'].dataset.state,'error');
}
const source=fs.readFileSync(process.argv[1],'utf8');
assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|eval\(/.test(source),'Untrusted results require safe DOM construction');
''')

    def test_copy_address_handles_unsupported_denied_and_successful_clipboard(self):
        self.run_lookup_script(r'''
const address='bc1q'+'q'.repeat(38);
handler=async()=>({ok:true,status:200,json:async()=>({serial:'Copy70587k45300',address,explorer_url:'https://mempool.space/address/'+address})});
await submit('Copy70587k45300');
const copy=all().find(node=>node.tagName==='button');
assert.ok(copy,'Provide a copy-address control');
await copy.emit('click');
assert.match(ids['lookup-status'].textContent,/دستی/);
navigator.clipboard={writeText:async()=>{throw new Error('Clipboard permission denied');}};
await copy.emit('click');
assert.match(ids['lookup-status'].textContent,/دستی/);
let copied;
navigator.clipboard={writeText:async value=>{copied=value;}};
await copy.emit('click');
assert.equal(copied,address);
assert.match(ids['lookup-status'].textContent,/کپی شد/);
assert.equal(requests.length,1,'Clipboard must not trigger a request');
''')

    def test_latest_serial_wins_when_requests_resolve_out_of_order(self):
        self.run_lookup_script(r'''
const pending=[];
handler=()=>new Promise(resolve=>pending.push(resolve));
const response=serial=>({ok:true,status:200,json:async()=>({serial,address:'bc1q'+'q'.repeat(38),explorer_url:'https://mempool.space/address/bc1q'+'q'.repeat(38)})});
ids.serial.value='First0587k45300';
const first=ids['lookup-form'].emit('submit');
ids.serial.value='Second0587k45300';
const second=ids['lookup-form'].emit('submit');
pending[1](response('Second0587k45300'));
await second;
assert.ok(all().some(node=>node.textContent==='Second0587k45300'));
pending[0](response('First0587k45300'));
await first;
assert.ok(all().some(node=>node.textContent==='Second0587k45300'),'An earlier response must not replace the latest serial');
assert.ok(!all().some(node=>node.textContent==='First0587k45300'));
''')

    def test_failed_local_qr_keeps_public_address_readable(self):
        self.run_lookup_script(r'''
const address='bc1q'+'q'.repeat(38);
handler=async()=>({ok:true,status:200,json:async()=>({serial:'Qr70587k45300',address,explorer_url:'https://mempool.space/address/'+address})});
await submit('Qr70587k45300');
const qr=all().find(node=>node.tagName==='img');
await qr.emit('error');
assert.equal(qr.hidden,true,'Hide a broken QR image');
assert.ok(all().some(node=>/کد تصویری.*در دسترس نیست/.test(node.textContent)));
assert.ok(all().some(node=>node.textContent===address));
assert.equal(ids['lookup-result'].hidden,false);
assert.equal(requests.length,1);
''')

    def test_native_invalid_input_announces_an_accessible_error(self):
        self.run_lookup_script(r'''
ids.serial.value='contains spaces';
await ids.serial.emit('invalid');
assert.equal(requests.length,0);
assert.equal(ids.serial.getAttribute('aria-invalid'),'true');
assert.match(ids['lookup-status'].textContent,/شمارهٔ سریال/);
assert.equal(ids['lookup-status'].dataset.state,'error');
''')

    def test_nojavascript_lookup_derives_three_opt_in_explorer_links_from_address(self):
        address = "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"
        source = self.render("lookup.html", wallet={"serial": "Demo7", "address": address,
                                                   "explorer_url": "https://evil.example/not-used"})
        document = Document(source)
        expected = {
            "https://mempool.space/address/" + address,
            "https://blockstream.info/address/" + address,
            "https://www.blockchain.com/explorer/addresses/btc/" + address,
        }
        found = {attrs.get("href") for tag, attrs in document.elements if tag == "a"}
        self.assertTrue(expected <= found)
        self.assertNotIn("https://evil.example/not-used", source)
        self.assertIn("<noscript>", source)
        for tag, attrs in document.elements:
            if tag == "a" and attrs.get("href") in expected:
                self.assertEqual(attrs.get("target"), "_blank")
                self.assertEqual(attrs.get("rel"), "noopener noreferrer")

    def test_terms_explain_internet_outages_and_server_market_requests_honestly(self):
        source = self.render("terms.html")
        for phrase in ("قطع اینترنت", "هیچ‌کس", "پیگیری", "ناپدید", "مرورگر", "سرور", "احراز هویت", "کارمزد عمومی"):
            self.assertIn(phrase, source)
        self.assertNotIn("به سرویس خارجی درخواست خودکار نمی‌فرستد", source)

    def test_all_pages_keep_strict_csp_safe_origin_and_hidden_contracts(self):
        for name in ("index.html", "guide.html", "kids.html", "terms.html", "lookup.html", "satoshi.html", "costs.html", "contact.html"):
            with self.subTest(page=name):
                source = self.render(name)
                document = Document(source)
                self.assertIn(("html", {"lang": "fa", "dir": "rtl"}), document.elements)
                self.assertEqual(sum(tag == "h1" for tag, _ in document.elements), 1)
                self.assertFalse(any(tag in ("iframe", "object", "embed", "style") for tag, _ in document.elements))
                for tag, attrs in document.elements:
                    self.assertFalse(any(key.startswith("on") or key == "style" for key in attrs))
                    if "src" in attrs:
                        self.assertTrue(attrs["src"].startswith("/static/"))
                    if tag == "link":
                        self.assertEqual(attrs["rel"], "stylesheet")
                        self.assertEqual(attrs["href"], "/static/site.css")
                    if tag == "a" and attrs.get("href", "").startswith("https://"):
                        self.assertEqual(attrs.get("target"), "_blank")
                        self.assertEqual(attrs.get("rel"), "noopener noreferrer")
                for script in re.findall(r"<script[^>]*>(.*?)</script>", source, re.S):
                    self.assertFalse(script.strip())
        css = (ROOT / "static/site.css").read_text()
        self.assertRegex(css, r'\[hidden\]\s*\{\s*display\s*:\s*none\s*!important\s*;?\s*\}',
                         "Author display rules must not expose hidden results or failed QR images")

    def test_invalid_serial_boundaries_are_never_normalized_or_requested(self):
        self.run_lookup_script(r'''
for (const serial of ['','-first','_first',' leading','trailing ','a/b','a%2fb','فارسی','7'.repeat(65),'abc\n','abc\r']) {
  await submit(serial);
  assert.equal(requests.length,0,'Reject malformed source token exactly: '+JSON.stringify(serial));
  assert.equal(ids['lookup-status'].dataset.state,'error');
}
''')


if __name__ == "__main__":
    unittest.main()

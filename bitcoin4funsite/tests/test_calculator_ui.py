"""Offline template and executable JavaScript contracts for the public calculators."""
from pathlib import Path
import shutil
import subprocess
import unittest

from jinja2 import Environment, FileSystemLoader, select_autoescape
from test_ui_contract import Document

ROOT = Path(__file__).resolve().parents[1]


class CalculatorUI(unittest.TestCase):
    def render(self, template_name, **context):
        env = Environment(loader=FileSystemLoader(ROOT / "templates"),
                          autoescape=select_autoescape(["html"]))
        self.assertTrue((ROOT / "templates" / template_name).is_file(), f"Missing public page: {template_name}")
        return env.get_template(template_name).render(**context)

    def test_satoshi_explainer_has_accessible_offline_bidirectional_converter(self):
        source = self.render("satoshi.html")
        document = Document(source)
        for phrase in ("۱۰۰٬۰۰۰٬۰۰۰", "ساتوشی", "آفلاین", "ارقام انگلیسی", "هشت", "۲۱ میلیون", "خودکار"):
            self.assertIn(phrase, source)
        for name in ("btc-amount", "satoshi-amount"):
            field = document.by_id(name)
            self.assertEqual(field["dir"], "ltr")
            self.assertEqual(field["type"], "text")
            self.assertIn("converter-help", field["aria-describedby"])
            self.assertIn(("label", {"for": name}), document.elements)
        self.assertEqual(document.by_id("converter-status")["aria-live"], "polite")
        self.assertIn('src="/static/calculator.js" defer', source)
        self.assertIn("<noscript>", source)

    def test_converter_uses_exact_integer_arithmetic_and_never_fetches(self):
        self.run_script(r'''
load();
for (const [btc,sats] of [['0.00000001','1'],['0.1','10000000'],['1.23456789','123456789'],['20999999.99999999','2099999999999999'],['21000000','2100000000000000'],['0','0']]) {
  await edit('btc-amount',btc);
  assert.equal(ids['satoshi-amount'].value,sats);
  assert.equal(ids['converter-status'].dataset.state,'success');
  await edit('satoshi-amount',sats);
  assert.equal(ids['btc-amount'].value,btc);
}
await edit('btc-amount','1.23000000');
assert.equal(ids['satoshi-amount'].value,'123000000');
await edit('satoshi-amount','123000000');
assert.equal(ids['btc-amount'].value,'1.23');
assert.equal(requests.length,0,'Conversion must work completely offline');
''')

    def test_converter_rejects_invalid_values_without_rounding_or_stale_output(self):
        self.run_script(r'''
load();
for (const [id,other,bad] of [
 ['btc-amount','satoshi-amount',['-1','+1','1e-8','0.000000001','1,000','۱',' 1','1 ','1\n','1\r','.1','1.','01','21000000.00000001']],
 ['satoshi-amount','btc-amount',['-1','+1','1.0','1e2','1,000','۱',' 1','1 ','1\n','1\r','01','2100000000000001','9'.repeat(1000)]]
]) {
  for (const value of bad) {
    await edit(id,'1');
    await edit(id,value);
    assert.equal(ids[other].value,'','Invalid input must clear the old answer: '+JSON.stringify(value));
    assert.equal(ids[id].getAttribute('aria-invalid'),'true');
    assert.equal(ids['converter-status'].dataset.state,'error');
  }
  await edit(id,'');
  assert.equal(ids[other].value,'');
  assert.equal(ids[id].getAttribute('aria-invalid'),null);
}
assert.equal(requests.length,0);
''')

    def test_costs_page_discloses_formula_sources_cache_and_network_uncertainty(self):
        source = self.render("costs.html")
        document = Document(source)
        for phrase in ("۵۰۰", "حداقل بسته", "حداقل همگانی", "۰٫۵", "۱۵", "۰٫۱۵", "۱۴۱", "یک ورودی", "دو خروجی", "سگویت", "اقتصادی", "روزها", "حذف", "تضمین", "۶۰ ثانیه", "۳۰۰ ثانیه", "ریال", "باقی‌مانده", "سرور"):
            self.assertIn(phrase, source)
        self.assertNotIn("BlueWallet", source)
        for name in ("market-stale", "market-data"):
            self.assertIn("hidden", document.by_id(name))
        self.assertEqual(document.by_id("market-status")["aria-live"], "polite")
        self.assertIn('id="quote-rows"', source)
        self.assertIn("<noscript>", source)
        self.assertIn("/static/calculator.js", source)
        self.assertIn("https://swapwallet.app/api/v1/market/prices", source)
        self.assertIn("https://mempool.space/api/v1/fees/recommended", source)
        home = self.render("index.html")
        self.assertIn('href="/costs"', home)

    def test_market_fetches_once_same_origin_and_renders_a_transparent_quote(self):
        self.run_script(r'''
handler=async()=>({ok:true,status:200,json:async()=>marketFixture()});
load();
await tick();
assert.equal(requests.length,1);
assert.equal(requests[0].url,'/api/market');
assert.equal(requests[0].options.credentials,'same-origin');
assert.equal(requests[0].options.redirect,'error');
assert.equal(ids['market-status'].dataset.state,'success');
assert.equal(ids['market-data'].hidden,false);
assert.equal(ids['market-stale'].hidden,true);
assert.equal(ids['market-fetched-at'].textContent,'2026-10-30T10:00:00+00:00');
assert.equal(ids['btc-price'].textContent,'10,000,000,000');
assert.equal(ids['usdt-price'].textContent,'100,000');
assert.equal(ids['sat-price'].textContent,'100');
assert.equal(ids['quote-rows'].children.length,2);
const first=ids['quote-rows'].children[0];
assert.equal(first.children.length,3,'Keep the three primary columns');
assert.ok(all(first).some(node=>node.textContent==='500'));
assert.ok(all(first).some(node=>node.textContent==='0.00000500'));
assert.ok(all(first).some(node=>node.textContent==='91,000'));
assert.ok(all(first).some(node=>node.tagName==='details'));
const detailText=all(first).map(node=>node.textContent).join(' ');
for (const word of ['شبکه','چاپ','گرداننده','ریال','910,000','119','150','141']) assert.ok(detailText.includes(word),word);
const secondText=all(ids['quote-rows'].children[1]).map(node=>node.textContent).join(' ');
assert.match(secondText,/باقی‌مانده/);
assert.ok(secondText.includes('51,500'));
assert.equal(all(ids['market-data']).filter(node=>['img','iframe','a'].includes(node.tagName)).length,0);
await tick();
assert.equal(requests.length,1,'No external requests or automatic polling');
''', page="market")

    def test_market_stale_and_unavailable_never_present_a_fabricated_price(self):
        for mode in ("stale", "http503", "offline", "invalid"):
            with self.subTest(mode=mode):
                self.run_script("const mode=" + repr(mode) + r''';
handler=async()=>{
  if(mode==='offline') throw new Error('Offline');
  if(mode==='http503') return {ok:false,status:503,json:async()=>{throw new Error('Do not parse errors');}};
  const payload=marketFixture();
  if(mode==='stale') payload.status='stale';
  if(mode==='invalid') payload.rates.btc_toman='0';
  return {ok:true,status:200,json:async()=>payload};
};
load(); await tick();
assert.equal(requests.length,1);
assert.equal(ids['market-panel'].getAttribute('aria-busy'),'false');
if(mode==='stale') {
  assert.equal(ids['market-stale'].hidden,false);
  assert.equal(ids['market-data'].hidden,false);
  assert.equal(ids['market-status'].dataset.state,'stale');
  assert.match(ids['market-status'].textContent,/قدیمی/);
} else {
  assert.equal(ids['market-data'].hidden,true);
  assert.equal(ids['market-stale'].hidden,true);
  assert.equal(ids['quote-rows'].children.length,0);
  assert.equal(ids['btc-price'].textContent,'');
  assert.equal(ids['market-status'].dataset.state,'error');
  assert.match(ids['market-status'].textContent,/دسترس نیست/);
}
''', page="market")

    def test_market_rejects_untrusted_or_inconsistent_data_before_rendering(self):
        self.run_script(r'''
const invalid=[
  x=>x.status='unknown', x=>x.fetched_at='<img src=x>',
  x=>x.source.prices='https://evil.example/',
  x=>x.rates.btc_toman='<img src=x onerror=alert(1)>',
  x=>x.rates.usdt_toman='0', x=>x.rates.satoshi_toman='NaN',
  x=>x.assumptions.operator_fee_percent='0', x=>x.rows=[],
  x=>x.rows[0].btc='0.1', x=>x.rows[0].total_rial=1,
  x=>x.rows[0].network_sats=-1, x=>x.rows[0].total_sats=0,
  x=>x.rows[1].total_toman=200001,
  x=>x.rows[1].remainder_toman=123
];
for(const change of invalid) {
  const payload=marketFixture(); change(payload);
  handler=async()=>({ok:true,status:200,json:async()=>payload});
  load(); await tick();
  assert.equal(ids['market-data'].hidden,true);
  assert.equal(ids['quote-rows'].children.length,0);
  assert.equal(ids['market-status'].dataset.state,'error');
}
const source=fs.readFileSync(process.argv[1],'utf8');
assert.ok(!/innerHTML|outerHTML|insertAdjacentHTML|eval\(/.test(source));
''', page="market")

    def test_other_pages_never_fetch_market_data(self):
        self.run_script("load(); await tick(); assert.equal(requests.length,0);", page="other")

    def test_contact_keeps_email_and_forbids_private_material_without_uploads(self):
        source = self.render("contact.html", contact_token="synthetic-token")
        document = Document(source)
        self.assertIn('href="mailto:09113458375@btc4.fun"', source)
        self.assertIn('dir="ltr">09113458375@btc4.fun', source)
        for phrase in ("کلمات بازیابی", "کلید خصوصی", "نفرستید", "پرسش عمومی", "پشتیبانی فنی مداوم"):
            self.assertIn(phrase, source)
        self.assertFalse(any(tag == "input" and attrs.get("type") == "file"
                             for tag, attrs in document.elements))
        self.assertNotIn("multipart/form-data", source)
        self.assertNotIn("calculator.js", source)

    def test_contact_form_posts_native_bounded_fields_with_csrf_and_honeypot(self):
        token = '\"><img src=x onerror=alert(1)>'
        source = self.render("contact.html", contact_token=token)
        document = Document(source)
        forms = [attrs for tag, attrs in document.elements if tag == "form"]
        self.assertEqual(len(forms), 1, "Provide one native contact form")
        self.assertEqual(forms[0]["method"].lower(), "post")
        self.assertEqual(forms[0]["action"], "/contact")
        self.assertNotIn("novalidate", forms[0])
        self.assertNotIn("onsubmit", forms[0])
        controls = {attrs["name"]: (tag, attrs) for tag, attrs in document.elements
                    if tag in ("input", "textarea") and "name" in attrs}
        self.assertEqual(set(controls), {"name", "mobile", "message", "csrf_token", "website"})
        for name, expected_tag, limit in (("name", "input", "80"),
                                          ("mobile", "input", "32"),
                                          ("message", "textarea", "2000")):
            tag, field = controls[name]
            self.assertEqual(tag, expected_tag)
            self.assertEqual(field["maxlength"], limit)
            if name == "mobile":
                self.assertNotIn("required", field, "A phone number is optional for a general question")
            else:
                self.assertIn("required", field)
            self.assertTrue(any(tag == "label" and attrs.get("for") == field["id"]
                                for tag, attrs in document.elements))
            for hint in field["aria-describedby"].split():
                self.assertTrue(document.by_id(hint), "Hints must reference existing text")
            self.assertFalse(field.get("value"))
        self.assertEqual(controls["name"][1]["autocomplete"], "name")
        self.assertEqual(controls["mobile"][1]["type"], "tel")
        self.assertEqual(controls["mobile"][1]["dir"], "ltr")
        self.assertEqual(controls["mobile"][1]["autocomplete"], "tel")
        self.assertEqual(controls["csrf_token"][1]["type"], "hidden")
        self.assertEqual(controls["csrf_token"][1]["value"], token)
        self.assertIn("hidden", document.by_id("contact-honeypot"))
        self.assertEqual(controls["website"][1]["tabindex"], "-1")
        self.assertEqual(controls["website"][1]["autocomplete"], "off")
        self.assertFalse(any(tag == "img" or any(key.startswith("on") for key in attrs)
                             for tag, attrs in document.elements))
        self.assertTrue(any(tag == "button" and attrs.get("type") == "submit"
                            for tag, attrs in document.elements))

    def test_contact_feedback_is_accessible_escaped_and_never_echoes_submitted_text(self):
        private_fields = {"name": "SYNTHETIC_PRIVATE_NAME", "mobile": "SYNTHETIC_PRIVATE_MOBILE",
                          "message": "SYNTHETIC_PRIVATE_MESSAGE"}
        for sent, error, role in ((False, "", None), (True, "", "status"),
                                  (False, "ارسال پیام ممکن نشد؛ دوباره تلاش کنید.", "alert"),
                                  (False, '<img src=x onerror=alert(1)>', "alert")):
            with self.subTest(sent=sent, error=error):
                source = self.render("contact.html", contact_token="synthetic-token",
                                     contact_sent=sent, contact_error=error, **private_fields)
                document = Document(source)
                feedback = [attrs for _, attrs in document.elements if attrs.get("id") == "contact-status"]
                if role is None:
                    self.assertEqual(feedback, [])
                else:
                    self.assertEqual(len(feedback), 1)
                    self.assertEqual(feedback[0]["role"], role)
                    self.assertEqual(feedback[0]["aria-atomic"], "true")
                    self.assertEqual(feedback[0]["aria-live"], "polite" if sent else "assertive")
                    self.assertNotIn("hidden", feedback[0])
                    if sent:
                        self.assertIn("پیام شما ارسال شد", source)
                    elif error.startswith("ارسال"):
                        self.assertIn(error, source)
                for secret in private_fields.values():
                    self.assertNotIn(secret, source)
                self.assertFalse(any(tag == "img" or any(key.startswith("on") for key in attrs)
                                     for tag, attrs in document.elements))

    def test_contact_without_a_token_disables_submission_and_offers_email_and_reload(self):
        for token in (None, ""):
            with self.subTest(token=token):
                source = self.render("contact.html", contact_token=token,
                                     contact_error="فرم فعلاً در دسترس نیست؛ از ایمیل استفاده کنید.")
                document = Document(source)
                self.assertTrue(any(tag == "fieldset" and attrs.get("id") == "contact-fields"
                                    for tag, attrs in document.elements), "Group editable controls in a fieldset")
                self.assertIn("disabled", document.by_id("contact-fields"))
                self.assertIn('name="name"', source)
                self.assertIn('name="mobile"', source)
                self.assertIn('name="message"', source)
                csrf = next(attrs for tag, attrs in document.elements
                            if tag == "input" and attrs.get("name") == "csrf_token")
                self.assertEqual(csrf["value"], "")
                self.assertEqual(document.by_id("contact-status")["role"], "alert")
                self.assertIn('href="mailto:09113458375@btc4.fun"', source)
                self.assertEqual(document.by_id("contact-retry")["href"], "/contact")
                self.assertIn("بارگیری دوبارهٔ فرم", source)
        active = Document(self.render("contact.html", contact_token="synthetic-token"))
        self.assertTrue(any(tag == "fieldset" and attrs.get("id") == "contact-fields"
                            for tag, attrs in active.elements), "Group editable controls in a fieldset")
        self.assertNotIn("disabled", active.by_id("contact-fields"))

    def test_contact_explains_the_additional_utf8_message_limit(self):
        source = self.render("contact.html", contact_token="synthetic-token")
        for phrase in ("چهار کیبی‌بایت", "پیام‌های فارسی ممکن است زودتر به سقف حجم برسند", "کوتاه بنویسید"):
            self.assertTrue(phrase in source, "Explain the UTF-8 transport limit in Persian")

    def test_contact_channels_are_opt_in_and_set_honest_response_expectations(self):
        source = self.render("contact.html", contact_token="synthetic-token")
        document = Document(source)
        channels = {"https://t.me/btc4_fun", "https://www.instagram.com/btc4.fun/",
                    "https://x.com/btc4_fun"}
        links = {attrs["href"]: attrs for tag, attrs in document.elements if tag == "a"}
        self.assertTrue(channels <= links.keys(), "All three social channels need opt-in links")
        for url in channels:
            self.assertEqual(links[url]["rel"], "noopener noreferrer")
            self.assertEqual(links[url]["target"], "_blank")
        for phrase in ("بیشتر به ایمیل پاسخ می‌دهم", "شاید تلگرام را هم چک کنم",
                       "کمتر پیامک می‌خوانم", "سیم‌کارت روی مودم است", "پیوست نفرستید",
                       "فقط با انتخاب شما", "جاوااسکریپت"):
            self.assertIn(phrase, source)
        self.assertFalse(any(tag in ("iframe", "object", "embed") for tag, _ in document.elements))
        for tag, attrs in document.elements:
            if "src" in attrs:
                self.assertTrue(attrs["src"].startswith("/static/"))
            if tag == "link":
                self.assertEqual(attrs.get("rel"), "stylesheet")
        self.assertNotIn("calculator.js", source)

    def test_contact_controls_and_terms_link_have_local_accessible_styles(self):
        css = (ROOT / "static/site.css").read_text()
        for selector in (".contact-form", ".contact-field", ".contact-social", ".contact-status", ".nav-terms"):
            self.assertIn(selector, css)
        self.assertRegex(css, r"\.contact-field\s+:is\(input,textarea\)\s*\{[^}]*width:100%")
        self.assertRegex(css, r"\.contact-field\s+:is\(input,textarea\)\s*\{[^}]*font:inherit")
        self.assertRegex(css, r"\.contact-field\s+textarea\s*\{[^}]*resize:vertical")
        self.assertRegex(css, r"\.contact-field\s+:is\(input,textarea\):focus-visible\s*\{[^}]*outline:")
        self.assertRegex(css, r"\.contact-social\s*\{[^}]*flex-wrap:wrap")
        self.assertRegex(css, r"\.nav-terms\s*\{[^}]*font-weight:700")
        self.assertRegex(css, r"\.contact-form fieldset\s*\{[^}]*min-width:0")
        self.assertRegex(css, r"@media\(max-width:700px\)\s*\{\.contact-form\s*\{[^}]*padding:20px")
        self.assertNotRegex(css, r"https?://|@import")

    def test_calculators_have_responsive_local_styles_and_safe_table_semantics(self):
        css = (ROOT / "static/site.css").read_text()
        for selector in (".calculator-card", ".converter-fields", ".market-section", ".rate-grid", ".quote-table", ".quote-details", ".contact-section", ".explorer-links"):
            self.assertIn(selector, css)
        self.assertRegex(css, r"\.site-header nav\s*\{[^}]*flex-wrap\s*:\s*wrap")
        self.assertIn("overflow-x:auto", css)
        self.assertRegex(css, r"@media\s*\(max-width:\s*(?:700|600|480)px\)")
        source = self.render("costs.html")
        document = Document(source)
        self.assertEqual(sum(tag == "th" and attrs.get("scope") == "col" for tag, attrs in document.elements), 3)
        self.assertTrue(any(tag == "caption" for tag, _ in document.elements))

    def test_home_calls_out_costs_without_fetching_or_embedding_rates(self):
        source = self.render("index.html")
        main = source.split('<main id="main-content"', 1)[1].split('</main>', 1)[0]
        self.assertIn('href="/costs"', main)
        self.assertIn("ریز هزینه", main)
        self.assertNotIn("market-panel", source)
        self.assertNotIn("calculator.js", source)

    def test_manual_converter_explanation_is_multiply_then_divide(self):
        source = self.render("satoshi.html")
        self.assertNotIn("هر بیت‌کوین را به صد میلیون ساتوشی تقسیم", source)
        self.assertIn("مقدار بیت‌کوین را در صد میلیون ضرب", source)
        self.assertIn("تعداد ساتوشی را بر صد میلیون تقسیم", source)

    def run_script(self, scenario, page="converter"):
        self.assertIsNotNone(shutil.which("node"), "Node is required for offline JavaScript behavior tests")
        harness = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this.attributes={}; this.dataset={}; this.listeners={}; this.textContent=''; this.hidden=false; this.value=''; }
  setAttribute(key,value) { this.attributes[key]=String(value); }
  getAttribute(key) { return this.attributes[key] ?? null; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name,handler) { (this.listeners[name] ||= []).push(handler); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=[...nodes]; this.textContent=''; }
  async emit(name) { await Promise.all((this.listeners[name] || []).map(handler=>handler({preventDefault(){}}))); }
}
const names = process.argv[2] === 'converter' ? ['satoshi-converter','btc-amount','satoshi-amount','converter-status'] :
  process.argv[2] === 'market' ? ['market-panel','market-status','market-stale','market-data','market-fetched-at','btc-price','usdt-price','sat-price','network-fee-rate','quote-rows'] : [];
const ids=Object.fromEntries(names.map(name=>[name,new Element()]));
if (ids['market-data']) ids['market-data'].hidden=true;
if (ids['market-stale']) ids['market-stale'].hidden=true;
global.document={getElementById:id=>ids[id] || null,createElement:tag=>new Element(tag)};
let handler=async()=>{throw new Error('Offline fixture: unavailable');};
const requests=[];
global.fetch=async(url,options)=>{requests.push({url,options}); return handler(url,options);};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const all=root=>{const found=[];const walk=node=>{found.push(node);node.children.forEach(walk);};walk(root);return found;};
const edit=async(id,value)=>{ids[id].value=value; await ids[id].emit('input');};
const marketFixture=()=>({status:'fresh',fetched_at:'2026-10-30T10:00:00+00:00',
  source:{prices:'https://swapwallet.app/api/v1/market/prices',fees:'https://mempool.space/api/v1/fees/recommended'},
  rates:{btc_toman:'10000000000',usdt_toman:'100000',satoshi_toman:'100'},
  assumptions:{exchange_fee_percent:'0.5',operator_fee_percent:'15',print_usd:'0.15',transaction_vbytes:141,network_fee_rate:'1'},
  costs:{network_sats:141,print_sats:150},
  rows:[{principal_sats:500,btc:'0.00000500',network_sats:141,print_sats:150,operator_sats:119,total_sats:910,total_toman:91000,total_rial:910000,budget_toman:null,remainder_toman:0},
        {principal_sats:1000,btc:'0.00001000',network_sats:141,print_sats:150,operator_sats:194,total_sats:1485,total_toman:148500,total_rial:1485000,budget_toman:200000,remainder_toman:51500}]});
const load=()=>vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
'''
        result = subprocess.run(["node", "-e", harness + "\n(async()=>{\n" + scenario + "\n})().catch(error=>{console.error(error); process.exitCode=1;});", str(ROOT / "static/calculator.js"), page], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

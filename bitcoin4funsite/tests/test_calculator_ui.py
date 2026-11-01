"""Offline template and executable JavaScript contracts for the public calculators."""
from fractions import Fraction
import json
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

    def test_converter_uses_exact_integer_arithmetic_independent_of_price_fetch(self):
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
assert.equal(requests.length,1,'Only the optional gross valuation requests a same-origin snapshot');
assert.equal(requests[0].url,'/api/market');
''')

    def test_gross_valuation_uses_raw_rate_not_adjusted_or_fees_and_fetches_once(self):
        self.run_script(r'''
const payload=marketFixture();
payload.raw_rates.btc_toman='10000000000.123456789123456789';
handler=async()=>({ok:true,json:async()=>payload});
load();
await edit('satoshi-amount','3000');
assert.equal(ids['btc-amount'].value,'0.00003','Offline conversion does not await the network');
await tick();
assert.equal(ids['gross-result'].hidden,false);
assert.equal(ids['gross-toman'].textContent,'300,000.00000370370367370370367');
assert.equal(ids['gross-raw-price'].textContent,'10,000,000,000.123456789123456789');
assert.equal(ids['gross-fetched-at'].textContent,payload.fetched_at);
assert.equal(ids['gross-status'].dataset.state,'success');
assert.equal(ids['gross-stale'].hidden,true);
await edit('btc-amount','0.00000001');
assert.equal(ids['gross-toman'].textContent,'100.00000000123456789123456789');
await edit('btc-amount','0');
assert.equal(ids['gross-toman'].textContent,'0');
await edit('satoshi-amount','2100000000000000');
assert.equal(ids['gross-toman'].textContent,'210,000,000,002,592,592.571592592569');
await edit('satoshi-amount','-1');
assert.equal(ids['gross-result'].hidden,true);
assert.equal(ids['gross-toman'].textContent,'');
await edit('btc-amount','');
assert.equal(ids['gross-toman'].textContent,'');
assert.equal(requests.length,1);
assert.equal(requests[0].url,'/api/market');
for(const [key,value] of Object.entries({method:'GET',credentials:'same-origin',redirect:'error',cache:'no-store'})) assert.equal(requests[0].options[key],value);
assert.equal(requests[0].options.body,undefined);
''')

    def test_gross_valuation_discloses_raw_online_value_separately_from_offline_units(self):
        source = self.render("satoshi.html")
        document = Document(source)
        self.assertIn("hidden", document.by_id("gross-result"))
        self.assertIn("hidden", document.by_id("gross-stale"))
        self.assertEqual(document.by_id("gross-status")["aria-live"], "polite")
        self.assertEqual(document.by_id("gross-result")["aria-live"], "polite")
        self.assertEqual(document.by_id("gross-toman")["dir"], "ltr")
        for phrase in ("ارزش خام", "تومان", "بدون کارمزد", "تبدیل", "شبکه", "چاپ", "گرداننده", "آفلاین", "یک بار", "سرور همین سایت", "خودکار تازه نمی‌شود", "ارسال نمی‌شود"):
            self.assertIn(phrase, source)
        self.assertNotRegex(source, r'<(?:script|img|iframe)[^>]+src="https?://')

    def test_gross_valuation_retains_stale_label_and_offline_conversion_survives_failures(self):
        for mode in ("stale", "offline", "http503", "badraw", "missingraw", "badtime", "badsource"):
            with self.subTest(mode=mode):
                self.run_script("const mode=" + repr(mode) + r''';
handler=async()=>{
  if(mode==='offline') throw Error('offline');
  const payload=marketFixture();
  if(mode==='stale') payload.status='stale';
  if(mode==='badraw') payload.raw_rates.btc_toman='NaN';
  if(mode==='missingraw') delete payload.raw_rates;
  if(mode==='badtime') payload.fetched_at='not a timestamp';
  if(mode==='badsource') payload.source.prices='https://evil.example/';
  return {ok:mode!=='http503',json:async()=>payload};
};
load(); await tick();
await edit('btc-amount','1.23456789');
assert.equal(ids['satoshi-amount'].value,'123456789');
assert.equal(ids['converter-status'].dataset.state,'success');
assert.equal(ids['gross-valuation'].getAttribute('aria-busy'),'false');
if(mode==='stale') {
  assert.equal(ids['gross-result'].hidden,false);
  assert.equal(ids['gross-stale'].hidden,false);
  assert.equal(ids['gross-status'].dataset.state,'stale');
  assert.match(ids['gross-status'].textContent,/قدیمی/);
} else {
  assert.equal(ids['gross-result'].hidden,true);
  assert.equal(ids['gross-toman'].textContent,'');
  assert.equal(ids['gross-raw-price'].textContent,'');
  assert.equal(ids['gross-status'].dataset.state,'error');
  assert.match(ids['gross-status'].textContent,/آفلاین/);
}
assert.equal(requests.length,1);
''')

    def test_gross_valuation_loading_and_accessible_styles_do_not_block_conversion(self):
        self.run_script(r'''
let deliver;
handler=()=>new Promise(resolve=>{deliver=resolve;}); load();
assert.equal(ids['gross-status'].dataset.state,'loading');
await edit('satoshi-amount','500');
assert.equal(ids['btc-amount'].value,'0.000005');
assert.equal(ids['gross-result'].hidden,true);
deliver({ok:false}); await tick();
assert.equal(ids['btc-amount'].value,'0.000005');
assert.equal(ids['gross-result'].hidden,true);
assert.equal(ids['gross-status'].dataset.state,'error');
''')
        css = (ROOT / "static/site.css").read_text()
        self.assertIn(".gross-result", css)
        self.assertIn(".gross-valuation", css)
        self.assertRegex(css, r"\.quote-controls\s+:is\(input,select\):focus-visible\s*\{[^}]*outline:")

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
assert.equal(requests.length,1);
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

    def test_fee_and_tag_choices_update_table_and_both_custom_modes_without_fetch(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from pricing import quote_table
        options = {speed: {variant: quote_table("12345678901.12345678", "98765.4321", fee, include_tag=tag)
                           for variant, tag in (("no_tag", False), ("with_tag", True))}
                   for speed, fee in (("economy", "1.1"), ("medium", "2.125"), ("fast", "3.25"))}
        self.run_script("const choices=" + json.dumps(options) + r''';
const payload=Object.assign(marketFixture(),choices.economy.no_tag,{quote_options:choices});
handler=async()=>({ok:true,json:async()=>payload}); load(); await tick();
assert.equal(ids['quote-speed'].value,'economy');
assert.equal(ids['quote-tag'].checked,false);
for (const speed of ['economy','medium','fast']) {
  for(const variant of ['no_tag','with_tag']) {
    const table=choices[speed][variant];
    ids['quote-speed'].value=speed; await ids['quote-speed'].emit('change');
    assert.equal(ids['quote-result'].hidden,true);
    ids['quote-tag'].checked=variant==='with_tag'; await ids['quote-tag'].emit('change');
    assert.equal(ids['quote-result'].hidden,true);
    assert.equal(ids['quote-tag-cost'].textContent.replaceAll(',',''),String(table.costs.tag_sats));
    assert.equal(ids['network-fee-rate'].textContent,table.assumptions.network_fee_rate);
    assert.equal(ids['quote-rows'].children.length,table.rows.length);
    for(const [index,row] of table.rows.entries()) {
      const displayed=all(ids['quote-rows'].children[index]).map(n=>n.textContent.replaceAll(',',''));
      assert.ok(displayed.includes(String(row.total_toman)));
      assert.ok(displayed.includes(String(row.tag_sats)));
      ids['quote-mode'].value=row.budget_toman===null?'principal_sats':'budget_toman';
      await ids['quote-mode'].emit('change');
      await edit('quote-amount',String(row.budget_toman??row.principal_sats));
      await ids['quote-form'].emit('submit');
      assert.equal(ids['quote-result'].hidden,false,JSON.stringify({speed,variant,row}));
      for(const [key,field] of Object.entries({principal_sats:'principal',network_sats:'network',print_sats:'print',tag_sats:'tag-cost-result',operator_sats:'operator',total_toman:'total-toman',total_sats:'total-sats',total_rial:'total-rial'})) {
        assert.equal(ids['quote-'+field].textContent.replaceAll(',',''),String(row[key]),speed+variant+key);
      }
    }
  }
}
assert.equal(requests.length,1);
assert.equal(requests[0].url,'/api/market');
assert.equal(requests[0].options.body,undefined);
''', page="market")

    def test_selected_tag_budget_boundaries_match_independent_fraction_inverse(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from pricing import quote_table
        maximum = 2100000000000000
        cases = []
        ceiling = lambda x: -(-x.numerator // x.denominator)
        for btc, usdt, fee in [('12345678901.12345678', '98765.4321', '2.125'),
                               ('0.000000000000000001', '0.000000000000000001', '0.000000000000000001')]:
            sat = Fraction(btc) * Fraction(201, 200) / 100000000
            network = ceiling(Fraction(fee) * 141)
            printing = ceiling(Fraction(15, 100) * Fraction(usdt) * Fraction(201, 200) / sat)
            tag = ceiling(Fraction(12, 100) * Fraction(usdt) * Fraction(201, 200) / sat)
            minimum = ceiling(ceiling(Fraction(23, 20) * (500 + network + printing + tag)) * sat)
            options = {variant: quote_table(btc, usdt, fee, include_tag=enabled)
                       for variant, enabled in [('no_tag', False), ('with_tag', True)]}
            for budget in (minimum - 1, minimum, minimum + 1, minimum + 100001, 10**32 - 1):
                principal = min(maximum, 20 * (Fraction(budget) // sat) // 23 - network - printing - tag)
                total = ceiling(ceiling(Fraction(23, 20) * (principal + network + printing + tag)) * sat)
                cases.append({'options': options, 'budget': str(budget), 'principal': str(principal),
                              'total': str(total), 'remainder': str(budget - total), 'tag': str(tag)})
        self.run_script('const cases=' + json.dumps(cases) + r''';
for(const test of cases) {
  const payload=Object.assign(marketFixture(),test.options.no_tag,{quote_options:{economy:test.options,medium:null,fast:null}});
  handler=async()=>({ok:true,json:async()=>payload}); load(); await tick();
  ids['quote-tag'].checked=true; await ids['quote-tag'].emit('change');
  ids['quote-mode'].value='budget_toman'; await ids['quote-mode'].emit('change');
  await edit('quote-amount',test.budget); await ids['quote-form'].emit('submit');
  if(BigInt(test.principal)<500n) {
    assert.equal(ids['quote-result'].hidden,true);
    assert.equal(ids['quote-status'].dataset.state,'error');
  } else {
    assert.equal(ids['quote-result'].hidden,false);
    for(const [field,value] of Object.entries({principal:test.principal,'total-toman':test.total,remainder:test.remainder,'tag-cost-result':test.tag}))
      assert.equal(ids['quote-'+field].textContent.replaceAll(',',''),value,field+test.budget);
  }
}
assert.equal(requests.length,cases.length);
''', page='market')

    def test_invalid_or_missing_priority_is_disabled_without_fabrication(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from pricing import quote_table
        options = {speed: {variant: quote_table('10000000000', '100000', fee, include_tag=tag)
                           for variant, tag in (('no_tag', False), ('with_tag', True))}
                   for speed, fee in (('economy', '1'), ('medium', '2'), ('fast', '3'))}
        self.run_script('const choices=' + json.dumps(options) + r''';
for (const damage of [
  x=>x.medium=null,
  x=>delete x.medium,
  x=>x.medium.with_tag.costs.tag_sats=-1,
  x=>delete x.medium.no_tag.rows[0].tag_sats,
  x=>x.medium.with_tag.assumptions.include_tag=false,
  x=>x.medium.with_tag.rates.satoshi_toman='200',
  x=>x.medium.with_tag.assumptions.network_fee_rate='10001',
  x=>x.medium.with_tag.rows[0].tag_sats+=1
]) {
  const options=structuredClone(choices); damage(options);
  const payload=Object.assign(marketFixture(),options.economy.no_tag,{quote_options:options,status:'stale'});
  handler=async()=>({ok:true,json:async()=>payload}); load(); await tick();
  assert.equal(ids['quote-calculate'].disabled,false);
  assert.equal(ids['quote-speed-medium'].disabled,true,'Invalid choice must be disabled');
  assert.equal(ids['quote-speed-fast'].disabled,false);
  assert.equal(ids['quote-tag'].disabled,false);
  assert.match(ids['quote-options-status'].textContent,/غیرفعال/);
  ids['quote-tag'].checked=true; await ids['quote-tag'].emit('change');
  await edit('quote-amount','3000'); await ids['quote-form'].emit('submit');
  assert.equal(ids['quote-result'].hidden,false);
  assert.match(ids['quote-result-warning'].textContent,/قدیمی/);
  ids['quote-speed'].value='medium'; await ids['quote-speed'].emit('change');
  assert.equal(ids['quote-result'].hidden,true);
  assert.equal(ids['quote-tag-cost-result'].textContent,'');
  assert.equal(ids['quote-calculate'].disabled,true);
  assert.equal(ids['quote-rows'].children.length,0);
  await ids['quote-form'].emit('submit');
  assert.equal(ids['quote-result'].hidden,true);
  ids['quote-speed'].value='fast'; await ids['quote-speed'].emit('change');
  assert.equal(ids['quote-calculate'].disabled,false);
  assert.equal(ids['market-stale'].hidden,false);
}
assert.equal(requests.length,8,'One fetch per independent page load');
''', page='market')

    def test_option_controls_are_labeled_local_and_default_to_no_tag(self):
        source = self.render("costs.html")
        document = Document(source)
        for field_id in ("quote-speed", "quote-tag"):
            field = document.by_id(field_id)
            self.assertNotIn("name", field)
            self.assertIn("disabled", field)
            self.assertIn(("label", {"for": field_id}), document.elements)
            for hint in field["aria-describedby"].split():
                self.assertTrue(document.by_id(hint))
        self.assertNotIn("checked", document.by_id("quote-tag"))
        self.assertEqual(document.by_id("quote-tag")["type"], "checkbox")
        self.assertIn("selected", document.by_id("quote-speed-economy"))
        for phrase in ("۰٫۱۲", "برچسب", "متوسط", "سریع", "تضمین"):
            self.assertIn(phrase, source)
        for field in ("quote-tag-cost", "quote-tag-cost-result"):
            self.assertEqual(document.by_id(field)["dir"], "ltr")

    def test_custom_principal_calculation_is_explicit_exact_and_local(self):
        self.run_script(r'''
handler=async()=>({ok:true,json:async()=>marketFixture()});
load(); await tick();
assert.equal(ids['quote-calculate'].disabled,false,'Ready after the shared snapshot');
await edit('quote-amount','3000');
assert.equal(ids['quote-result'].hidden,true,'Typing must not calculate');
await ids['quote-form'].emit('submit');
assert.equal(ids['quote-result'].hidden,false);
for(const [field,value] of Object.entries({principal:'3,000',btc:'0.00003',network:'141',print:'150',operator:'494','total-sats':'3,785','total-toman':'378,500','total-rial':'3,785,000'})) {
  assert.equal(ids['quote-'+field].textContent,value,field);
}
assert.equal(ids['quote-status'].dataset.state,'success');
assert.equal(requests.length,1,'Custom inputs must never leave the browser');
assert.equal(requests[0].url,'/api/market');
assert.equal(requests[0].options.body,undefined);
assert.equal(requests[0].options.method,'GET');
''', page="market")

    def test_custom_budget_finds_maximal_net_principal_and_keeps_remainder(self):
        self.run_script(r'''
handler=async()=>({ok:true,json:async()=>marketFixture()});
load(); await tick();
ids['quote-mode'].value='budget_toman'; await ids['quote-mode'].emit('change');
await edit('quote-amount','200000'); await ids['quote-form'].emit('submit');
assert.equal(ids['quote-principal'].textContent,'1,448');
assert.equal(ids['quote-operator'].textContent,'261');
assert.equal(ids['quote-total-sats'].textContent,'2,000');
assert.equal(ids['quote-total-toman'].textContent,'200,000');
assert.equal(ids['quote-budget'].textContent,'200,000');
assert.equal(ids['quote-remainder'].textContent,'0');
assert.equal(ids['quote-budget-details'].hidden,false);
await edit('quote-amount','200099');
assert.equal(ids['quote-result'].hidden,true,'Editing invalidates the previous quote');
await ids['quote-form'].emit('submit');
assert.equal(ids['quote-principal'].textContent,'1,448');
assert.equal(ids['quote-remainder'].textContent,'99');
ids['quote-mode'].value='principal_sats'; await ids['quote-mode'].emit('change');
assert.equal(ids['quote-result'].hidden,true,'Changing units invalidates the previous quote');
await edit('quote-amount','500'); await ids['quote-form'].emit('submit');
assert.equal(ids['quote-budget-details'].hidden,true);
assert.equal(requests.length,1);
''', page="market")

    def test_custom_quote_form_is_accessible_local_and_explicit(self):
        source = self.render("costs.html")
        document = Document(source)
        form = document.by_id("quote-form")
        self.assertEqual(form["action"], "/costs")
        self.assertEqual(form["method"], "get")
        for field_id in ("quote-mode", "quote-amount"):
            field = document.by_id(field_id)
            self.assertIn(("label", {"for": field_id}), document.elements)
            self.assertNotIn("name", field, "No financial input belongs in a submitted request")
            for hint in field["aria-describedby"].split():
                self.assertTrue(document.by_id(hint))
        self.assertEqual(document.by_id("quote-amount")["dir"], "ltr")
        self.assertEqual(document.by_id("quote-amount")["maxlength"], "32")
        self.assertEqual(document.by_id("quote-calculate")["type"], "submit")
        self.assertIn("disabled", document.by_id("quote-calculate"))
        self.assertIn("hidden", document.by_id("quote-result"))
        self.assertEqual(document.by_id("quote-status")["aria-live"], "polite")
        self.assertEqual(document.by_id("quote-result")["aria-live"], "polite")
        for value in ("principal_sats", "budget_toman"):
            self.assertTrue(any(tag == "option" and attrs.get("value") == value for tag, attrs in document.elements))
        for phrase in ("۳۲", "۵۰۰", "۲۱ میلیون", "ارسال نمی‌شود", "محاسبه", "اصل مبلغ خالص", "باقی‌مانده"):
            self.assertIn(phrase, source)
        css = (ROOT / "static/site.css").read_text()
        for selector in (".quote-calculator", ".quote-controls", ".quote-result", ".quote-breakdown"):
            self.assertIn(selector, css)
        self.assertNotRegex(source, r'<(?:script|img|iframe)[^>]+src="https?://')
        self.assertNotRegex(source, r'\bon(?:submit|click|change|input)=')

    def test_custom_quote_rejects_bad_inputs_and_insufficient_budget_without_old_results(self):
        self.run_script(r'''
handler=async()=>({ok:true,json:async()=>marketFixture()}); load(); await tick();
for(const mode of ['principal_sats','budget_toman']) {
  ids['quote-mode'].value=mode; await ids['quote-mode'].emit('change');
  const bad=['','0','-1','+500','1e3','1.0','1,000','۵۰۰','٥٠٠',' 500','500 ','500\n','500\r','0500','9'.repeat(33),...(mode==='principal_sats'?['499','2100000000000001']:['90999'])];
  for(const value of bad) {
    await edit('quote-amount',mode==='principal_sats'?'3000':'200000');
    await ids['quote-form'].emit('submit');
    assert.equal(ids['quote-result'].hidden,false);
    await edit('quote-amount',value); await ids['quote-form'].emit('submit');
    assert.equal(ids['quote-result'].hidden,true,JSON.stringify(value));
    for(const key of ['principal','btc','network','print','operator','total-sats','total-toman','total-rial','budget','remainder']) assert.equal(ids['quote-'+key].textContent,'','Clear old result: '+value);
    assert.equal(ids['quote-amount'].getAttribute('aria-invalid'),'true',JSON.stringify(value));
    assert.equal(ids['quote-status'].dataset.state,'error');
    if(value==='90999') assert.match(ids['quote-status'].textContent,/کافی نیست/);
  }
}
await edit('quote-amount','91000'); await ids['quote-form'].emit('submit');
assert.equal(ids['quote-amount'].getAttribute('aria-invalid'),null);
assert.equal(ids['quote-principal'].textContent,'500');
assert.equal(ids['quote-remainder'].textContent,'0');
assert.equal(requests.length,1);
''', page="market")

    def test_custom_quote_readiness_stale_warning_and_unavailable_snapshot(self):
        self.run_script(r'''
let deliver;
handler=()=>new Promise(resolve=>{deliver=resolve;}); load();
assert.equal(ids['quote-calculate'].disabled,true);
assert.equal(ids['quote-status'].dataset.state,'loading');
await edit('quote-amount','3000'); await ids['quote-form'].emit('submit');
assert.equal(ids['quote-result'].hidden,true);
const payload=marketFixture(); payload.status='stale';
deliver({ok:true,json:async()=>payload}); await tick();
assert.equal(ids['quote-status'].dataset.state,'stale');
await ids['quote-form'].emit('submit');
assert.equal(ids['quote-status'].dataset.state,'stale');
assert.match(ids['quote-result-warning'].textContent,/قدیمی/);
assert.equal(ids['quote-result-fetched-at'].textContent,payload.fetched_at);
''', page="market")
        for mode in ("offline", "http503", "invalid"):
            with self.subTest(mode=mode):
                self.run_script("const mode=" + repr(mode) + r''';
handler=async()=>{if(mode==='offline') throw Error('offline');
 const payload=marketFixture(); if(mode==='invalid') payload.costs.network_sats=-1;
 return {ok:mode!=='http503',json:async()=>payload};};
load(); await tick();
assert.equal(ids['quote-calculate'].disabled,true);
assert.equal(ids['quote-status'].dataset.state,'error');
await edit('quote-amount','3000'); await ids['quote-form'].emit('submit');
assert.equal(ids['quote-result'].hidden,true);
assert.equal(ids['quote-total-toman'].textContent,'');
assert.equal(ids['quote-status'].dataset.state,'error');
assert.equal(requests.length,1);
''', page="market")

    def test_custom_modes_match_fraction_oracle_for_fractional_ceilings_minimum_and_supply(self):
        maximum = 2100000000000000
        scenarios = []
        # Python Fraction is independent of the UI's decimal-string BigInt implementation.
        for rate_text, network, printing in (("0.000000000000001", 1, 2),
                                              ("100.00000000000000000001", 141, 150),
                                              ("0.333333333333333333", 0, 0),
                                              ("105.00000000000000000000000001", 443, 193)):
            rate = Fraction(rate_text)

            def quote(principal):
                subtotal = principal + network + printing
                operator = (subtotal * 15 + 99) // 100
                total = subtotal + operator
                cost = (total * rate.numerator + rate.denominator - 1) // rate.denominator
                return {"principal": str(principal), "network": str(network), "print": str(printing),
                        "operator": str(operator), "total-sats": str(total),
                        "total-toman": str(cost), "total-rial": str(cost * 10)}

            for principal in (500, 501, 3000, maximum - 1, maximum):
                scenarios.append({"mode": "principal_sats", "input": str(principal), "rate": rate_text,
                                  "network": network, "printing": printing, "expected": quote(principal)})
            for budget in (int(quote(500)["total-toman"]), int(quote(3000)["total-toman"]) + 1,
                           int(quote(maximum)["total-toman"]), 10 ** 32 - 1):
                low, high = 500, maximum
                while low < high:
                    middle = (low + high + 1) // 2
                    if int(quote(middle)["total-toman"]) <= budget:
                        low = middle
                    else:
                        high = middle - 1
                expected = quote(low)
                expected.update(budget=str(budget), remainder=str(budget - int(expected["total-toman"])))
                scenarios.append({"mode": "budget_toman", "input": str(budget), "rate": rate_text,
                                  "network": network, "printing": printing, "expected": expected})
        self.run_script("const scenarios=" + json.dumps(scenarios) + r''';
for(const test of scenarios) {
  const payload=marketFixture();
  payload.rates.satoshi_toman=test.rate;
  payload.costs.network_sats=test.network; payload.costs.print_sats=test.printing;
  payload.rows=payload.rows.slice(0,1);
  Object.assign(payload.rows[0],{network_sats:test.network,print_sats:test.printing,total_sats:500+test.network+test.printing+119});
  handler=async()=>({ok:true,json:async()=>payload}); load(); await tick();
  ids['quote-mode'].value=test.mode; await ids['quote-mode'].emit('change');
  await edit('quote-amount',test.input); await ids['quote-form'].emit('submit');
  assert.equal(ids['quote-result'].hidden,false,JSON.stringify(test));
  for(const [key,value] of Object.entries(test.expected)) assert.equal(ids['quote-'+key].textContent.replaceAll(',',''),value,JSON.stringify({test,key}));
}
assert.equal(requests.length,scenarios.length,'One snapshot for each independently loaded page only');
''', page="market")

    def test_custom_modes_match_shared_synthetic_golden_vectors(self):
        vectors = json.loads((ROOT / "tests/fixtures/quote_calculator.json").read_text())["cases"]
        cases = []
        for vector in vectors:
            expected = vector.get("expected")
            # Error vectors share the first vector's pricing snapshot. Unsafe numeric
            # JSON costs are rejected, never rounded into a usable browser quote.
            metadata = expected or vectors[0]["expected"]
            costs = {key: int(value) for key, value in metadata["costs"].items()}
            subtotal = 500 + costs["network_sats"] + costs["print_sats"]
            operator = (subtotal * 15 + 99) // 100
            total = subtotal + operator
            rate = Fraction(metadata["rates"]["satoshi_toman"])
            toman = (total * rate.numerator + rate.denominator - 1) // rate.denominator
            row = {"principal_sats": 500, "btc": "0.00000500", **costs,
                   "operator_sats": operator, "total_sats": total, "total_toman": toman,
                   "total_rial": toman * 10, "budget_toman": None, "remainder_toman": 0}
            assumptions = {**metadata["assumptions"], "transaction_vbytes": 141}
            unsafe = any(value > 9007199254740991 for value in (*costs.values(), total, toman * 10))
            cases.append({**vector, "snapshot": {"rates": metadata["rates"], "assumptions": assumptions,
                                                 "costs": costs, "rows": [row]}, "unsafe": unsafe})
        self.run_script("const cases=" + json.dumps(cases) + r''';
let successful=0, rejected=0;
for(const test of cases) {
  const payload=Object.assign(marketFixture(),test.snapshot);
  handler=async()=>({ok:true,json:async()=>payload}); load(); await tick();
  const mode=test.mode==='principal'?'principal_sats':'budget_toman';
  ids['quote-mode'].value=mode; await ids['quote-mode'].emit('change');
  await edit('quote-amount',test.inputs[mode]); await ids['quote-form'].emit('submit');
  if(test.unsafe || test.expected_error || test.inputs[mode].length>32) {
    assert.equal(ids['quote-result'].hidden,true,test.id);
    assert.equal(ids['quote-status'].dataset.state,'error',test.id);
    if(test.id==='budget_insufficient') assert.match(ids['quote-status'].textContent,/کافی نیست/);
    if(test.unsafe) assert.equal(ids['quote-calculate'].disabled,true);
    rejected++; continue;
  }
  assert.equal(ids['quote-result'].hidden,false,test.id);
  for(const [key,field] of Object.entries({principal_sats:'principal',network_sats:'network',print_sats:'print',operator_sats:'operator',total_sats:'total-sats',total_toman:'total-toman',total_rial:'total-rial'})) {
    assert.equal(ids['quote-'+field].textContent.replaceAll(',',''),test.expected[key],test.id+':'+key);
  }
  assert.equal(ids['quote-btc'].textContent,test.expected.btc.replace(/\.?0+$/,''),test.id);
  if(test.mode==='budget') {
    assert.equal(ids['quote-budget'].textContent.replaceAll(',',''),test.expected.budget_toman,test.id);
    assert.equal(ids['quote-remainder'].textContent.replaceAll(',',''),test.expected.remainder_toman,test.id);
    if(test.next_principal_total_toman) assert.ok(BigInt(test.next_principal_total_toman)>BigInt(test.inputs.budget_toman),test.id+':maximality');
  }
  successful++;
}
assert.ok(successful>=10); assert.ok(rejected>=4);
assert.equal(requests.length,cases.length);
''', page="market")
        gross = [vector for vector in vectors if "raw_asset_toman" in vector]
        self.run_script("const cases=" + json.dumps(gross) + r''';
for(const test of cases) {
  const payload=marketFixture(); payload.raw_rates={btc_toman:test.inputs.btc_toman,usdt_toman:test.inputs.usdt_toman};
  handler=async()=>({ok:true,json:async()=>payload}); load(); await tick();
  await edit('satoshi-amount',test.expected.principal_sats);
  assert.equal(ids['gross-toman'].textContent.replaceAll(',',''),test.raw_asset_toman,test.id);
}
assert.equal(requests.length,cases.length);
''')

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
const names = process.argv[2] === 'converter' ? ['satoshi-converter','btc-amount','satoshi-amount','converter-status','gross-valuation','gross-status','gross-result','gross-toman','gross-raw-price','gross-fetched-at','gross-stale'] :
  process.argv[2] === 'market' ? ['market-panel','market-status','market-stale','market-data','market-fetched-at','btc-price','usdt-price','sat-price','network-fee-rate','quote-speed','quote-speed-economy','quote-speed-medium','quote-speed-fast','quote-tag','quote-tag-cost','quote-options-status','quote-rows','quote-form','quote-mode','quote-amount','quote-calculate','quote-status','quote-result','quote-principal','quote-btc','quote-network','quote-print','quote-tag-cost-result','quote-operator','quote-total-sats','quote-total-toman','quote-total-rial','quote-budget','quote-remainder','quote-budget-details','quote-result-fetched-at','quote-result-warning'] : [];
const ids=Object.fromEntries(names.map(name=>[name,new Element()]));
if(ids['gross-result']) ids['gross-result'].hidden=true;
if(ids['gross-stale']) ids['gross-stale'].hidden=true;
if(ids['quote-mode']) ids['quote-mode'].value='principal_sats';
if(ids['quote-result']) ids['quote-result'].hidden=true;
if(ids['quote-calculate']) ids['quote-calculate'].disabled=true;
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
  raw_rates:{btc_toman:'9950248756.21890547263681592039800995',usdt_toman:'99502.4875621890547263681592039800995'},
  rates:{btc_toman:'10000000000',usdt_toman:'100000',satoshi_toman:'100'},
  assumptions:{exchange_fee_percent:'0.5',operator_fee_percent:'15',print_usd:'0.15',transaction_vbytes:141,network_fee_rate:'1'},
  costs:{network_sats:141,print_sats:150},
  rows:[{principal_sats:500,btc:'0.00000500',network_sats:141,print_sats:150,operator_sats:119,total_sats:910,total_toman:91000,total_rial:910000,budget_toman:null,remainder_toman:0},
        {principal_sats:1000,btc:'0.00001000',network_sats:141,print_sats:150,operator_sats:194,total_sats:1485,total_toman:148500,total_rial:1485000,budget_toman:200000,remainder_toman:51500}]});
const load=()=>{
  // A reload gets a new DOM, not another set of listeners on the previous page.
  for(const name of names) ids[name]=new Element();
  for(const name of ['gross-result','gross-stale','quote-result','market-data','market-stale']) if(ids[name]) ids[name].hidden=true;
  if(ids['quote-mode']) ids['quote-mode'].value='principal_sats';
  if(ids['quote-speed']) ids['quote-speed'].value='economy';
  if(ids['quote-tag']) ids['quote-tag'].checked=false;
  if(ids['quote-calculate']) ids['quote-calculate'].disabled=true;
  vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
};
'''
        result = subprocess.run(["node", "-e", harness + "\n(async()=>{\n" + scenario + "\n})().catch(error=>{console.error(error); process.exitCode=1;});", str(ROOT / "static/calculator.js"), page], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

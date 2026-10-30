"""Offline serial admission; synthetic tokens, no inventory or live services."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_app():
    spec = importlib.util.spec_from_file_location('serial_validation_app', ROOT / 'app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def aliases(serial):
    token = quote(serial, safe='')
    return (('/' + token, 404), ('/s/' + token, 404),
            ('/lookup?serial=' + token, 400), ('/api/wallets/' + token, 400),
            ('/api/wallets/' + token + '/qr.svg', 400))


class SerialAdmission(unittest.TestCase):
    def test_native_form_pattern_matches_server_for_valid_and_invalid_tokens(self):
        import re
        from test_ui_contract import Document
        module = load_app()
        response = module.create_app({'TESTING': True}).test_client().get('/lookup')
        field = Document(response.text).by_id('serial')
        for serial in ('admin', 'login', '0587k45300', 'TEST-0587kTX100', '0587k45300\n'):
            with self.subTest(serial=serial):
                self.assertEqual(re.fullmatch(field['pattern'], serial) is not None,
                                 module.SERIAL_RE.fullmatch(serial) is not None)

    def test_shape_boundaries_match_browser_and_native_pattern(self):
        import json
        import test_ui_contract
        valid = ['0587k45300', '0587kTX0', '0587kTXzz', '0587kTX100',
                 '0587kTX1000', 'admin0587k45300', 'A_b-C0587kTX0',
                 'A' * 56 + '0587kTX0']
        invalid = ['admin', 'login', '0587kTX', '0587kTY0', '0587nTX0',
                   '05c7kTX0', '058vkTX0', '0587kTXA', '-0587k45300',
                   '_0587k45300', 'A' * 57 + '0587kTX0', '0587k45300\n',
                   '0587k45300\r', '0587k45300 ', '0587k45300/',
                   '۰۵87k45300', '0587kTX0\x00']
        module = load_app()
        limiter = Mock()
        limiter.admit.return_value = 0
        lookup = Mock(return_value=None)
        app = module.create_app({'TESTING': True, 'LOOKUP_LIMITER': limiter, 'WALLET_LOOKUP': lookup})
        client = app.test_client()
        for serial in valid:
            self.assertIsNotNone(module.SERIAL_RE.fullmatch(serial), serial)
        for serial in invalid:
            for path, expected in aliases(serial):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, expected)
        limiter.admit.assert_not_called()
        lookup.assert_not_called()
        scenario = 'const valid = ' + json.dumps(valid) + ';\nconst invalid = ' + json.dumps(invalid) + ';\n'
        scenario += r'''
// HTML pattern uses Unicode sets mode and implicit full-string matching.
const native = new RegExp('^(?:'+ids.serial.getAttribute('pattern')+')(?![\\s\\S])', 'v');
handler=async()=>({ok:false,status:404});
for (const serial of invalid) {
  assert.equal(native.test(serial), false, JSON.stringify(serial));
  await submit(serial);
  assert.equal(requests.length, 0, JSON.stringify(serial));
}
for (const serial of valid) {
  assert.equal(native.test(serial), true, serial);
  const before = requests.length;
  await submit(serial);
  assert.equal(requests.length, before+1, serial);
  assert.equal(requests.at(-1).url, '/api/wallets/'+encodeURIComponent(serial));
}
'''
        test_ui_contract.UIContract().run_lookup_script(scenario)

    def test_browser_rejects_unrelated_names_without_fetch(self):
        import test_ui_contract
        test_ui_contract.UIContract().run_lookup_script(r'''
for (const serial of ['admin', 'login', 'TEST-DO-NOT-FUND', '0587k45300\n']) {
  await submit(serial);
  assert.equal(requests.length, 0, 'Invalid serial reached fetch: '+JSON.stringify(serial));
  assert.equal(ids.serial.getAttribute('aria-invalid'), 'true');
}
''')

    def test_unrelated_names_rejected_before_any_database_or_limiter_access(self):
        module = load_app()
        # No WALLET_LOOKUP override: exercise the production route/factory boundary.
        app = module.create_app({'TESTING': True})
        client = app.test_client()
        with patch('lookup_limit.LookupLimiter', side_effect=RuntimeError('FORBIDDEN_ADMISSION')) as limiter, \
                patch.object(module.psycopg, 'connect') as connect, \
                patch.object(module.Path, 'read_text', side_effect=AssertionError('FORBIDDEN_SECRET_READ')) as secret_read:
            for serial in ('admin', 'login', 'robots.txt', 'TEST-DO-NOT-FUND'):
                for path, expected in aliases(serial):
                    with self.subTest(path=path):
                        response = app.test_client().get(path)
                        self.assertEqual(response.status_code, expected)
            limiter.assert_not_called()
            connect.assert_not_called()
            secret_read.assert_not_called()
        self.assertNotIn('lookup_limiter', app.extensions)

    def test_generated_serial_modes_prefixes_and_suffix_widths_keep_all_aliases(self):
        # Execute the actual pure encoder definitions without importing key generation.
        import ast
        import datetime as dt
        source = (ROOT.parent / 'btc_envelope_maker' / 'btc_envelope_maker.py').read_text()
        names = {'gregorian_to_jalali', 'enc1', 'enc_hour', 'enc_ms', 'to_b36', 'serial_stem'}
        tree = ast.parse(source)
        nodes = [node for node in tree.body if
                 isinstance(node, ast.FunctionDef) and node.name in names or
                 isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and
                     target.id in {'_ALPHA', '_B36', '_B60'} for target in node.targets)]
        encoder = {'dt': dt}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<generator-serial-helpers>', 'exec'), encoder)
        module = load_app()
        limiter = Mock()
        limiter.admit.return_value = 0
        lookup = Mock(side_effect=lambda serial: {'serial': serial,
                      'address': 'bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu'})
        client = module.create_app({'TESTING': True, 'WALLET_LOOKUP': lookup,
                                   'LOOKUP_LIMITER': limiter}).test_client()
        for mode in ('digits', 'compact'):
            for moment in (dt.datetime(2026, 3, 21), dt.datetime(2026, 10, 30, 23, 59, 59)):
                stem, _ = encoder['serial_stem'](moment, mode)
                for prefix in ('', 'TEST-', 'a_9-Z-', '123'):
                    for width, index in ((1, 35), (2, 1295), (3, 1296), (4, 46656)):
                        serial = prefix + stem + encoder['to_b36'](index, width)
                        for path, _ in aliases(serial):
                            with self.subTest(serial=serial, path=path):
                                response = client.get(path)
                                self.assertEqual(response.status_code, 200)
                                lookup.assert_called_with(serial)

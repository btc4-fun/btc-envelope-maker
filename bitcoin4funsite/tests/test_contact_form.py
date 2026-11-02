"""Real form and service with a recording sender and synthetic SQLite."""
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from contact import ContactService


class ContactForm(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name) / 'contact.db'
        env = patch.dict(os.environ, {'CONTACT_SECRET': 'synthetic-form-secret-with-enough-bytes',
            'CONTACT_STATE_FILE': str(self.state)})
        env.start()
        self.addCleanup(env.stop)
        self.now = [1000000]
        self.sent = []
        def publish(payload, token):
            self.sent.append(payload)
            return {'event': 'message', 'topic': 'btc4fun', 'id': 'synthetic'}
        self.service = ContactService(publish=publish, token_loader=lambda: 'synthetic', clock=lambda: self.now[0])
        self.client = create_app({'TESTING': True, 'CONTACT_SERVICE': self.service}).test_client()

    def form(self):
        page = self.client.get('/contact')
        match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert match is not None
        token = match[1]
        answer = str(sum(map(int, token.split('.')[3:5])))
        return page, dict(name='Synthetic', mobile='', message='Synthetic only', website='',
                         csrf_token=token, captcha_answer=answer)

    def post(self, form, **kwargs):
        return self.client.post('/contact', data=form, headers={'Origin': 'https://btc4.fun'}, **kwargs)

    def test_real_form_question_and_three_digit_scripts_without_js(self):
        for digits in ('0123456789', '۰۱۲۳۴۵۶۷۸۹', '٠١٢٣٤٥٦٧٨٩'):
            page, form = self.form()
            self.assertIn(self.service.question(form['csrf_token']), page.text)
            self.assertRegex(page.text, r'id="contact-captcha"[^>]*name="captcha_answer"')
            self.assertNotRegex(page.text, r'type="hidden"[^>]*name="captcha_answer"')
            form['captcha_answer'] = form['captcha_answer'].translate(str.maketrans('0123456789', digits))
            self.assertEqual(self.post(form).status_code, 303)
            self.assertEqual(self.post(form).status_code, 400)
        self.assertEqual(len(self.sent), 3)
        self.assertIn('Source IP: 127.0.0.1', self.sent[0]['message'])
        self.assertNotIn('127.0.0.1', self.state.read_bytes().decode('latin1'))

    def test_invalid_answer_tamper_expiry_and_browser_ip_never_publish(self):
        _, form = self.form()
        for answer in ('99', '', ' 2', '+2', '２', '²'):
            response = self.post(dict(form, captcha_answer=answer))
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(form['csrf_token'], response.text)
        parts = form['csrf_token'].split('.')
        parts[3] = '1' if parts[3] != '1' else '2'
        self.assertEqual(self.post(dict(form, csrf_token='.'.join(parts))).status_code, 400)
        self.assertEqual(self.post(dict(form, client_ip='203.0.113.9')).status_code, 400)
        self.now[0] += 900
        self.assertEqual(self.post(form).status_code, 400)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.state.exists())

import glob
import os
import re
import unittest

from database import db
from helpers import ADMIN_PASS, ROOT, create_test_app, login


class FrontendTestCase(unittest.TestCase):
    def setUp(self):
        self.app, self.db_manager = create_test_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.ctx.pop()

    def add_event(self, **overrides):
        data = {'name': 'Offenes Rudern', 'weekday': 'Montag', 'start_time': '10:00', 'end_time': '12:00', 'season': 'Immer'}
        data.update(overrides)
        return self.client.post('/add', data=data)


class AccessTest(FrontendTestCase):
    def test_protected_pages_redirect_to_login(self):
        for path in ('/', '/users', '/export-csv', '/download/stegplan.pdf', '/download/stundenplan.pdf'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertIn('/login', response.headers['Location'], path)

    def test_plans_are_public(self):
        login(self.client)
        self.add_event()
        self.client.get('/logout')
        for path in ('/stegplan.svg', '/stundenplan.svg'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.mimetype, 'image/svg+xml', path)
            response.close()

    def test_wrong_password_shows_the_login_again(self):
        response = login(self.client, password='falsch')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/').status_code, 302)

    def test_only_the_admin_reaches_user_management(self):
        login(self.client)
        self.assertEqual(self.client.get('/users').status_code, 200)
        self.client.post('/users/add', data={'username': 'steg', 'password': 'steg-password'})
        self.client.get('/logout')
        login(self.client, 'steg', 'steg-password')
        self.assertEqual(self.client.get('/users').status_code, 302)


class LoginFormTest(FrontendTestCase):
    def test_missing_password_field_does_not_crash(self):
        response = self.client.post('/login', data={'username': 'admin'})
        self.assertEqual(response.status_code, 200)

    def test_missing_password_fields_do_not_crash_the_password_change(self):
        login(self.client)
        response = self.client.post('/change-password', data={})
        self.assertEqual(response.status_code, 200)


class MessageTest(FrontendTestCase):
    def test_login_error_is_localized(self):
        page = login(self.client, password='falsch').data.decode()
        self.assertIn('Ungültiger Benutzername oder Passwort', page)

    def test_password_change_messages_are_localized(self):
        login(self.client)
        cases = [
            ({'current_password': 'falsch'}, 'nicht korrekt'),
            ({'current_password': ADMIN_PASS, 'new_password': 'neues-passwort', 'confirm_password': 'anders'}, 'nicht überein'),
            ({'current_password': ADMIN_PASS, 'new_password': 'kurz', 'confirm_password': 'kurz'}, 'mindestens 8 Zeichen'),
            ({'current_password': ADMIN_PASS, 'new_password': 'neues-passwort', 'confirm_password': 'neues-passwort'}, 'erfolgreich'),
        ]
        for data, message in cases:
            self.assertIn(message, self.client.post('/change-password', data=data).data.decode())


class SecurityHeaderTest(FrontendTestCase):
    def test_headers_are_set_on_every_response(self):
        for path in ('/login', '/static/style.css', '/gibt-es-nicht'):
            response = self.client.get(path)
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff', path)
            self.assertEqual(response.headers['Referrer-Policy'], 'same-origin', path)
            response.close()

    def test_https_settings_are_off_for_local_http(self):
        response = self.client.get('/login')
        self.assertNotIn('Strict-Transport-Security', response.headers)
        self.assertNotIn('Secure', response.headers['Set-Cookie'])


    def test_csp_is_set_on_pages_but_not_on_plans(self):
        self.assertIn("script-src 'self'", self.client.get('/login').headers['Content-Security-Policy'])
        login(self.client)
        self.add_event()
        response = self.client.get('/stegplan.svg')
        self.assertNotIn('Content-Security-Policy', response.headers)
        response.close()


class TemplateTest(FrontendTestCase):
    def test_templates_contain_no_inline_code_or_external_resources(self):
        forbidden = re.compile(r'\son[a-z]+=|<script>|\sstyle=|src="https?://|href="https?://')
        for path in glob.glob(os.path.join(ROOT, 'templates', '*.html')):
            with open(path, encoding='utf-8') as f:
                self.assertIsNone(forbidden.search(f.read()), path)

    def test_stylesheet_and_script_are_served(self):
        for path in ('/static/style.css', '/static/app.js'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.data, path)
            response.close()

    def test_pdf_dialogs_are_only_rendered_after_login(self):
        self.assertNotIn(b'schedulePdfModal', self.client.get('/login').data)
        login(self.client)
        self.assertIn(b'schedulePdfModal', self.client.get('/').data)

    def test_username_cannot_break_out_of_the_confirmation(self):
        login(self.client)
        self.client.post('/users/add', data={'username': '"><b>x', 'password': 'steg-password'})
        page = self.client.get('/users').data.decode()
        self.assertNotIn('"><b>x', page)
        self.assertIn('data-confirm="', page)


class HttpsOnlyTest(unittest.TestCase):
    def test_https_settings_are_on_by_default(self):
        app, _ = create_test_app(https_only=True)
        with app.app_context():
            response = app.test_client().get('/login', base_url='https://localhost')
            self.assertEqual(response.headers['Strict-Transport-Security'], 'max-age=2592000')
            cookie = response.headers['Set-Cookie']
            self.assertIn('Secure', cookie)
            self.assertIn('HttpOnly', cookie)
            self.assertIn('SameSite=Lax', cookie)
            db.session.remove()
            db.engine.dispose()


class EventTest(FrontendTestCase):
    def setUp(self):
        super().setUp()
        login(self.client)

    def test_add_edit_and_delete_event(self):
        self.add_event()
        event = self.db_manager.get_events()[0]
        self.client.post(f'/edit/{event.id}', data={'name': 'Handicap', 'weekday': 'Mittwoch', 'start_time': '18:00', 'end_time': '20:00', 'season': 'Immer'})
        self.assertEqual(self.db_manager.get_events()[0].name, 'Handicap')
        self.assertIn('Handicap'.encode(), self.client.get('/').data)
        self.client.post(f'/delete/{event.id}')
        self.assertEqual(self.db_manager.get_events(), [])

    def test_invalid_date_is_rejected(self):
        response = self.add_event(season='Manuell', start_date='31.02', end_date='01.03')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.db_manager.get_events(), [])

    def test_pdf_downloads(self):
        self.add_event()
        for path in ('/download/stegplan.pdf?date=2026-11-01&orientation=landscape', '/download/stundenplan.pdf?date=2026-11-01'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.data.startswith(b'%PDF'), path)


if __name__ == '__main__':
    unittest.main()

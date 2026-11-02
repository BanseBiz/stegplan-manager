import io
import os
import sqlite3
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from database import db
from helpers import create_test_app, login
from test_frontend import FrontendTestCase

EVENT = {'name': 'Termin', 'weekday': 'Montag', 'start_time': '10:00', 'end_time': '12:00', 'season': 'Immer'}
CSV = 'Name,Wochentag,Anfang,Ende\nImport,Montag,10:00,12:00\n'


class PermissionMigrationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, 'old.db')
        connection = sqlite3.connect(self.path)
        connection.executescript('''
            CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR(50) NOT NULL UNIQUE, password_hash VARCHAR(255) NOT NULL);
            CREATE TABLE room (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE, slug VARCHAR(120) NOT NULL UNIQUE, sort_order INTEGER NOT NULL);
            CREATE TABLE event (id INTEGER PRIMARY KEY, room_id INTEGER REFERENCES room(id), name VARCHAR(100) NOT NULL, weekday VARCHAR(20) NOT NULL,
                start_time VARCHAR(10) NOT NULL, end_time VARCHAR(10) NOT NULL, season VARCHAR(20), start_date VARCHAR(5), end_date VARCHAR(5),
                supervisor1 VARCHAR(50), supervisor2 VARCHAR(50), supervisor3 VARCHAR(50), comment VARCHAR(200));
        ''')
        password = generate_password_hash('irrelevant')
        connection.executemany('INSERT INTO user (username, password_hash) VALUES (?, ?)', [('admin', password), ('anna', password), ('bert', password)])
        connection.executemany('INSERT INTO room (name, slug, sort_order) VALUES (?, ?, ?)', [('Kraftraum', 'kraftraum', 1), ('Ergoraum', 'ergoraum', 2)])
        connection.commit()
        connection.close()

    def tearDown(self):
        self.directory.cleanup()

    def start(self):
        app, db_manager = create_test_app(f'sqlite:///{self.path}')
        return app, db_manager

    def close(self):
        db.session.remove()
        db.engine.dispose()

    def test_existing_users_keep_their_access(self):
        app, db_manager = self.start()
        with app.app_context():
            for room in db_manager.get_all_rooms():
                self.assertEqual([user.username for user in room.managers], ['anna', 'bert'])
                self.assertTrue(room.show_in_overview)
            users = {user.username: user for user in db_manager.get_all_users()}
            self.assertTrue(users['anna'].manages_stegplan)
            self.assertTrue(users['bert'].manages_stegplan)
            self.close()

    def test_backfill_runs_only_once(self):
        app, db_manager = self.start()
        with app.app_context():
            kraft = db_manager.get_room_by_slug('kraftraum')
            db_manager.set_room_managers(kraft.id, [])
            db_manager.add_user('carl', 'x')
            self.close()
        app, db_manager = self.start()
        with app.app_context():
            self.assertEqual(db_manager.get_room_by_slug('kraftraum').managers, [])
            self.assertEqual([user.username for user in db_manager.get_room_by_slug('ergoraum').managers], ['anna', 'bert'])
            self.assertFalse(db_manager.get_user_by_username('carl').manages_stegplan)
            self.close()


class FreshInstallTest(unittest.TestCase):
    def test_new_users_and_rooms_start_without_managers(self):
        app, db_manager = create_test_app()
        with app.app_context():
            db_manager.add_user('anna', 'x')
            room = db_manager.add_room('Kraftraum')
            self.assertEqual(room.managers, [])
            self.assertTrue(room.show_in_overview)
            self.assertFalse(db_manager.get_user_by_username('anna').manages_stegplan)
            self.assertFalse(db_manager.get_user_by_username('admin').manages_stegplan)
            db.session.remove()
            db.engine.dispose()

    def test_deleting_users_and_rooms_removes_their_assignments(self):
        app, db_manager = create_test_app()
        with app.app_context():
            db_manager.add_user('anna', 'x')
            anna = db_manager.get_user_by_username('anna')
            kraft = db_manager.add_room('Kraftraum')
            ergo = db_manager.add_room('Ergoraum')
            db_manager.set_room_managers(kraft.id, [anna.id])
            db_manager.set_room_managers(ergo.id, [anna.id])
            db_manager.delete_room(kraft.id)
            self.assertEqual([room.name for room in anna.managed_rooms], ['Ergoraum'])
            db_manager.delete_user(anna.id)
            self.assertEqual(ergo.managers, [])
            self.assertEqual(db.session.execute(db.text('SELECT COUNT(*) FROM room_manager')).scalar(), 0)
            db.session.remove()
            db.engine.dispose()


class AccessTest(FrontendTestCase):
    """anna manages the Kraftraum, bert the stegplan, carl nothing."""

    def setUp(self):
        super().setUp()
        login(self.client)
        for name in ('anna', 'bert', 'carl'):
            self.client.post('/users/add', data={'username': name, 'password': f'{name}-password'})
        self.users = {name: self.db_manager.get_user_by_username(name) for name in ('anna', 'bert', 'carl')}
        self.client.post('/rooms/add', data={'name': 'Kraftraum', 'sort_order': '1'})
        self.client.post('/rooms/add', data={'name': 'Ergoraum', 'sort_order': '2'})
        self.kraft = self.db_manager.get_room_by_slug('kraftraum')
        self.ergo = self.db_manager.get_room_by_slug('ergoraum')
        self.assign(self.kraft, 'anna')
        self.client.post('/rooms/stegplan', data={'managers': [str(self.users['bert'].id)], 'show_in_overview': '1'})
        self.add_event(name='Steg-Termin')
        self.add_event(name='Ergo-Termin', room='ergoraum')
        self.add_event(name='Kraft-Termin', room='kraftraum')
        self.steg_event = self.db_manager.get_events()[0]
        self.ergo_event = self.db_manager.get_events(self.ergo.id)[0]
        self.client.get('/logout')

    def assign(self, room, *names, show_in_overview=True):
        data = {'name': room.name, 'sort_order': str(room.sort_order), 'managers': [str(self.users[name].id) for name in names]}
        if show_in_overview:
            data['show_in_overview'] = '1'
        return self.client.post(f'/rooms/{room.id}', data=data)

    def as_user(self, name):
        self.client.get('/logout')
        login(self.client, name, f'{name}-password')

    def counts(self):
        return self.db_manager.count_events(), self.db_manager.count_events(self.kraft.id), self.db_manager.count_events(self.ergo.id)

    def upload(self, room=None):
        data = {'csv_file': (io.BytesIO(CSV.encode()), 'plan.csv')}
        if room:
            data['room'] = room
        return self.client.post('/import-csv', data=data, content_type='multipart/form-data')

    def assert_no_access(self, room_slug, event):
        """Every way into a plan answers 404 and changes nothing."""
        before = self.counts()
        room_query = f'?room={room_slug}' if room_slug else ''
        room_data = {'room': room_slug} if room_slug else {}
        requests = [
            self.client.get(f'/add{room_query}'),
            self.client.post('/add', data=dict(EVENT, **room_data)),
            self.client.get(f'/edit/{event.id}'),
            self.client.post(f'/edit/{event.id}', data=EVENT),
            self.client.post(f'/delete/{event.id}'),
            self.client.post('/delete-all', data=room_data),
            self.upload(room_slug),
            self.client.get(f'/export-csv{room_query}'),
        ]
        if room_slug:
            requests += [self.client.get(f'/raum/{room_slug}'), self.client.get(f'/download/raum/{room_slug}.pdf')]
        else:
            requests += [self.client.get('/download/stegplan.pdf'), self.client.get('/download/stundenplan.pdf')]
        self.assertEqual([response.status_code for response in requests], [404] * len(requests))
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.db_manager.get_event(event.id).name, event.name)

    def assert_full_access(self, room_slug):
        room_query = f'?room={room_slug}' if room_slug else ''
        room_data = {'room': room_slug} if room_slug else {}
        self.assertEqual(self.client.get(f'/raum/{room_slug}' if room_slug else '/').status_code, 200)
        self.assertEqual(self.client.get(f'/add{room_query}').status_code, 200)
        self.assertEqual(self.client.post('/add', data=dict(EVENT, name='Neu', **room_data)).status_code, 302)
        self.assertEqual(self.upload(room_slug).status_code, 302)
        self.assertEqual(self.client.get(f'/export-csv{room_query}').status_code, 200)
        pdf = f'/download/raum/{room_slug}.pdf' if room_slug else '/download/stundenplan.pdf'
        self.assertEqual(self.client.get(pdf).status_code, 200)

    def test_room_manager_can_work_in_their_room_only(self):
        self.as_user('anna')
        self.assert_full_access('kraftraum')
        self.assert_no_access('ergoraum', self.ergo_event)
        self.assert_no_access(None, self.steg_event)

    def test_stegplan_manager_can_work_in_the_stegplan_only(self):
        self.as_user('bert')
        self.assert_full_access(None)
        self.assert_no_access('ergoraum', self.ergo_event)

    def test_user_without_plans_has_no_access(self):
        self.as_user('carl')
        self.assert_no_access(None, self.steg_event)
        self.assert_no_access('ergoraum', self.ergo_event)

    def test_admin_has_access_to_everything(self):
        login(self.client)
        self.assert_full_access(None)
        self.assert_full_access('ergoraum')

    def test_start_page_leads_to_the_first_own_plan(self):
        self.as_user('anna')
        self.assertTrue(self.client.get('/').headers['Location'].endswith('/raum/kraftraum'))
        self.as_user('carl')
        self.assertTrue(self.client.get('/').headers['Location'].endswith('/uebersicht'))
        self.as_user('bert')
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_tabs_only_show_own_plans(self):
        self.as_user('anna')
        for path in ('/raum/kraftraum', '/uebersicht'):
            page = self.client.get(path).data.decode()
            self.assertIn('/raum/kraftraum', page)
            self.assertNotIn('/raum/ergoraum', page)
            self.assertNotIn('>Stegplan<', page)
        login(self.client)
        page = self.client.get('/').data.decode()
        for link in ('/raum/kraftraum', '/raum/ergoraum', '>Stegplan<'):
            self.assertIn(link, page)

    def test_copies_are_limited_to_own_rooms(self):
        login(self.client)
        self.assign(self.kraft, 'anna')
        self.as_user('anna')
        form = self.client.get('/add?room=kraftraum').data.decode()
        self.assertNotIn('Ergoraum', form)
        self.client.post('/add', data=dict(EVENT, name='Kopie', room='kraftraum', copy_to_rooms=[str(self.ergo.id)]))
        self.assertNotIn('Kopie', [event.name for event in self.db_manager.get_events(self.ergo.id)])
        self.assertIn('Kopie', [event.name for event in self.db_manager.get_events(self.kraft.id)])

    def test_copies_reach_all_own_rooms(self):
        login(self.client)
        self.assign(self.ergo, 'anna')
        self.as_user('anna')
        self.client.post('/add', data=dict(EVENT, name='Kopie', room='kraftraum', copy_to_rooms=[str(self.ergo.id)]))
        self.assertIn('Kopie', [event.name for event in self.db_manager.get_events(self.ergo.id)])

    def test_plan_actions_only_on_dashboards(self):
        self.as_user('anna')
        self.assertIn('import-form', self.client.get('/raum/kraftraum').data.decode())
        for path in ('/change-password', '/uebersicht', f'/edit/{self.db_manager.get_events(self.kraft.id)[0].id}'):
            self.assertNotIn('import-form', self.client.get(path).data.decode(), path)

    def test_only_the_admin_assigns_managers(self):
        self.as_user('anna')
        self.assertEqual(self.client.get(f'/rooms/{self.ergo.id}').status_code, 302)
        self.assign(self.ergo, 'anna')
        self.client.post('/rooms/stegplan', data={'managers': [str(self.users['anna'].id)]})
        self.assertEqual(self.ergo.managers, [])
        self.assertFalse(self.users['anna'].manages_stegplan)

    def test_admin_is_never_listed(self):
        login(self.client)
        for path in (f'/rooms/{self.kraft.id}', '/rooms/stegplan'):
            page = self.client.get(path).data.decode()
            self.assertIn('>anna<', page)
            self.assertNotIn('>admin<', page)
        admin = self.db_manager.get_user_by_username('admin')
        self.assign(self.kraft, 'anna')
        self.client.post(f'/rooms/{self.kraft.id}', data={'name': 'Kraftraum', 'sort_order': '1', 'managers': [str(admin.id)]})
        self.assertEqual(self.kraft.managers, [])

    def test_admin_pages_show_the_assignments(self):
        login(self.client)
        rooms = self.client.get('/rooms').data.decode()
        self.assertIn('anna', rooms)
        self.assertIn('bert', rooms)
        users = self.client.get('/users').data.decode()
        self.assertIn('Kraftraum', users)
        self.assertIn('keine Pläne', users)
        self.assertIn('alle Pläne', users)

    def test_unassigning_removes_access_immediately(self):
        login(self.client)
        self.assign(self.kraft)
        self.as_user('anna')
        self.assertEqual(self.client.get('/raum/kraftraum').status_code, 404)

    def test_new_room_leads_to_its_settings(self):
        login(self.client)
        response = self.client.post('/rooms/add', data={'name': 'Sporthalle', 'sort_order': '3'})
        room = self.db_manager.get_room_by_slug('sporthalle')
        self.assertTrue(response.headers['Location'].endswith(f'/rooms/{room.id}'))

    def test_overview_flag_only_affects_the_overview(self):
        login(self.client)
        self.assign(self.ergo, show_in_overview=False)
        response = self.client.get('/nutzungszeiten.svg')
        overview = response.data.decode()
        response.close()
        self.assertNotIn('ERGORAUM', overview)
        self.assertIn('KRAFTRAUM', overview)
        self.assertIn('STEG', overview)
        self.client.get('/logout')
        response = self.client.get('/raumplan/ergoraum.svg')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Ergo-Termin', response.data)
        response.close()

    def overview(self):
        response = self.client.get('/nutzungszeiten.svg')
        data = response.data.decode()
        response.close()
        return data

    def test_stegplan_is_shown_in_the_overview_by_default(self):
        self.assertTrue(self.db_manager.get_stegplan_in_overview())
        self.assertIn('STEG', self.overview())

    def test_stegplan_can_be_hidden_from_the_overview(self):
        login(self.client)
        self.assertIn('checked', self.client.get('/rooms/stegplan').data.decode().split('show_in_overview')[1][:40])
        self.client.post('/rooms/stegplan', data={'managers': [str(self.users['bert'].id)]})
        overview = self.overview()
        self.assertNotIn('STEG', overview)
        self.assertNotIn('Steg-Termin', overview)
        self.assertIn('KRAFTRAUM', overview)
        stegplan_row = self.client.get('/rooms').data.decode().split('>Stegplan</td>')[1].split('</tr>')[0]
        self.assertIn('Nein', stegplan_row)
        self.assertNotIn('checked', self.client.get('/rooms/stegplan').data.decode().split('show_in_overview')[1][:40])
        self.assertTrue(self.users['bert'].manages_stegplan)
        self.client.get('/logout')
        response = self.client.get('/stegplan.svg')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Steg-Termin', response.data)
        response.close()

    def test_stegplan_can_be_shown_again(self):
        login(self.client)
        self.client.post('/rooms/stegplan', data={})
        self.client.post('/rooms/stegplan', data={'show_in_overview': '1'})
        self.assertIn('STEG', self.overview())

    def test_only_the_admin_hides_the_stegplan(self):
        self.as_user('bert')
        self.client.post('/rooms/stegplan', data={})
        self.assertTrue(self.db_manager.get_stegplan_in_overview())

    def test_public_plans_stay_public(self):
        for path in ('/stegplan.svg', '/stundenplan.svg', '/raumplan/kraftraum.svg', '/raumplan/ergoraum.svg', '/nutzungszeiten.svg'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            response.close()


if __name__ == '__main__':
    unittest.main()

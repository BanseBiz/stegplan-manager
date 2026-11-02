import glob
import io
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import inspect

from database import db, make_slug
from helpers import ROOT, WEEK, create_test_app, login, make_event, make_generator, timetable_tiles
from test_frontend import FrontendTestCase


EVENT = dict(name='Kinder U15', weekday='Montag', start_time='17:00', end_time='19:00', season='Immer', start_date='', end_date='',
             supervisor1='Annika', supervisor2='', supervisor3='', comment='')


class SlugTest(unittest.TestCase):
    def test_names_become_addresses(self):
        self.assertEqual(make_slug('Kraftraum'), 'kraftraum')
        self.assertEqual(make_slug('Sporthalle Marschweg'), 'sporthalle-marschweg')
        self.assertEqual(make_slug('Größe & Übung!'), 'groesse-uebung')
        self.assertEqual(make_slug('!!!'), 'raum')


class RoomDatabaseTest(FrontendTestCase):
    def setUp(self):
        super().setUp()
        self.kraft = self.db_manager.add_room('Kraftraum', 1)
        self.ergo = self.db_manager.add_room('Ergoraum', 2)
        self.db_manager.add_new_events([EVENT])
        self.db_manager.add_new_events([EVENT], self.kraft.id)
        self.db_manager.add_new_events([dict(EVENT, name='Team Rowing')], self.ergo.id)

    def names(self, room=None):
        return [event.name for event in self.db_manager.get_events(room.id if room else None)]

    def test_plans_do_not_share_events(self):
        self.assertEqual(self.names(), ['Kinder U15'])
        self.assertEqual(self.names(self.kraft), ['Kinder U15'])
        self.assertEqual(self.names(self.ergo), ['Team Rowing'])

    def test_deleting_all_events_only_affects_the_plan(self):
        self.db_manager.delete_all_events(self.kraft.id)
        self.assertEqual(self.names(self.kraft), [])
        self.assertEqual(self.names(), ['Kinder U15'])
        self.assertEqual(self.names(self.ergo), ['Team Rowing'])

        self.db_manager.delete_all_events()
        self.assertEqual(self.names(), [])
        self.assertEqual(self.names(self.ergo), ['Team Rowing'])

    def test_duplicates_are_checked_per_plan(self):
        self.assertEqual(self.db_manager.add_new_events([EVENT], self.kraft.id), (0, 1))
        self.assertEqual(self.db_manager.add_new_events([EVENT], self.ergo.id), (1, 0))

    def test_deleting_a_room_removes_only_its_events(self):
        self.db_manager.delete_room(self.kraft.id)
        self.assertEqual([room.name for room in self.db_manager.get_all_rooms()], ['Ergoraum'])
        self.assertEqual(self.db_manager.count_events(), 1)
        self.assertEqual(self.db_manager.count_events(self.ergo.id), 1)
        self.assertEqual(self.db_manager.count_events(self.kraft.id), 0)

    def test_rooms_are_sorted_by_their_order(self):
        self.db_manager.update_room(self.ergo.id, 'Ergoraum', 0)
        self.assertEqual([room.name for room in self.db_manager.get_all_rooms()], ['Ergoraum', 'Kraftraum'])

    def test_slug_is_unique_and_survives_a_rename(self):
        self.db_manager.update_room(self.kraft.id, 'Kraftkammer', 1)
        self.assertEqual(self.kraft.slug, 'kraftraum')
        self.assertEqual(self.db_manager.add_room('Kraftraum').slug, 'kraftraum-2')


class RoomPlanRenderingTest(unittest.TestCase):
    def setUp(self):
        self.gen = make_generator()
        self.room = SimpleNamespace(name='Kraftraum', slug='kraftraum')

    def labels(self, svg):
        return re.findall(r'class="time-label">(\d\d:00)<', svg)

    def test_grid_fits_the_events_of_the_room(self):
        svg = self.gen.generate_room_svg_string(self.room, [make_event('16:00', '17:30'), make_event('20:30', '22:00', weekday='Mittwoch')])
        labels = self.labels(svg)
        self.assertEqual((labels[0], labels[-1]), ('16:00', '21:00'))

    def test_page_keeps_its_height(self):
        for times in (('16:00', '22:00'), ('07:00', '22:00')):
            svg = self.gen.generate_room_svg_string(self.room, [make_event(*times)])
            self.assertIn('viewBox="0 0 1626 1150', svg)

    def test_empty_room_shows_the_default_grid(self):
        svg = self.gen.generate_room_svg_string(self.room, [])
        labels = self.labels(svg)
        self.assertEqual((labels[0], labels[-1]), ('08:00', '20:00'))
        self.assertEqual(timetable_tiles(svg), [])

    def test_title_names_the_room_and_is_escaped(self):
        self.assertIn('Nutzungszeiten ORVO Kraftraum', self.gen.generate_room_svg_string(self.room, []))
        room = SimpleNamespace(name='<script>', slug='x')
        svg = self.gen.generate_room_svg_string(room, [])
        self.assertNotIn('<script>', svg)
        self.assertIn('&lt;script&gt;', svg)

    def test_inactive_events_are_left_out(self):
        event = make_event(season='Manuell', start_date='01.04', end_date='30.09')
        date = datetime(2026, 11, 1)
        self.assertEqual(timetable_tiles(self.gen.generate_room_svg_string(self.room, [event], target_date=date)), [])

    def test_pdf_is_generated_with_a_validity_date(self):
        stream = self.gen.generate_room_pdf_for_date(self.room, [make_event()], datetime(2026, 11, 1))
        self.assertEqual(stream.read(4), b'%PDF')
        self.assertIn('gültig ab 01.11.', self.gen.generate_room_svg_string(self.room, [], datetime(2026, 11, 1), custom_title_date=True))

    def test_stundenplan_fits_its_events_like_rooms(self):
        events = [make_event('16:00', '17:30'), make_event('20:30', '22:00', weekday='Mittwoch')]
        stundenplan = self.labels(self.gen.generate_timetable_svg_string(events, WEEK))
        room = self.labels(self.gen.generate_room_svg_string(self.room, events))
        self.assertEqual(stundenplan, room)
        self.assertEqual((stundenplan[0], stundenplan[-1]), ('16:00', '21:00'))


class RoomRoutesTest(FrontendTestCase):
    def setUp(self):
        super().setUp()
        login(self.client)
        self.client.post('/rooms/add', data={'name': 'Kraftraum', 'sort_order': '1'})
        self.client.post('/rooms/add', data={'name': 'Ergoraum', 'sort_order': '2'})
        self.kraft = self.db_manager.get_room_by_slug('kraftraum')
        self.ergo = self.db_manager.get_room_by_slug('ergoraum')

    def add_room_event(self, room='kraftraum', **overrides):
        return self.add_event(room=room, **overrides)

    def upload(self, text, room=None):
        data = {'csv_file': (io.BytesIO(text.encode()), 'plan.csv')}
        if room:
            data['room'] = room
        return self.client.post('/import-csv', data=data, content_type='multipart/form-data', follow_redirects=True)

    def plan_svg(self, path):
        response = self.client.get(path)
        data = response.data.decode()
        response.close()
        return data

    def test_room_event_stays_out_of_the_stegplan_files(self):
        self.add_event(name='Offenes Rudern')
        self.add_room_event(name='Kinder U15')
        self.assertIn('Kinder U15', self.plan_svg('/raumplan/kraftraum.svg'))
        self.assertNotIn('Offenes Rudern', self.plan_svg('/raumplan/kraftraum.svg'))
        for path in ('/stegplan.svg', '/stundenplan.svg'):
            self.assertNotIn('Kinder U15', self.plan_svg(path), path)
            self.assertIn('Offenes Rudern', self.plan_svg(path), path)

    def test_dashboards_only_list_their_own_events(self):
        self.add_event(name='Offenes Rudern')
        self.add_room_event(name='Kinder U15')
        stegplan = self.client.get('/').data.decode()
        room = self.client.get('/raum/kraftraum').data.decode()
        self.assertIn('Offenes Rudern', stegplan)
        self.assertNotIn('Kinder U15', stegplan)
        self.assertIn('Kinder U15', room)
        self.assertNotIn('Offenes Rudern', room)

    def test_saving_redirects_back_to_the_plan(self):
        response = self.add_room_event()
        self.assertTrue(response.headers['Location'].endswith('/raum/kraftraum'))
        event = self.db_manager.get_events(self.kraft.id)[0]
        data = {'name': 'Neu', 'weekday': 'Montag', 'start_time': '10:00', 'end_time': '12:00', 'season': 'Immer'}
        response = self.client.post(f'/edit/{event.id}', data=data)
        self.assertTrue(response.headers['Location'].endswith('/raum/kraftraum'))
        self.assertIn('Neu', self.plan_svg('/raumplan/kraftraum.svg'))
        response = self.client.post(f'/delete/{event.id}')
        self.assertTrue(response.headers['Location'].endswith('/raum/kraftraum'))
        self.assertNotIn('Neu', self.plan_svg('/raumplan/kraftraum.svg'))

    def test_invalid_date_keeps_the_room(self):
        response = self.add_room_event(season='Manuell', start_date='31.02')
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="room" value="kraftraum"', response.data.decode())
        self.assertEqual(self.db_manager.count_events(self.kraft.id), 0)

    def test_new_event_can_be_copied_into_further_rooms(self):
        self.add_room_event(name='HLS Schulsport', copy_to_rooms=[str(self.ergo.id)])
        self.assertEqual(self.db_manager.count_events(self.kraft.id), 1)
        self.assertEqual(self.db_manager.count_events(self.ergo.id), 1)
        self.assertIn('HLS Schulsport', self.plan_svg('/raumplan/ergoraum.svg'))
        self.assertEqual(self.db_manager.count_events(), 0)

    def test_copies_are_independent(self):
        self.add_room_event(copy_to_rooms=[str(self.ergo.id)])
        self.db_manager.delete_all_events(self.kraft.id)
        self.assertEqual(self.db_manager.count_events(self.ergo.id), 1)

    def test_copy_option_only_exists_on_new_room_events(self):
        self.assertIn('copy_to_rooms', self.client.get('/add?room=kraftraum').data.decode())
        self.assertNotIn('copy_to_rooms', self.client.get('/add').data.decode())
        self.add_room_event()
        event = self.db_manager.get_events(self.kraft.id)[0]
        self.assertNotIn('copy_to_rooms', self.client.get(f'/edit/{event.id}').data.decode())

    def test_delete_all_only_affects_the_active_plan(self):
        self.add_event()
        self.add_room_event()
        self.add_room_event('ergoraum')
        response = self.client.post('/delete-all', data={'room': 'kraftraum'})
        self.assertTrue(response.headers['Location'].endswith('/raum/kraftraum'))
        self.assertEqual((self.db_manager.count_events(), self.db_manager.count_events(self.kraft.id), self.db_manager.count_events(self.ergo.id)), (1, 0, 1))
        self.client.post('/delete-all')
        self.assertEqual((self.db_manager.count_events(), self.db_manager.count_events(self.ergo.id)), (0, 1))

    def test_csv_goes_into_the_active_plan(self):
        csv_text = 'Name,Wochentag,Anfang,Ende\nTest,Montag,10:00,12:00\n'
        page = self.upload(csv_text, 'kraftraum').data.decode()
        self.assertIn('1 Termine angelegt', page)
        self.assertIn('Test', self.plan_svg('/raumplan/kraftraum.svg'))
        self.assertEqual(self.db_manager.count_events(), 0)

    def test_csv_export_is_limited_to_the_plan(self):
        self.add_event(name='Offenes Rudern')
        self.add_room_event(name='Kinder U15')
        response = self.client.get('/export-csv?room=kraftraum')
        self.assertIn('orvo-raum-kraftraum.csv', response.headers['Content-Disposition'])
        self.assertIn('Kinder U15', response.data.decode())
        self.assertNotIn('Offenes Rudern', response.data.decode())
        self.assertNotIn('Kinder U15', self.client.get('/export-csv').data.decode())

    def test_room_pdf_download(self):
        self.add_room_event()
        response = self.client.get('/download/raum/kraftraum.pdf?date=2026-11-01')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b'%PDF'))
        self.assertIn('raumplan-kraftraum_20261101.pdf', response.headers['Content-Disposition'])

    def test_unknown_rooms_are_not_found(self):
        for path in ('/raum/gibtsnicht', '/raumplan/gibtsnicht.svg', '/download/raum/gibtsnicht.pdf', '/add?room=gibtsnicht', '/export-csv?room=gibtsnicht'):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.post('/delete-all', data={'room': 'gibtsnicht'}).status_code, 404)

    def test_tabs_show_all_plans_in_order(self):
        page = self.client.get('/').data.decode()
        self.assertLess(page.index('/raum/kraftraum'), page.index('/raum/ergoraum'))
        self.assertIn('Stegplan', self.client.get('/raum/kraftraum').data.decode())

    def test_dashboard_shows_the_plan_specific_pdf(self):
        room = self.client.get('/raum/kraftraum').data.decode()
        self.assertIn('roomPdfModal', room)
        self.assertNotIn('data-modal-open="pdfModal"', room)
        self.assertNotIn('roomPdfModal', self.client.get('/').data.decode())


class RoomAdminTest(FrontendTestCase):
    def setUp(self):
        super().setUp()
        login(self.client)
        self.client.post('/rooms/add', data={'name': 'Kraftraum', 'sort_order': '1'})
        self.room = self.db_manager.get_room_by_slug('kraftraum')

    def test_new_room_has_an_empty_public_plan(self):
        self.client.get('/logout')
        response = self.client.get('/raumplan/kraftraum.svg')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/svg+xml')
        self.assertIn(b'Nutzungszeiten ORVO Kraftraum', response.data)
        self.assertNotIn('Content-Security-Policy', response.headers)
        response.close()

    def test_room_dashboard_and_pdf_need_a_login(self):
        self.client.get('/logout')
        for path in ('/raum/kraftraum', '/download/raum/kraftraum.pdf'):
            self.assertEqual(self.client.get(path).status_code, 302, path)

    def test_rename_keeps_the_address_and_updates_the_title(self):
        self.client.post(f'/rooms/{self.room.id}', data={'name': 'Kraftkammer', 'sort_order': '5'})
        self.assertEqual(self.room.name, 'Kraftkammer')
        self.assertEqual(self.room.sort_order, 5)
        response = self.client.get('/raumplan/kraftraum.svg')
        self.assertIn(b'Nutzungszeiten ORVO Kraftkammer', response.data)
        response.close()

    def test_invalid_names_are_rejected(self):
        for name in ('', '   ', 'x' * 101, 'Kraftraum'):
            page = self.client.post('/rooms/add', data={'name': name}, follow_redirects=True).data.decode()
            self.assertIn('bg-red-50', page, repr(name))
        self.assertEqual(len(self.db_manager.get_all_rooms()), 1)

    def test_room_cannot_take_the_name_of_another_one(self):
        self.client.post('/rooms/add', data={'name': 'Ergoraum'})
        ergo = self.db_manager.get_room_by_slug('ergoraum')
        self.client.post(f'/rooms/{ergo.id}', data={'name': 'Kraftraum', 'sort_order': '1'})
        self.assertEqual(ergo.name, 'Ergoraum')

    def test_keeping_the_own_name_is_allowed(self):
        self.client.post(f'/rooms/{self.room.id}', data={'name': 'Kraftraum', 'sort_order': '9'})
        self.assertEqual(self.room.sort_order, 9)

    def test_delete_removes_room_events_and_file_but_not_the_stegplan(self):
        self.add_event(name='Offenes Rudern')
        self.add_event(name='Kinder U15', room='kraftraum')
        self.client.post(f'/rooms/delete/{self.room.id}')
        self.assertEqual(self.db_manager.get_all_rooms(), [])
        self.assertEqual(self.db_manager.count_events(), 1)
        self.assertEqual(self.client.get('/raumplan/kraftraum.svg').status_code, 404)
        self.assertEqual(self.client.get('/raum/kraftraum').status_code, 404)

    def test_regular_users_cannot_manage_rooms(self):
        self.client.post('/users/add', data={'username': 'steg', 'password': 'steg-password'})
        self.client.get('/logout')
        login(self.client, 'steg', 'steg-password')
        self.assertEqual(self.client.get('/rooms').status_code, 302)
        self.client.post('/rooms/add', data={'name': 'Fremd'})
        self.client.post(f'/rooms/{self.room.id}', data={'name': 'Fremd', 'sort_order': '1'})
        self.client.post(f'/rooms/delete/{self.room.id}')
        self.assertEqual([room.name for room in self.db_manager.get_all_rooms()], ['Kraftraum'])
        self.assertNotIn('/rooms"', self.client.get('/').data.decode())

    def test_regular_users_can_maintain_room_events(self):
        self.client.post('/users/add', data={'username': 'steg', 'password': 'steg-password'})
        steg = self.db_manager.get_user_by_username('steg')
        self.client.post(f'/rooms/{self.room.id}', data={'name': 'Kraftraum', 'sort_order': '1', 'managers': [str(steg.id)]})
        self.client.get('/logout')
        login(self.client, 'steg', 'steg-password')
        self.add_event(room='kraftraum')
        self.assertEqual(self.db_manager.count_events(self.room.id), 1)


class StylesheetTest(unittest.TestCase):
    def test_all_template_classes_exist_in_the_built_stylesheet(self):
        with open(os.path.join(ROOT, 'static', 'style.css'), encoding='utf-8') as f:
            css = f.read()
        for path in glob.glob(os.path.join(ROOT, 'templates', '*.html')):
            with open(path, encoding='utf-8') as f:
                source = f.read()
            for value in re.findall(r'class="([^"]*)"', source) + re.findall(r"_tab = '([^']*)'", source):
                # Keep class names inside template expressions, drop the compared values
                value = re.sub(r"==\s*'[^']*'", ' ', value).replace("'", ' ')
                value = re.sub(r'\{[{%]|[%}]\}', ' ', value)
                for name in value.split():
                    if '-' in name or name in ('flex', 'grid', 'hidden', 'block', 'border', 'shadow', 'transition'):
                        selector = '.' + name.replace('.', r'\.').replace(':', r'\:')
                        self.assertIn(selector, css, f'{os.path.basename(path)}: {name}')


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, 'old.db')
        connection = sqlite3.connect(self.path)
        connection.execute('''CREATE TABLE event (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, weekday VARCHAR(20) NOT NULL,
            start_time VARCHAR(10) NOT NULL, end_time VARCHAR(10) NOT NULL, season VARCHAR(20), start_date VARCHAR(5), end_date VARCHAR(5),
            supervisor1 VARCHAR(50), supervisor2 VARCHAR(50), supervisor3 VARCHAR(50), comment VARCHAR(200))''')
        connection.execute("INSERT INTO event (name, weekday, start_time, end_time) VALUES ('Offenes Rudern', 'Montag', '10:00', '12:00')")
        connection.commit()
        connection.close()

    def tearDown(self):
        self.directory.cleanup()

    def test_old_table_is_extended_and_keeps_its_data(self):
        for _ in range(2):  # The second start must not fail on the existing column
            app, db_manager = create_test_app(f'sqlite:///{self.path}')
            with app.app_context():
                self.assertIn('room_id', [column['name'] for column in inspect(db.engine).get_columns('event')])
                self.assertEqual([event.name for event in db_manager.get_events()], ['Offenes Rudern'])
                db.session.remove()
                db.engine.dispose()


if __name__ == '__main__':
    unittest.main()

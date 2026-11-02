import os
import re
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

from database import db
from helpers import create_test_app, login, make_event, make_generator
from test_frontend import FrontendTestCase

DATE = datetime(2026, 11, 1)
KRAFT = SimpleNamespace(name='Kraftraum', slug='kraftraum')
ERGO = SimpleNamespace(name='Ergoraum', slug='ergoraum')


def texts(svg):
    return [re.sub(r'&amp;', '&', text) for text in re.findall(r'<text [^>]*>([^<]*)</text>', svg)]


def rows(svg):
    """Returns the texts of each table row by its vertical position."""
    found = {}
    for x, y, text in re.findall(r'<text x="(\d+)" y="(\d+)" class="cell-text"[^>]*>([^<]*)<', svg):
        found.setdefault(int(y), []).append((int(x), text))
    return [[text for _, text in sorted(found[y])] for y in sorted(found)]


class OverviewContentTest(unittest.TestCase):
    def setUp(self):
        self.gen = make_generator()

    def render(self, plans, notes='', date=DATE):
        return self.gen.generate_overview_svg_string(plans, notes, date)

    def test_layout_matches_the_template(self):
        svg = self.render([(None, [make_event()])])
        for text in ('Tag', 'Uhrzeit', 'Gruppe', 'Ansprechpartner*in'):
            self.assertIn(text, texts(svg))
        for color in ('#1d3b87', '#c92626', '#e0e0e0', '#f0f4fa'):
            self.assertIn(color, svg)

    def test_table_text_is_pure_black(self):
        self.assertIn('.cell-text { fill: #000000;', self.render([(None, [make_event()])]))

    def test_stegplan_comes_first_and_rooms_keep_their_order(self):
        svg = self.render([(None, [make_event()]), (KRAFT, [make_event()]), (ERGO, [make_event()])])
        sections = [text for text in texts(svg) if text.isupper() and text != 'HINWEISE:']
        self.assertEqual(sections, ['STEG', 'KRAFTRAUM', 'ERGORAUM'])

    def test_plans_without_active_events_are_left_out(self):
        inactive = make_event(season='Sommer')
        svg = self.render([(None, []), (KRAFT, [inactive]), (ERGO, [make_event()])])
        self.assertEqual([text for text in texts(svg) if text.isupper()], ['ERGORAUM'])

    def test_inactive_events_are_left_out(self):
        svg = self.render([(None, [make_event(name='Winter', season='Winter'), make_event(name='Sommer', season='Sommer')])])
        self.assertIn('Winter', ' '.join(texts(svg)))
        self.assertNotIn('Sommer', ' '.join(texts(svg)))

    def test_rows_are_sorted_and_show_the_day_once(self):
        events = [
            make_event('18:00', '19:00', weekday='Dienstag', name='C'),
            make_event('12:00', '13:00', weekday='Montag', name='B'),
            make_event('08:00', '09:00', weekday='Montag', name='A', supervisor1='Heini', supervisor2='Peter'),
        ]
        self.assertEqual(rows(self.render([(None, events)])), [
            ['Montag', '08:00 – 09:00', 'A', 'Heini, Peter'],
            ['12:00 – 13:00', 'B', '-'],
            ['Dienstag', '18:00 – 19:00', 'C', '-'],
        ])

    def test_comment_follows_the_name_in_brackets(self):
        svg = self.render([(None, [make_event(name='Junioren', comment='bei Schlechtwetter')])])
        self.assertIn('Junioren (bei Schlechtwetter)', texts(svg))

    def test_long_groups_wrap_and_grow_the_row(self):
        short = self.render([(None, [make_event()])])
        long = self.render([(None, [make_event(name='Team Rowing', comment='Team Rowing mit Martin oder Peter und weiteren Personen')])])
        height = lambda svg: int(re.search(r'<svg width="800" height="(\d+)"', svg).group(1))
        self.assertEqual(height(long), height(short) + 18)
        self.assertTrue(all(len(text) <= 38 for text in texts(long) if 'Rowing' in text))

    def test_height_follows_the_content(self):
        one = self.render([(None, [make_event()])])
        self.assertIn('height="165" viewBox="0 0 800 165"', one)
        two = self.render([(None, [make_event(), make_event('12:00', '13:00')])])
        self.assertIn('height="195" viewBox="0 0 800 195"', two)

    def test_title_names_the_season(self):
        cases = {
            datetime(2026, 7, 1): 'Nutzungszeiten ORVO (Sommer 2026)',
            datetime(2026, 11, 1): 'Nutzungszeiten ORVO (Winter 2026/2027)',
            datetime(2027, 1, 15): 'Nutzungszeiten ORVO (Winter 2026/2027)',
            datetime(2027, 3, 31): 'Nutzungszeiten ORVO (Sommer 2027)',
        }
        for date, title in cases.items():
            self.assertIn(title, texts(self.render([], date=date)))

    def test_invalid_phase_config_keeps_a_title(self):
        svg = make_generator(summer='kaputt').generate_overview_svg_string([], '', DATE)
        self.assertIn('Nutzungszeiten ORVO', texts(svg))

    def test_notes_become_bullets_and_empty_lines_are_dropped(self):
        svg = self.render([], 'Erster Hinweis\n\n   \n• Zweiter Hinweis')
        self.assertIn('HINWEISE:', texts(svg))
        self.assertIn('• Erster Hinweis', texts(svg))
        self.assertIn('• Zweiter Hinweis', texts(svg))

    def test_long_notes_wrap(self):
        svg = self.render([], 'Wort ' * 40)
        self.assertGreater(len([text for text in texts(svg) if 'Wort' in text]), 1)

    def test_no_notes_no_heading(self):
        self.assertNotIn('HINWEISE:', texts(self.render([], '  \n ')))

    def test_all_texts_are_escaped(self):
        room = SimpleNamespace(name='<b>', slug='x')
        svg = self.render([(room, [make_event(name='A & B', comment='<i>', supervisor1='<u>')])], '<s>')
        for raw in ('<b>', '<i>', '<u>', '<s>', 'A & B'):
            self.assertNotIn(raw, svg)


class OverviewPathTest(unittest.TestCase):
    def test_default_is_next_to_the_room_plans(self):
        gen = make_generator()
        gen.config['svg_output_path'] = '/srv/plans/stegplan.svg'
        self.assertEqual(gen.get_overview_svg_path(), '/srv/plans/nutzungszeiten.svg')
        gen.config['room_output_dir'] = '/srv/rooms'
        self.assertEqual(gen.get_overview_svg_path(), '/srv/rooms/nutzungszeiten.svg')

    def test_config_can_name_the_file(self):
        gen = make_generator()
        gen.config['overview_output_path'] = '/var/www/res/26-nutzungszeiten.svg'
        self.assertEqual(gen.get_overview_svg_path(), '/var/www/res/26-nutzungszeiten.svg')


class OverviewRoutesTest(FrontendTestCase):
    def setUp(self):
        super().setUp()
        login(self.client)

    def public_svg(self):
        response = self.client.get('/nutzungszeiten.svg')
        self.assertEqual(response.status_code, 200)
        data = response.data.decode()
        response.close()
        return data

    def test_overview_is_public(self):
        self.add_event()
        self.client.get('/logout')
        response = self.client.get('/nutzungszeiten.svg')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/svg+xml')
        self.assertNotIn('Content-Security-Policy', response.headers)
        response.close()

    def test_overview_page_needs_a_login(self):
        self.client.get('/logout')
        self.assertEqual(self.client.get('/uebersicht').status_code, 302)

    def test_changes_in_every_plan_update_the_overview(self):
        self.client.post('/rooms/add', data={'name': 'Kraftraum', 'sort_order': '1'})
        self.add_event(name='Offenes Rudern')
        self.add_event(name='Kinder U15', room='kraftraum')
        svg = self.public_svg()
        self.assertIn('STEG', svg)
        self.assertIn('KRAFTRAUM', svg)
        self.assertIn('Offenes Rudern', svg)
        self.assertIn('Kinder U15', svg)

        event = self.db_manager.get_events(self.db_manager.get_room_by_slug('kraftraum').id)[0]
        self.client.post(f'/edit/{event.id}', data={'name': 'Handicap', 'weekday': 'Montag', 'start_time': '10:00', 'end_time': '12:00', 'season': 'Immer'})
        self.assertIn('Handicap', self.public_svg())
        self.assertNotIn('Kinder U15', self.public_svg())

        self.client.post(f'/delete/{event.id}')
        self.assertNotIn('Handicap', self.public_svg())

    def test_room_changes_update_the_overview(self):
        self.client.post('/rooms/add', data={'name': 'Kraftraum', 'sort_order': '1'})
        room = self.db_manager.get_room_by_slug('kraftraum')
        self.add_event(room='kraftraum')
        self.client.post(f'/rooms/{room.id}', data={'name': 'Kraftkammer', 'sort_order': '1', 'show_in_overview': '1'})
        self.assertIn('KRAFTKAMMER', self.public_svg())
        self.client.post(f'/rooms/delete/{room.id}')
        self.assertNotIn('KRAFTKAMMER', self.public_svg())

    def test_default_notes_come_from_the_template(self):
        self.add_event()
        self.assertIn('Vorrang', self.public_svg())
        self.assertIn('Rutschgefahr', self.client.get('/uebersicht').data.decode())

    def test_admin_changes_the_notes(self):
        self.add_event()
        response = self.client.post('/uebersicht/notes', data={'notes': 'Bitte Fenster schließen'}, follow_redirects=True)
        self.assertIn('gespeichert', response.data.decode())
        svg = self.public_svg()
        self.assertIn('Bitte Fenster schließen', svg)
        self.assertNotIn('Vorrang', svg)

    def test_notes_can_be_removed(self):
        self.client.post('/uebersicht/notes', data={'notes': ''})
        self.assertNotIn('HINWEISE', self.public_svg())

    def test_regular_users_see_the_overview_but_cannot_change_notes(self):
        self.add_event()
        self.client.post('/users/add', data={'username': 'steg', 'password': 'steg-password'})
        self.client.get('/logout')
        login(self.client, 'steg', 'steg-password')
        page = self.client.get('/uebersicht').data.decode()
        self.assertIn('/nutzungszeiten.svg', page)
        self.assertNotIn('<textarea', page)
        self.client.post('/uebersicht/notes', data={'notes': 'Fremd'})
        self.assertNotIn('Fremd', self.public_svg())

    def test_tabs_are_shown_without_rooms(self):
        self.assertIn('/uebersicht', self.client.get('/').data.decode())

    def test_overview_page_has_no_plan_actions(self):
        page = self.client.get('/uebersicht').data.decode()
        self.assertNotIn('import-form', page)
        self.assertNotIn('data-modal-open', page)
        self.assertIn('import-form', self.client.get('/').data.decode())

    def test_configured_file_name_is_used(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, '26-nutzungszeiten.svg')
        app, _ = create_test_app(overview_output_path=path)
        with app.app_context():
            client = app.test_client()
            login(client)
            client.post('/add', data={'name': 'Test', 'weekday': 'Montag', 'start_time': '10:00', 'end_time': '12:00', 'season': 'Immer'})
            self.assertTrue(os.path.exists(path))
            response = client.get('/nutzungszeiten.svg')
            self.assertIn(b'Nutzungszeiten ORVO', response.data)
            response.close()
            db.session.remove()
            db.engine.dispose()

    def test_failing_overview_does_not_block_saving(self):
        app, db_manager = create_test_app(overview_output_path='/proc/gibt/es/nicht/uebersicht.svg')
        with app.app_context():
            client = app.test_client()
            login(client)
            with self.assertLogs('frontend', level='ERROR'):
                response = client.post('/add', data={'name': 'Test', 'weekday': 'Montag', 'start_time': '10:00', 'end_time': '12:00', 'season': 'Immer'})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(db_manager.count_events(), 1)
            db.session.remove()
            db.engine.dispose()


class SettingTest(FrontendTestCase):
    def test_settings_are_stored_and_replaced(self):
        self.assertEqual(self.db_manager.get_setting('x', 'default'), 'default')
        self.db_manager.set_setting('x', 'eins')
        self.db_manager.set_setting('x', 'zwei')
        self.assertEqual(self.db_manager.get_setting('x', 'default'), 'zwei')

    def test_plans_are_listed_in_display_order(self):
        second = self.db_manager.add_room('Zweiter', 2)
        first = self.db_manager.add_room('Erster', 1)
        self.assertEqual([room for room, _ in self.db_manager.get_overview_plans()], [None, first, second])


if __name__ == '__main__':
    unittest.main()

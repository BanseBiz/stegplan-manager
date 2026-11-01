import io
import unittest

from csv_handler import CsvHandler
from helpers import login
from test_frontend import FrontendTestCase

HEADER = 'Name,Wochentag,Anfang,Ende,Saison,Startdatum,Enddatum,Betreuer 1,Betreuer 2,Betreuer 3,Kommentar\n'
ROW = 'Offenes Rudern,Montag,10:00,12:00,Immer,,,Heini,,,\n'


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.handler = CsvHandler()

    def parse(self, text, encoding='utf-8'):
        return self.handler.parse_csv_to_events(text.encode(encoding))

    def test_valid_row(self):
        events, errors = self.parse(HEADER + ROW)
        self.assertEqual(errors, [])
        self.assertEqual(events[0]['name'], 'Offenes Rudern')
        self.assertEqual(events[0]['supervisor1'], 'Heini')

    def test_excel_time_format_is_normalized(self):
        events, errors = self.parse('Name,Wochentag,Anfang,Ende\nTest,Montag,05:15:00 PM,9:45:00 AM\n')
        self.assertEqual(errors, [])
        self.assertEqual((events[0]['start_time'], events[0]['end_time']), ('17:15', '09:45'))

    def test_semicolon_file_from_german_excel(self):
        events, errors = self.parse((HEADER + ROW).replace(',', ';'))
        self.assertEqual((len(events), errors), (1, []))

    def test_comma_inside_a_quoted_comment_keeps_the_delimiter(self):
        events, errors = self.parse(HEADER + 'Test,Montag,10:00,12:00,,,,,,,"a, b"\n')
        self.assertEqual(errors, [])
        self.assertEqual(events[0]['comment'], 'a, b')

    def test_encodings(self):
        text = HEADER + 'Tür,Montag,10:00,12:00,,,,,,,\n'
        for encoding in ('utf-8', 'utf-8-sig', 'cp1252'):
            events, errors = self.parse(text, encoding)
            self.assertEqual(errors, [], encoding)
            self.assertEqual(events[0]['name'], 'Tür', encoding)

    def test_short_rows_and_missing_columns_get_defaults(self):
        events, errors = self.parse(HEADER + 'Test,Montag,10:00,12:00\n')
        self.assertEqual(errors, [])
        self.assertEqual(events[0]['season'], 'Immer')
        self.assertEqual(events[0]['comment'], '')

    def test_rows_longer_than_the_header_are_accepted(self):
        events, errors = self.parse(HEADER + ROW.strip() + ',zu,viel\n')
        self.assertEqual((len(events), errors), (1, []))

    def test_empty_rows_are_skipped(self):
        events, errors = self.parse(HEADER + '\n,,,,,,,,,,\n' + ROW + ' , , \n')
        self.assertEqual((len(events), errors), (1, []))

    def test_invalid_values_are_reported_with_their_line(self):
        cases = {
            'Test,Mo,10:00,12:00': ('csv_error_weekday', 'Mo'),
            'Test,Montag,25:99,12:00': ('csv_error_time', '25:99'),
            'Test,Montag,10:00,mittags': ('csv_error_time', 'mittags'),
            'Test,Montag,10:00,12:00,Frühling': ('csv_error_season', 'Frühling'),
            'Test,Montag,10:00,12:00,Manuell,31.02,': ('csv_error_date', '31.02'),
            ',Montag,10:00,12:00': ('csv_error_required', ''),
        }
        for row, (key, value) in cases.items():
            events, errors = self.parse(HEADER + ROW + row + '\n')
            self.assertEqual(errors, [(3, key, value)], row)

    def test_missing_required_column(self):
        self.assertEqual(self.parse('Name,Wochentag\nTest,Montag\n'), ([], [(1, 'csv_error_columns', '')]))
        self.assertEqual(self.parse(''), ([], [(1, 'csv_error_columns', '')]))


class ImportRouteTest(FrontendTestCase):
    def setUp(self):
        super().setUp()
        login(self.client)

    def upload(self, text, filename='plan.csv', encoding='utf-8'):
        data = {'csv_file': (io.BytesIO(text.encode(encoding)), filename)}
        return self.client.post('/import-csv', data=data, content_type='multipart/form-data', follow_redirects=True).data.decode()

    def test_import_reports_the_result_and_generates_the_plans(self):
        page = self.upload(HEADER + ROW)
        self.assertIn('1 Termine angelegt, 0 bereits vorhandene', page)
        self.assertEqual(len(self.db_manager.get_events()), 1)
        response = self.client.get('/stegplan.svg')
        self.assertIn(b'Offenes Rudern', response.data)
        response.close()

    def test_second_import_adds_nothing(self):
        self.upload(HEADER + ROW)
        page = self.upload(HEADER + ROW)
        self.assertIn('0 Termine angelegt, 1 bereits vorhandene', page)
        self.assertEqual(len(self.db_manager.get_events()), 1)

    def test_duplicates_inside_a_file_are_skipped(self):
        page = self.upload(HEADER + ROW + ROW)
        self.assertIn('1 Termine angelegt, 1 bereits vorhandene', page)

    def test_changed_event_is_added(self):
        self.upload(HEADER + ROW)
        self.upload(HEADER + ROW.replace('Heini', 'Peter'))
        self.assertEqual(len(self.db_manager.get_events()), 2)

    def test_stored_dates_only_distinguish_manual_events(self):
        self.upload(HEADER + 'Test,Montag,10:00,12:00,Sommer,31.03,27.10\nTest,Montag,10:00,12:00,Manuell,01.05,30.09\n')
        page = self.upload(HEADER + 'Test,Montag,10:00,12:00,Sommer,29.03,25.10\nTest,Montag,10:00,12:00,Manuell,01.06,30.09\n')
        self.assertIn('1 Termine angelegt, 1 bereits vorhandene', page)

    def test_export_can_be_imported_again_without_changes(self):
        self.upload(HEADER + ROW + 'Handicap,Mittwoch,18:00,20:00,Sommer,31.03,27.10,Jens,,,"für alle, die wollen"\n')
        exported = self.client.get('/export-csv').data.decode()
        page = self.upload(exported)
        self.assertIn('0 Termine angelegt, 2 bereits vorhandene', page)

    def test_a_single_invalid_row_rejects_the_whole_file(self):
        page = self.upload(HEADER + ROW + 'Test,Mo,10:00,12:00\n')
        self.assertIn('Zeile 3', page)
        self.assertEqual(self.db_manager.get_events(), [])

    def test_long_error_lists_are_shortened(self):
        page = self.upload(HEADER + 'Test,Mo,10:00,12:00\n' * 8)
        self.assertIn('Zeile 6', page)
        self.assertNotIn('Zeile 7', page)
        self.assertIn('3 weitere Fehler', page)

    def test_file_extension_is_case_insensitive(self):
        self.upload(HEADER + ROW, filename='PLAN.CSV')
        self.assertEqual(len(self.db_manager.get_events()), 1)

    def test_other_files_are_rejected(self):
        page = self.upload(HEADER + ROW, filename='plan.txt')
        self.assertIn('Endung .csv', page)
        self.assertEqual(self.db_manager.get_events(), [])


if __name__ == '__main__':
    unittest.main()

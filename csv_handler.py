import csv
import io
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

WEEKDAYS = ('Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag')
SEASONS = ('Immer', 'Sommer', 'Winter', 'Manuell')
REQUIRED_COLUMNS = ('Name', 'Wochentag', 'Anfang', 'Ende')

class CsvHandler:
    """Handles import and export of event data via CSV."""

    def normalize_time(self, time_str):
        """Converts various time formats to 24h HH:MM format."""
        time_str = str(time_str).strip()
        if not time_str:
            return ""
        formats = ["%I:%M:%S %p", "%H:%M:%S", "%H:%M", "%I:%M %p"]
        for fmt in formats:
            try:
                return datetime.strptime(time_str, fmt).strftime("%H:%M")
            except ValueError:
                continue
        return time_str

    def is_valid_time(self, time_str):
        """Validates if a string is a real time in HH:MM format."""
        try:
            datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False

    def is_valid_date(self, date_str):
        """Validates if a string strictly matches DD.MM and is a real calendar date."""
        if not date_str:
            return True
        if not re.match(r'^(0[1-9]|[12][0-9]|3[01])\.(0[1-9]|1[012])$', date_str):
            return False
        try:
            # Append a leapyear (2000) as that 29.02. is acceped as valid
            datetime.strptime(f"{date_str}.2000", '%d.%m.%Y')
            return True
        except ValueError:
            return False

    def decode_csv(self, file_content_bytes):
        """Decodes CSV bytes, falling back to the encoding of a German Excel."""
        try:
            # utf-8-sig automatically removes a potential BOM (Byte Order Mark) from Excel
            return file_content_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            return file_content_bytes.decode("cp1252", errors="replace")

    def parse_csv_to_events(self, file_content_bytes):
        """Parses CSV bytes into event dictionaries and a list of (line, error key, value) errors."""
        text = self.decode_csv(file_content_bytes)
        header = text.split('\n', 1)[0]
        delimiter = ';' if header.count(';') > header.count(',') else ','
        reader = csv.DictReader(io.StringIO(text, newline=None), delimiter=delimiter)

        if not reader.fieldnames or any(column not in reader.fieldnames for column in REQUIRED_COLUMNS):
            return [], [(1, 'csv_error_columns', '')]

        events_to_add = []
        errors = []
        for row in reader:
            # Columns beyond the header end up under the key None
            row.pop(None, None)
            values = {key: (value or '').strip() for key, value in row.items()}
            if not any(values.values()):
                continue

            line = reader.line_num
            event = {
                'name': values.get('Name', ''),
                'weekday': values.get('Wochentag', ''),
                'start_time': self.normalize_time(values.get('Anfang', '')),
                'end_time': self.normalize_time(values.get('Ende', '')),
                'season': values.get('Saison', '') or 'Immer',
                'start_date': values.get('Startdatum', ''),
                'end_date': values.get('Enddatum', ''),
                'supervisor1': values.get('Betreuer 1', ''),
                'supervisor2': values.get('Betreuer 2', ''),
                'supervisor3': values.get('Betreuer 3', ''),
                'comment': values.get('Kommentar', '')
            }

            row_errors = self.validate_event(event)
            errors.extend((line, key, value) for key, value in row_errors)
            if not row_errors:
                events_to_add.append(event)
        logger.info(f"Parsed {len(events_to_add)} events from CSV, {len(errors)} errors.")
        return events_to_add, errors

    def validate_event(self, event):
        """Returns the (error key, value) pairs of an event parsed from CSV."""
        if not all(event[key] for key in ('name', 'weekday', 'start_time', 'end_time')):
            return [('csv_error_required', '')]

        errors = []
        if event['weekday'] not in WEEKDAYS:
            errors.append(('csv_error_weekday', event['weekday']))
        for key in ('start_time', 'end_time'):
            if not self.is_valid_time(event[key]):
                errors.append(('csv_error_time', event[key]))
        if event['season'] not in SEASONS:
            errors.append(('csv_error_season', event['season']))
        for key in ('start_date', 'end_date'):
            if not self.is_valid_date(event[key]):
                errors.append(('csv_error_date', event[key]))
        return errors

    def generate_csv_from_events(self, events):
        """Generates a CSV string from a list of event objects."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Name', 'Wochentag', 'Anfang', 'Ende', 'Saison', 'Startdatum', 'Enddatum', 'Betreuer 1', 'Betreuer 2', 'Betreuer 3', 'Kommentar'])

        for ev in events:
            writer.writerow([
                ev.name, ev.weekday, ev.start_time, ev.end_time,
                getattr(ev, 'season', 'Immer'), getattr(ev, 'start_date', ''), getattr(ev, 'end_date', ''),
                ev.supervisor1, ev.supervisor2, ev.supervisor3, ev.comment
            ])
        logger.info(f"Generated CSV containing {len(events)} events.")
        return output.getvalue()

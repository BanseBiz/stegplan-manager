import csv
import io
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

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

    def parse_csv_to_events(self, file_content_bytes):
        """Parses CSV bytes into a list of event dictionaries."""
        # utf-8-sig automatically removes a potential BOM (Byte Order Mark) from Excel
        stream = io.StringIO(file_content_bytes.decode("utf-8-sig"), newline=None)
        reader = csv.DictReader(stream)
        
        events_to_add = []
        for row in reader:
            # Check if minimum requirements are present in the row
            if not row.get('Name') or not row.get('Wochentag') or not row.get('Anfang') or not row.get('Ende'):
                continue
                
            events_to_add.append({
                'name': row.get('Name', '').strip(),
                'weekday': row.get('Wochentag', '').strip(),
                'start_time': self.normalize_time(row.get('Anfang', '')),
                'end_time': self.normalize_time(row.get('Ende', '')),
                'season': row.get('Saison', 'Immer').strip(),
                'start_date': row.get('Startdatum', '').strip(),
                'end_date': row.get('Enddatum', '').strip(),
                'supervisor1': row.get('Betreuer 1', '').strip(),
                'supervisor2': row.get('Betreuer 2', '').strip(),
                'supervisor3': row.get('Betreuer 3', '').strip(),
                'comment': row.get('Kommentar', '').strip()
            })
        logger.info(f"Successfully parsed {len(events_to_add)} events from CSV.")
        return events_to_add

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
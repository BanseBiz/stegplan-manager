import os
import html
import io
import cairosvg
import logging
import math
from datetime import datetime
import pyphen
from csv_handler import WEEKDAYS

logger = logging.getLogger(__name__)

class DocumentGenerator:
    """Handles generation of SVG and PDF documents."""

    def __init__(self, config, loc):
        self.config = config
        # Initialize Pyphen for German hyphenation
        self.dic = pyphen.Pyphen(lang='de_DE')
        self.loc = loc

    def wrap_text(self, text, max_len):
        """Wraps text after a certain number of characters."""
        words = text.split()
        lines, cur_line = [], ""
        for w in words:
            if cur_line and len(cur_line) + len(w) > max_len:
                lines.append(cur_line.strip())
                cur_line = w + " "
            else:
                cur_line += w + " "
        if cur_line: 
            lines.append(cur_line.strip())
        return lines

    def wrap_text_with_hyphens(self, text, max_len):
        """Wraps text at spaces. Words that are too long are hyphenated."""
        words = text.split()
        lines = []
        cur_line = ""
        for w in words:
            if len(cur_line) + len(w) + (1 if cur_line else 0) <= max_len:
                cur_line += (" " if cur_line else "") + w
            else:
                if cur_line:
                    lines.append(cur_line)
                    cur_line = ""
                while len(w) > max_len:
                    positions = self.dic.positions(w)
                    valid_pos = [p for p in positions if p < max_len]
                    if valid_pos:
                        split_idx = valid_pos[-1] # Last possible split position before max_len
                    else:
                        split_idx = max_len - 1 # Fallback if no syllable was found
                    lines.append(w[:split_idx] + "-")
                    w = w[split_idx:]
                cur_line = w
        if cur_line:
            lines.append(cur_line)
        return lines

    def get_phase_starts(self):
        """Returns the configured summer and winter start as (month, day) tuples."""
        starts = []
        for key, default in (('sommerphase_start', '31.03'), ('winterphase_start', '27.10')):
            # Append a leap year (2000) so that 29.02 is accepted as valid
            parsed = datetime.strptime(f"{self.config.get(key, default)}.2000", "%d.%m.%Y")
            starts.append((parsed.month, parsed.day))
        return starts

    def is_summer_phase(self, date):
        """Checks if a date is in the summer phase. A start date belongs to the phase it starts."""
        summer_start, winter_start = self.get_phase_starts()
        return summer_start <= (date.month, date.day) < winter_start

    def get_season(self, date):
        """Returns the phase of a date and the year it started in. Fails on an invalid phase config."""
        if self.is_summer_phase(date):
            return 'summer', date.year
        # The winter phase spans the turn of the year and keeps the year it started in
        summer_start, _ = self.get_phase_starts()
        return 'winter', date.year - 1 if (date.month, date.day) < summer_start else date.year

    def get_base_title(self, date):
        """Returns the plan title for the season of the given date."""
        try:
            phase, year = self.get_season(date)
            return self.loc.get(f'title_{phase}', year)
        except ValueError:
            return self.loc.get('title_default', date.year)

    def get_overview_title(self, date):
        """Returns the overview title with the season of the given date."""
        try:
            phase, year = self.get_season(date)
        except ValueError:
            return self.loc.get('title_overview_plain')
        season = self.loc.get('season_label_summer', year) if phase == 'summer' else self.loc.get('season_label_winter', year, year + 1)
        return self.loc.get('title_overview', season)

    def is_event_active(self, ev, target_date=None):
        """Checks if an event is active on the selected date (regardless of the year)."""
        now = target_date if target_date else datetime.now()
        if getattr(ev, 'season') in ('Sommer', 'Winter'):
            # Seasonal events always follow the configured phases, not their stored dates
            try:
                return self.is_summer_phase(now) == (ev.season == 'Sommer')
            except ValueError:
                return True
        if not getattr(ev, 'season') or ev.season == 'Immer' or not getattr(ev, 'start_date') or not getattr(ev, 'end_date'):
            return True
        try:
            start_month, start_day = int(ev.start_date[3:5]), int(ev.start_date[0:2])
            end_month, end_day = int(ev.end_date[3:5]), int(ev.end_date[0:2])
            current_month, current_day = now.month, now.day

            start_tuple = (start_month, start_day)
            end_tuple = (end_month, end_day)
            current_tuple = (current_month, current_day)

            if start_tuple <= end_tuple:
                return start_tuple <= current_tuple <= end_tuple
            else:
                # Year change (e.g. Winter from 27.10 to 31.03)
                return current_tuple >= start_tuple or current_tuple <= end_tuple
        except Exception:
            return True

    def get_card_layout(self, ev):
        """Returns the name, supervisor and comment lines and the height of a stegplan card."""
        name_lines = self.wrap_text_with_hyphens(ev['name'], 17)

        supervisor_list = [v.strip() for k, v in ev.items() if k.startswith('supervisor') and v.strip()]
        supervisor_lines = []
        if supervisor_list:
            supervisor_str = " & ".join(supervisor_list)
            if len(supervisor_str) > 18:
                supervisor_lines = [b + " &" if i < len(supervisor_list)-1 else b for i, b in enumerate(supervisor_list)]
            else:
                supervisor_lines = [supervisor_str]

        comment_lines = self.wrap_text(ev.get('comment', ''), 23)

        card_height = 150 + (len(name_lines) - 1) * 46
        if supervisor_lines: card_height += 10 + len(supervisor_lines) * 40
        if comment_lines: card_height += 15 + len(comment_lines) * 40
        return name_lines, supervisor_lines, comment_lines, card_height

    def generate_stegplan_svg_string(self, events, target_date=None, orientation='portrait', custom_title_date=False):
        """Generates a stegplan layout as an SVG string."""
        active_events = [e for e in events if self.is_event_active(e, target_date=target_date)]
        
        days = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
        day_events = {day: [] for day in days}
        
        for e in active_events:
            if getattr(e, 'weekday', '') in day_events:
                day_events[e.weekday].append(e.to_dict())
                
        for day in days:
            day_events[day] = sorted(day_events[day], key=lambda x: x['start_time'])

        # Layout constants
        COL_W, GAP, MARGIN_X, MARGIN_Y, CARD_GAP = 420, 15, 60, 120, 12
        
        if orientation == 'landscape':
            TOTAL_W = MARGIN_X * 2 + 7 * COL_W + 6 * GAP
        else:
            TOTAL_W = MARGIN_X * 2 + 4 * COL_W + 3 * GAP

        def get_col_height(day):
            y = 85 + CARD_GAP
            for ev in day_events[day]:
                y += self.get_card_layout(ev)[3] + CARD_GAP
            return y

        if orientation == 'portrait':
            row1_height = max([get_col_height(d) for d in days[:4]])
            start_y_row1 = MARGIN_Y
            start_y_row2 = start_y_row1 + row1_height + 80
        else:
            start_y_row1 = MARGIN_Y
            start_y_row2 = MARGIN_Y
            
        max_total_y = 0

        # Determine season phase (Summer/Winter) for title
        now = target_date if target_date else datetime.now()
        base_title = self.get_base_title(now)

        if custom_title_date:
            title_text = self.loc.get('title_valid_from', base_title, now.strftime('%d.%m.'))
        else:
            title_text = base_title

        if orientation == 'landscape':
            svg = [f'<svg viewBox="0 0 {TOTAL_W} HEIGHT_PLACEHOLDER" width="297mm" height="210mm" xmlns="http://www.w3.org/2000/svg">']
        else:
            svg = [f'<svg viewBox="0 0 {TOTAL_W} HEIGHT_PLACEHOLDER" width="210mm" height="297mm" xmlns="http://www.w3.org/2000/svg">']

        svg.append('<defs><style>.bg { fill: #f8fafc; } .header-bg { fill: #1e293b; rx: 16px; } .day-title { font-family: "Segoe UI", Arial, sans-serif; font-size: 38px; font-weight: bold; fill: #ffffff; text-anchor: middle; } .card-bg { fill: #ffffff; stroke: #cbd5e1; stroke-width: 3px; rx: 20px; } .time-text { font-family: "Segoe UI", Arial, sans-serif; font-size: 36px; font-weight: 800; fill: #475569; letter-spacing: -0.5px; } .event-title { font-family: "Segoe UI", Arial, sans-serif; font-size: 38px; font-weight: 900; fill: #0f172a; letter-spacing: -0.5px; } .event-sub { font-family: "Segoe UI", Arial, sans-serif; font-size: 30px; font-weight: 700; fill: #64748b; } .event-extra { font-family: "Segoe UI", Arial, sans-serif; font-size: 28px; font-weight: 600; fill: #94a3b8; font-style: italic; } .main-title { font-family: "Segoe UI", Arial, sans-serif; font-size: 56px; font-weight: 900; fill: #0f172a; text-anchor: middle; }</style>')
        svg.append('<filter id="shadow" x="-5%" y="-5%" width="110%" height="110%"><feDropShadow dx="0" dy="6" stdDeviation="6" flood-color="#000000" flood-opacity="0.08"/></filter></defs>')
        svg.append(f'<rect width="{TOTAL_W}" height="HEIGHT_PLACEHOLDER" class="bg" />')
        
        svg.append(f'<text x="{TOTAL_W / 2}" y="70" class="main-title">{title_text}</text>')

        for i, day in enumerate(days):
            if orientation == 'landscape':
                x = MARGIN_X + i * (COL_W + GAP)
                y = start_y_row1
            else:
                if i < 4:
                    x = MARGIN_X + i * (COL_W + GAP)
                    y = start_y_row1
                else:
                    offset_x = (COL_W + GAP) / 2
                    x = MARGIN_X + offset_x + (i - 4) * (COL_W + GAP)
                    y = start_y_row2
            
            svg.append(f'<rect x="{x}" y="{y}" width="{COL_W}" height="85" class="header-bg" />')
            svg.append(f'<text x="{x + COL_W/2}" y="{y + 57}" class="day-title">{day}</text>')
            
            y += 85 + CARD_GAP
            
            for ev in day_events[day]:
                color = '#0ea5e9' if 'Offenes' in ev['name'] else '#ef4444' if 'Jugend' in ev['name'] or 'Junges' in ev['name'] else '#2563eb'
                
                name_lines, supervisor_lines, comment_lines, card_height = self.get_card_layout(ev)
                
                svg.append(f'<rect x="{x}" y="{y}" width="{COL_W}" height="{card_height}" class="card-bg" filter="url(#shadow)"/>')
                svg.append(f'<circle cx="{x + 35}" cy="{y + 55}" r="12" fill="{color}" />')
                
                text_y = y + 65
                svg.append(f'<text x="{x + 65}" y="{text_y}" class="time-text">{html.escape(ev["start_time"])} - {html.escape(ev["end_time"])} Uhr</text>')
                
                text_y += 4
                for name_line in name_lines:
                    text_y += 46
                    svg.append(f'<text x="{x + 35}" y="{text_y}" class="event-title">{html.escape(name_line)}</text>')
                
                if supervisor_lines:
                    text_y += 10
                    for b in supervisor_lines:
                        text_y += 40
                        svg.append(f'<text x="{x + 35}" y="{text_y}" class="event-sub">{html.escape(b)}</text>')
                    
                if comment_lines:
                    text_y += 15
                    for k_line in comment_lines:
                        text_y += 40
                        svg.append(f'<text x="{x + 35}" y="{text_y}" class="event-extra">{html.escape(k_line)}</text>')
                    
                y += card_height + CARD_GAP
                
            if y > max_total_y: max_total_y = y

        svg.append('</svg>')
        return '\n'.join(svg).replace('HEIGHT_PLACEHOLDER', str(max_total_y + 40))

    def generate_stegplan_svg(self, events):
        """Generates the two-line SVG layout and saves it to the server."""
        svg_string = self.generate_stegplan_svg_string(events)
        
        # Saving the SVG in the configured target directory
        output_path = self.config.get('svg_output_path', '/var/www/res/stegplan.svg')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(svg_string)
        logger.info(f"Stegplan SVG generated and saved to {output_path}")
            
        # Generate the timetable SVG as well
        active_events = [e for e in events if self.is_event_active(e)]
        days = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
        self.generate_timetable_svg(active_events, days)

    def get_accent_color(self, name):
        """Returns the category color. It is only an accent, on paper the name tells events apart."""
        if 'Offenes' in name:
            return '#075985'
        if any(group in name for group in ('Jugend', 'Junges', 'Junioren', 'Kinder')):
            return '#991b1b'
        return '#1e3a8a'

    def get_event_hours(self, ev):
        """Returns start and end of an event as decimal hours, or None if they cannot be drawn."""
        try:
            start_hour, start_min = map(int, ev.start_time.split(':'))
            end_hour, end_min = map(int, ev.end_time.split(':'))
        except (ValueError, AttributeError):
            logger.warning(f"Skipping event '{ev.name}' with invalid times: {ev.start_time} - {ev.end_time}")
            return None
        start_dec, end_dec = start_hour + start_min / 60.0, end_hour + end_min / 60.0
        if end_dec <= start_dec:
            logger.warning(f"Skipping event '{ev.name}' ending before it starts: {ev.start_time} - {ev.end_time}")
            return None
        return start_dec, end_dec

    def generate_timetable_svg_string(self, events, days, target_date=None, custom_title_date=False, title=None):
        """Generates a timetable layout as an SVG string. The grid covers the hours with events and fills the page."""
        drawable_events = []
        for ev in events:
            if ev.weekday in days:
                hours = self.get_event_hours(ev)
                if hours:
                    drawable_events.append((ev, hours[0], hours[1]))

        # The grid only covers the hours with events, an empty plan shows 08:00 to 21:00
        if drawable_events:
            START_HOUR = min(int(start) for _, start, _ in drawable_events)
            END_HOUR = max(math.ceil(end) - 1 for _, _, end in drawable_events)
        else:
            START_HOUR, END_HOUR = 8, 20
        
        TIME_COL_W, COL_W = 80, 215
        MARGIN_TOP, MARGIN_LEFT = 110, 21
        # 1150 is the height that keeps the A4 proportions at this width
        HOUR_H = (1150 - MARGIN_TOP - 20) / (END_HOUR - START_HOUR + 1)
        TOTAL_W = MARGIN_LEFT + TIME_COL_W + len(days) * COL_W + 20
        TOTAL_H = MARGIN_TOP + (END_HOUR - START_HOUR + 1) * HOUR_H + 20

        # Determine season phase (Summer/Winter)
        now = target_date if target_date else datetime.now()
        base_title = title or self.get_base_title(now)

        if custom_title_date:
            title_text = self.loc.get('title_valid_from', base_title, now.strftime('%d.%m.'))
        else:
            title_text = base_title

        svg = [f'<svg viewBox="0 0 {TOTAL_W} {TOTAL_H}" width="297mm" height="210mm" xmlns="http://www.w3.org/2000/svg">']
        # Pure black on white prints without halftoning on black and white printers
        svg.append('<defs><style>.bg { fill: #ffffff; } .line { stroke: #000000; stroke-width: 0.5; } .line-solid { stroke: #000000; stroke-width: 1.5; } .time-label { font-family: "Segoe UI", Arial, sans-serif; font-size: 18px; font-weight: bold; fill: #000000; text-anchor: end; } .day-header { fill: #000000; } .day-label { font-family: "Segoe UI", Arial, sans-serif; font-size: 22px; font-weight: bold; fill: #ffffff; text-anchor: middle; } .main-title { font-family: "Segoe UI", Arial, sans-serif; font-size: 30px; font-weight: bold; fill: #000000; text-anchor: middle; } .tile-text { font-family: "Segoe UI", Arial, sans-serif; fill: #000000; } .tile-title { font-weight: bold; } .tile-time { font-weight: bold; } .tile-comment { font-style: italic; }</style></defs>')
        svg.append(f'<rect width="{TOTAL_W}" height="{TOTAL_H}" class="bg" />')
        svg.append(f'<text x="{TOTAL_W / 2}" y="45" class="main-title">{html.escape(title_text)}</text>')

        # Grid and Labels
        for h in range(START_HOUR, END_HOUR + 1):
            y = MARGIN_TOP + (h - START_HOUR) * HOUR_H
            svg.append(f'<text x="{MARGIN_LEFT + TIME_COL_W - 12}" y="{y + 6}" class="time-label">{h:02d}:00</text>')
            svg.append(f'<line x1="{MARGIN_LEFT + TIME_COL_W}" y1="{y}" x2="{TOTAL_W - 20}" y2="{y}" class="line" />')

        for i, day in enumerate(days):
            x = MARGIN_LEFT + TIME_COL_W + i * COL_W
            svg.append(f'<rect x="{x + 2}" y="{MARGIN_TOP - 44}" width="{COL_W - 4}" height="38" rx="4" class="day-header" />')
            svg.append(f'<text x="{x + COL_W/2}" y="{MARGIN_TOP - 17}" class="day-label">{day}</text>')
            svg.append(f'<line x1="{x}" y1="{MARGIN_TOP}" x2="{x}" y2="{TOTAL_H-20}" class="line-solid" />')
        svg.append(f'<line x1="{MARGIN_LEFT + TIME_COL_W + len(days) * COL_W}" y1="{MARGIN_TOP}" x2="{MARGIN_LEFT + TIME_COL_W + len(days) * COL_W}" y2="{TOTAL_H-20}" class="line-solid" />')

        # Draw Events
        for day_idx, day in enumerate(days):
            day_events_list = [{'ev': ev, 's': start, 'e': end} for ev, start, end in drawable_events if ev.weekday == day]
            day_events_list.sort(key=lambda x: x['s'])
            
            # Group events connected by overlaps, each group shares the width of the day
            groups = []
            group_end = 0
            for item in day_events_list:
                if groups and item['s'] < group_end:
                    groups[-1].append(item)
                    group_end = max(group_end, item['e'])
                else:
                    groups.append([item])
                    group_end = item['e']

            # Assign each event to the first free column of its group
            for group in groups:
                col_ends = []
                for item in group:
                    for col, col_end in enumerate(col_ends):
                        if item['s'] >= col_end:
                            item['col'] = col
                            col_ends[col] = item['e']
                            break
                    else:
                        item['col'] = len(col_ends)
                        col_ends.append(item['e'])
                for item in group:
                    item['cols'] = len(col_ends)

            # Draw tiles
            for item in day_events_list:
                ev = item['ev']
                start_dec = item['s']
                end_dec = item['e']
                col = item['col']
                cols = item['cols']
                y = MARGIN_TOP + (start_dec - START_HOUR) * HOUR_H
                h = (end_dec - start_dec) * HOUR_H

                if cols > 1:
                    w = (COL_W - 4 - 4 * cols) / cols
                    x = MARGIN_LEFT + TIME_COL_W + day_idx * COL_W + 4 + col * (w + 4)
                else:
                    w = COL_W - 8
                    x = MARGIN_LEFT + TIME_COL_W + day_idx * COL_W + 4
                    
                color_accent = self.get_accent_color(ev.name)

                svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#ffffff" stroke="#000000" stroke-width="1.5" rx="3"/>')
                svg.append(f'<line x1="{x + 4.5}" y1="{y + 2}" x2="{x + 4.5}" y2="{y + h - 2}" stroke="{color_accent}" stroke-width="6"/>')

                if cols == 1:
                    title_size, time_size, detail_size = 18, 15, 14
                    time_lines = [f"{ev.start_time} – {ev.end_time} Uhr"]
                elif cols == 2:
                    title_size, time_size, detail_size = 15, 13, 13
                    time_lines = [f"{ev.start_time}–{ev.end_time}"]
                else:
                    title_size, time_size, detail_size = 12, 13, 12
                    time_lines = [f"{ev.start_time} –", ev.end_time]

                # Character limits leave room for fonts wider than Arial, which depend on the system
                # Short tiles fit only two lines, and the time must be one of them
                compact = h < 64
                if compact:
                    title_size, time_size, detail_size = 14, 12, 12
                    if cols == 1:
                        time_lines = [f"{ev.start_time} – {ev.end_time}"]

                text_x = x + 12
                text_w = w - 16
                max_title = 8 if cols > 2 else int(text_w / (title_size * 0.62))
                max_detail = int(text_w / (detail_size * 0.55))

                supervisors = " & ".join(b.strip() for b in [ev.supervisor1, ev.supervisor2, ev.supervisor3] if b and b.strip())
                title_lines = self.wrap_text_with_hyphens(ev.name, max_title)
                if compact:
                    if len(title_lines) > 1:
                        title_lines = [title_lines[0].rstrip('-') + '…']
                    time_with_supervisors = f"{time_lines[0]} · {supervisors}"
                    if supervisors and len(time_lines) == 1 and len(time_with_supervisors) <= max_detail:
                        time_lines = [time_with_supervisors]
                        supervisors = ''

                lines = [(line, 'tile-title', title_size) for line in title_lines]
                lines += [(line, 'tile-time', time_size) for line in time_lines]
                lines += [(line, 'tile-supervisor', detail_size) for line in self.wrap_text_with_hyphens(supervisors, max_detail)]
                lines += [(line, 'tile-comment', detail_size) for line in self.wrap_text_with_hyphens(ev.comment or '', max_detail)]

                # Text that does not fit ends with an ellipsis instead of running into the next tile
                visible_lines = []
                top_padding, line_gap = (3, 2) if compact else (6, 3)
                used_height = top_padding
                for line in lines:
                    used_height += line[2] + line_gap
                    if used_height > h - (1 if compact else 3):
                        break
                    visible_lines.append(line)
                if visible_lines and len(visible_lines) < len(lines):
                    text, css_class, size = visible_lines[-1]
                    visible_lines[-1] = (text.rstrip(' -&') + '…', css_class, size)
                    logger.warning(f"Text of event '{ev.name}' does not fit into its timetable tile.")

                text_y = y + top_padding
                for text, css_class, size in visible_lines:
                    text_y += size + line_gap
                    svg.append(f'<text x="{text_x}" y="{text_y - 1}" font-size="{size}" class="tile-text {css_class}">{html.escape(text)}</text>')

        svg.append('</svg>')
        return '\n'.join(svg)
        
    def generate_timetable_svg(self, events, days):
        """Saves the timetable layout to a file."""
        svg_string = self.generate_timetable_svg_string(events, days)
        timetable_path = self.config.get('timetable_output_path', '/var/www/res/stundenplan.svg')
        os.makedirs(os.path.dirname(timetable_path), exist_ok=True)
        with open(timetable_path, 'w', encoding='utf-8') as f:
            f.write(svg_string)
        logger.info(f"Timetable SVG generated and saved to {timetable_path}")

    def get_room_output_dir(self):
        """Returns the directory of the room plans and the overview."""
        return self.config.get('room_output_dir') or os.path.dirname(self.config.get('svg_output_path', '/var/www/res/stegplan.svg'))

    def get_room_svg_path(self, room):
        """Returns the path of the SVG file of a room."""
        return os.path.join(self.get_room_output_dir(), f"raum-{room.slug}.svg")

    def get_overview_svg_path(self):
        """Returns the path of the SVG file of the overview."""
        return self.config.get('overview_output_path') or os.path.join(self.get_room_output_dir(), 'nutzungszeiten.svg')

    def generate_room_svg_string(self, room, events, target_date=None, custom_title_date=False):
        """Generates the timetable of a room as an SVG string."""
        active_events = [e for e in events if self.is_event_active(e, target_date=target_date)]
        return self.generate_timetable_svg_string(
            active_events, list(WEEKDAYS), target_date=target_date, custom_title_date=custom_title_date,
            title=self.loc.get('title_room', room.name)
        )

    def generate_room_svg(self, room, events):
        """Generates the timetable of a room and saves it to the server."""
        svg_string = self.generate_room_svg_string(room, events)
        output_path = self.get_room_svg_path(room)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(svg_string)
        logger.info(f"Room SVG generated and saved to {output_path}")

    def delete_room_svg(self, room):
        """Removes the SVG file of a deleted room."""
        output_path = self.get_room_svg_path(room)
        if os.path.exists(output_path):
            os.remove(output_path)
            logger.info(f"Room SVG {output_path} removed")

    def generate_room_pdf_for_date(self, room, events, target_date):
        """Generates a room timetable PDF stream for a specific date."""
        svg_string = self.generate_room_svg_string(room, events, target_date=target_date, custom_title_date=True)

        pdf_out = io.BytesIO()
        cairosvg.svg2pdf(bytestring=svg_string.encode('utf-8'), write_to=pdf_out)
        pdf_out.seek(0)
        logger.info(f"Room PDF for {target_date.strftime('%Y-%m-%d')} generated successfully.")
        return pdf_out

    def generate_overview_svg_string(self, plans, notes, target_date=None):
        """Generates the list of all active events by plan as an SVG string."""
        now = target_date if target_date else datetime.now()
        WIDTH, ROW_H, LINE_H, SECTION_H = 800, 30, 18, 35
        COL_DAY, COL_TIME, COL_GROUP, COL_CONTACT = 20, 120, 250, 550
        MAX_GROUP, MAX_CONTACT, MAX_NOTE = 38, 33, 105

        svg = [f'<rect x="0" y="0" width="{WIDTH}" height="60" class="header-bg" />']
        svg.append(f'<text x="{WIDTH / 2}" y="38" text-anchor="middle" class="header-text">{html.escape(self.get_overview_title(now))}</text>')
        svg.append(f'<rect x="0" y="60" width="{WIDTH}" height="40" class="sub-header-bg" />')
        for x, key in ((COL_DAY, 'overview_col_day'), (COL_TIME, 'overview_col_time'), (COL_GROUP, 'overview_col_group'), (COL_CONTACT, 'overview_col_contact')):
            svg.append(f'<text x="{x}" y="85" class="col-head-text">{html.escape(self.loc.get(key))}</text>')

        y = 100
        for room, events in plans:
            active_events = [e for e in events if e.weekday in WEEKDAYS and self.is_event_active(e, target_date=now)]
            if not active_events:
                continue
            active_events.sort(key=lambda e: (WEEKDAYS.index(e.weekday), e.start_time))

            label = room.name.upper() if room else self.loc.get('overview_section_stegplan')
            svg.append(f'<rect x="0" y="{y}" width="{WIDTH}" height="{SECTION_H}" class="section-header-bg" />')
            svg.append(f'<text x="{COL_DAY}" y="{y + 22}" class="section-header-text">{html.escape(label)}</text>')
            svg.append(f'<line x1="0" y1="{y}" x2="{WIDTH}" y2="{y}" stroke="#1d3b87" stroke-width="1" />')
            y += SECTION_H

            previous_day = None
            for index, ev in enumerate(active_events):
                comment = (ev.comment or '').strip()
                group = f"{ev.name} ({comment})" if comment else ev.name
                contact = ", ".join(b.strip() for b in [ev.supervisor1, ev.supervisor2, ev.supervisor3] if b and b.strip()) or "-"
                group_lines = self.wrap_text(group, MAX_GROUP)
                contact_lines = self.wrap_text(contact, MAX_CONTACT)
                row_h = ROW_H + (max(len(group_lines), len(contact_lines)) - 1) * LINE_H

                svg.append(f'<rect x="0" y="{y}" width="{WIDTH}" height="{row_h}" class="{"row-bg-even" if index % 2 else "row-bg-odd"}" />')
                if ev.weekday != previous_day:
                    if previous_day:
                        svg.append(f'<line x1="0" y1="{y}" x2="{WIDTH}" y2="{y}" stroke="#ddd" />')
                    svg.append(f'<text x="{COL_DAY}" y="{y + 20}" class="cell-text" font-weight="bold">{ev.weekday}</text>')
                    previous_day = ev.weekday
                svg.append(f'<text x="{COL_TIME}" y="{y + 20}" class="cell-text">{html.escape(ev.start_time)} – {html.escape(ev.end_time)}</text>')
                for i, line in enumerate(group_lines):
                    svg.append(f'<text x="{COL_GROUP}" y="{y + 20 + i * LINE_H}" class="cell-text">{html.escape(line)}</text>')
                for i, line in enumerate(contact_lines):
                    svg.append(f'<text x="{COL_CONTACT}" y="{y + 20 + i * LINE_H}" class="cell-text">{html.escape(line)}</text>')
                y += row_h

            svg.append(f'<line x1="0" y1="{y}" x2="{WIDTH}" y2="{y}" stroke="#1d3b87" stroke-width="2" />')

        note_lines = [line.strip().lstrip('•').strip() for line in (notes or '').splitlines()]
        note_lines = [line for line in note_lines if line]
        if note_lines:
            y += 30
            svg.append(f'<text x="{COL_DAY}" y="{y}" class="footer-text">{html.escape(self.loc.get("overview_notes_title"))}</text>')
            for note in note_lines:
                for i, line in enumerate(self.wrap_text(note, MAX_NOTE)):
                    y += 20
                    svg.append(f'<text x="{COL_DAY}" y="{y}" class="footer-text">{"• " if i == 0 else "   "}{html.escape(line)}</text>')
            y += 30

        svg.append(f'<rect x="0" y="0" width="{WIDTH}" height="{y}" class="border" />')
        head = [f'<svg width="{WIDTH}" height="{y}" viewBox="0 0 {WIDTH} {y}" xmlns="http://www.w3.org/2000/svg">']
        head.append('<defs><style>.header-bg { fill: #1d3b87; } .header-text { fill: #ffffff; font-family: Arial, sans-serif; font-weight: bold; font-size: 24px; } .sub-header-bg { fill: #c92626; } .col-head-text { fill: #ffffff; font-family: Arial, sans-serif; font-weight: bold; font-size: 16px; } .section-header-bg { fill: #e0e0e0; } .section-header-text { fill: #1d3b87; font-family: Arial, sans-serif; font-weight: bold; font-size: 16px; } .row-bg-odd { fill: #ffffff; } .row-bg-even { fill: #f0f4fa; } .cell-text { fill: #000000; font-family: Arial, sans-serif; font-size: 14px; } .footer-text { fill: #c92626; font-family: Arial, sans-serif; font-size: 12px; font-weight: bold; } .border { stroke: #1d3b87; stroke-width: 1; fill: none; }</style></defs>')
        return '\n'.join(head + svg + ['</svg>'])

    def generate_overview_svg(self, plans, notes):
        """Generates the overview and saves it to the server."""
        svg_string = self.generate_overview_svg_string(plans, notes)
        output_path = self.get_overview_svg_path()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(svg_string)
        logger.info(f"Overview SVG generated and saved to {output_path}")

    def generate_stegplan_pdf_for_date(self, all_events, target_date, orientation):
        """Generates a stegplan PDF stream for a specific date and orientation."""
        svg_string = self.generate_stegplan_svg_string(
            all_events, target_date=target_date, orientation=orientation, custom_title_date=True
        )
        
        pdf_out = io.BytesIO()
        cairosvg.svg2pdf(bytestring=svg_string.encode('utf-8'), write_to=pdf_out)
        pdf_out.seek(0)
        logger.info(f"Stegplan PDF for {target_date.strftime('%Y-%m-%d')} generated successfully.")
        return pdf_out

    def generate_stundenplan_pdf_for_date(self, all_events, target_date):
        """Generates a timetable PDF stream for a specific date."""
        active_events = [e for e in all_events if self.is_event_active(e, target_date=target_date)]
        days = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
        
        svg_string = self.generate_timetable_svg_string(active_events, days, target_date=target_date, custom_title_date=True)
        
        pdf_out = io.BytesIO()
        cairosvg.svg2pdf(bytestring=svg_string.encode('utf-8'), write_to=pdf_out)
        pdf_out.seek(0)
        logger.info(f"Timetable PDF for {target_date.strftime('%Y-%m-%d')} generated successfully.")
        return pdf_out
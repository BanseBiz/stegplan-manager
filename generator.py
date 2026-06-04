import os
import html
import io
import cairosvg
import logging
from datetime import datetime
import pyphen

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
            if len(cur_line) + len(w) > max_len:
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

    def is_event_active(self, ev, target_date=None):
        """Checks if an event is active on the selected date (regardless of the year)."""
        if not getattr(ev, 'season') or ev.season == 'Immer' or not getattr(ev, 'start_date') or not getattr(ev, 'end_date'):
            return True
        try:
            start_month, start_day = int(ev.start_date[3:5]), int(ev.start_date[0:2])
            end_month, end_day = int(ev.end_date[3:5]), int(ev.end_date[0:2])
            now = target_date if target_date else datetime.now()
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
                supervisor_list = [v.strip() for k, v in ev.items() if k.startswith('supervisor') and v.strip()]
                supervisor_lines = []
                if supervisor_list:
                    supervisor_str = " & ".join(supervisor_list)
                    if len(supervisor_str) > 18:
                        supervisor_lines = [b + " &" if i < len(supervisor_list)-1 else b for i, b in enumerate(supervisor_list)]
                    else:
                        supervisor_lines = [supervisor_str]
                comment_lines = self.wrap_text(ev.get('comment', ''), 23)
                
                card_height = 150
                if supervisor_lines: card_height += 10 + len(supervisor_lines) * 40
                if comment_lines: card_height += 15 + len(comment_lines) * 40
                y += card_height + CARD_GAP
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
        summer_str = self.config.get('sommerphase_start', '31.03')
        winter_str = self.config.get('winterphase_start', '27.10')
        try:
            summer_start = datetime.strptime(f"{summer_str}.{now.year}", "%d.%m.%Y")
            winter_start = datetime.strptime(f"{winter_str}.{now.year}", "%d.%m.%Y")
            if summer_start <= now < winter_start:
                base_title = self.loc.get('title_summer', now.year)
            else:
                base_title = self.loc.get('title_winter', now.year)
        except ValueError:
            base_title = self.loc.get('title_default', now.year)

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
                
                supervisor_list = [v.strip() for k, v in ev.items() if k.startswith('supervisor') and v.strip()]
                supervisor_lines = []
                if supervisor_list:
                    supervisor_str = " & ".join(supervisor_list)
                    if len(supervisor_str) > 18:
                        supervisor_lines = [b + " &" if idx < len(supervisor_list)-1 else b for idx, b in enumerate(supervisor_list)]
                    else:
                        supervisor_lines = [supervisor_str]
                        
                comment_lines = self.wrap_text(ev.get('comment', ''), 23)
                
                card_height = 150
                if supervisor_lines: card_height += 10 + len(supervisor_lines) * 40
                if comment_lines: card_height += 15 + len(comment_lines) * 40
                
                svg.append(f'<rect x="{x}" y="{y}" width="{COL_W}" height="{card_height}" class="card-bg" filter="url(#shadow)"/>')
                svg.append(f'<circle cx="{x + 35}" cy="{y + 55}" r="12" fill="{color}" />')
                
                text_y = y + 65
                svg.append(f'<text x="{x + 65}" y="{text_y}" class="time-text">{html.escape(ev["start_time"])} - {html.escape(ev["end_time"])} Uhr</text>')
                
                text_y += 50
                svg.append(f'<text x="{x + 35}" y="{text_y}" class="event-title">{html.escape(ev["name"])}</text>')
                
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

    def generate_timetable_svg_string(self, events, days, target_date=None, custom_title_date=False):
        """Generates a timetable layout as an SVG string."""
        START_HOUR = 8
        END_HOUR = 20
        
        HOUR_H, TIME_COL_W, COL_W = 80, 80, 215
        MARGIN_TOP, MARGIN_LEFT = 110, 21
        TOTAL_W = MARGIN_LEFT + TIME_COL_W + len(days) * COL_W + 20
        TOTAL_H = MARGIN_TOP + (END_HOUR - START_HOUR + 1) * HOUR_H + 20

        # Determine season phase (Summer/Winter)
        now = target_date if target_date else datetime.now()
        summer_str = self.config.get('sommerphase_start', '31.03')
        winter_str = self.config.get('winterphase_start', '27.10')
        try:
            summer_start = datetime.strptime(f"{summer_str}.{now.year}", "%d.%m.%Y")
            winter_start = datetime.strptime(f"{winter_str}.{now.year}", "%d.%m.%Y")
            if summer_start <= now < winter_start:
                base_title = self.loc.get('title_summer', now.year)
            else:
                base_title = self.loc.get('title_winter', now.year)
        except ValueError:
            base_title = self.loc.get('title_default', now.year)

        if custom_title_date:
            title_text = self.loc.get('title_valid_from', base_title, now.strftime('%d.%m.'))
        else:
            title_text = base_title

        svg = [f'<svg viewBox="0 0 {TOTAL_W} {TOTAL_H}" width="297mm" height="210mm" xmlns="http://www.w3.org/2000/svg">']
        svg.append('<defs><style>.bg { fill: #f8fafc; } .line { stroke: #cbd5e1; stroke-width: 1; stroke-dasharray: 4 4; } .line-solid { stroke: #94a3b8; stroke-width: 1; } .time-label { font-family: "Segoe UI", Arial, sans-serif; font-size: 16px; font-weight: 600; fill: #64748b; text-anchor: end; } .day-label { font-family: "Segoe UI", Arial, sans-serif; font-size: 20px; font-weight: bold; fill: #1e293b; text-anchor: middle; } .main-title { font-family: "Segoe UI", Arial, sans-serif; font-size: 28px; font-weight: 900; fill: #0f172a; text-anchor: middle; }</style>')
        svg.append('<filter id="shadow-sp" x="-5%" y="-5%" width="110%" height="110%"><feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#000000" flood-opacity="0.1"/></filter></defs>')
        svg.append(f'<rect width="{TOTAL_W}" height="{TOTAL_H}" class="bg" />')
        svg.append(f'<text x="{TOTAL_W / 2}" y="45" class="main-title">{title_text}</text>')

        # Grid and Labels
        for h in range(START_HOUR, END_HOUR + 1):
            y = MARGIN_TOP + (h - START_HOUR) * HOUR_H
            svg.append(f'<text x="{MARGIN_LEFT + TIME_COL_W - 15}" y="{y + 6}" class="time-label">{h:02d}:00</text>')
            svg.append(f'<line x1="{MARGIN_LEFT + TIME_COL_W}" y1="{y}" x2="{TOTAL_W - 20}" y2="{y}" class="line" />')

        for i, day in enumerate(days):
            x = MARGIN_LEFT + TIME_COL_W + i * COL_W
            svg.append(f'<text x="{x + COL_W/2}" y="{MARGIN_TOP - 20}" class="day-label">{day}</text>')
            svg.append(f'<line x1="{x}" y1="{MARGIN_TOP}" x2="{x}" y2="{TOTAL_H-20}" class="line-solid" />')
        svg.append(f'<line x1="{MARGIN_LEFT + TIME_COL_W + len(days) * COL_W}" y1="{MARGIN_TOP}" x2="{MARGIN_LEFT + TIME_COL_W + len(days) * COL_W}" y2="{TOTAL_H-20}" class="line-solid" />')

        # Draw Events
        for day_idx, day in enumerate(days):
            day_events_list = []
            for ev in events:
                if ev.weekday == day:
                    try:
                        start_hour, start_min = map(int, ev.start_time.split(':'))
                        end_hour, end_min = map(int, ev.end_time.split(':'))
                        start_dec, end_dec = start_hour + start_min / 60.0, end_hour + end_min / 60.0
                        if start_dec < START_HOUR: start_dec = START_HOUR
                        if end_dec > END_HOUR + 1: end_dec = END_HOUR + 1
                        if end_dec > start_dec:
                            day_events_list.append({'ev': ev, 's': start_dec, 'e': end_dec})
                    except: pass
                    
            day_events_list.sort(key=lambda x: x['s'])
            
            # Check overlaps
            for i, item in enumerate(day_events_list):
                overlaps = False
                for j, other in enumerate(day_events_list):
                    if i != j:
                        if max(item['s'], other['s']) < min(item['e'], other['e']):
                            overlaps = True
                            break
                item['overlaps'] = overlaps

            # Assign columns (0 = left, 1 = right)
            col_ends = [0, 0]
            for item in day_events_list:
                if item['s'] >= col_ends[0]:
                    item['col'] = 0
                    col_ends[0] = item['e']
                elif item['s'] >= col_ends[1]:
                    item['col'] = 1
                    col_ends[1] = item['e']
                else:
                    item['col'] = 0
                    col_ends[0] = item['e']

            # Draw tiles
            for item in day_events_list:
                ev = item['ev']
                start_dec = item['s']
                end_dec = item['e']
                overlaps = item['overlaps']
                col = item['col']
                
                y = MARGIN_TOP + (start_dec - START_HOUR) * HOUR_H
                h = (end_dec - start_dec) * HOUR_H
                
                if overlaps:
                    w = (COL_W - 12) / 2
                    x = MARGIN_LEFT + TIME_COL_W + day_idx * COL_W + 4 + col * (w + 4)
                else:
                    w = COL_W - 8
                    x = MARGIN_LEFT + TIME_COL_W + day_idx * COL_W + 4
                    
                color_bg = '#bae6fd' if 'Offenes' in ev.name else '#fecaca' if 'Jugend' in ev.name or 'Junges' in ev.name else '#bfdbfe'
                color_stroke = '#38bdf8' if 'Offenes' in ev.name else '#f87171' if 'Jugend' in ev.name or 'Junges' in ev.name else '#60a5fa'
                color_text = '#0369a1' if 'Offenes' in ev.name else '#b91c1c' if 'Jugend' in ev.name or 'Junges' in ev.name else '#1d4ed8'

                svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color_bg}" stroke="{color_stroke}" stroke-width="2" rx="6" filter="url(#shadow-sp)" fill-opacity="0.95"/>')
                
                if overlaps:
                    max_title = 13
                    title_lines = self.wrap_text_with_hyphens(ev.name, max_title)
                    title_font_size = 12
                else:
                    max_title = 24
                    title_lines = [ev.name if len(ev.name) <= max_title else ev.name[:max_title-2] + '..']
                    title_font_size = 14
                    
                current_y = y + 24
                for t_line in title_lines:
                    svg.append(f'<text x="{x + 6}" y="{current_y}" font-family="Segoe UI, Arial, sans-serif" font-size="{title_font_size}" font-weight="800" fill="{color_text}">{html.escape(t_line)}</text>')
                    current_y += 14 if overlaps else 18
                    
                current_y += 4 if overlaps else 0
                
                time_font_size = 10 if overlaps else 12
                time_str = f"{ev.start_time} - {ev.end_time}" if overlaps else f"{ev.start_time} - {ev.end_time} Uhr"
                svg.append(f'<text x="{x + 6}" y="{current_y}" font-family="Segoe UI, Arial, sans-serif" font-size="{time_font_size}" font-weight="600" fill="{color_text}">{html.escape(time_str)}</text>')

                current_text_y = current_y
                
                supervisor_list = [b.strip() for b in [ev.supervisor1, ev.supervisor2, ev.supervisor3] if b and b.strip()]
                if supervisor_list:
                    if overlaps:
                        for i, b in enumerate(supervisor_list):
                            suffix = " &" if i < len(supervisor_list) - 1 else ""
                            max_bet = 18 - len(suffix)
                            bet_trunc = b if len(b) <= max_bet else b[:max_bet-2] + '..'
                            bet_trunc += suffix
                            current_text_y += 14
                            svg.append(f'<text x="{x + 6}" y="{current_text_y}" font-family="Segoe UI, Arial, sans-serif" font-size="11" font-weight="600" fill="{color_text}">{html.escape(bet_trunc)}</text>')
                    else:
                        supervisor_str = " & ".join(supervisor_list)
                        max_bet = 31
                        bet_trunc = supervisor_str if len(supervisor_str) <= max_bet else supervisor_str[:max_bet-2] + '..'
                        current_text_y += 16
                        svg.append(f'<text x="{x + 6}" y="{current_text_y}" font-family="Segoe UI, Arial, sans-serif" font-size="11" font-weight="600" fill="{color_text}">{html.escape(bet_trunc)}</text>')
                    
                if ev.comment and ev.comment.strip():
                    max_comment = 17 if overlaps else 36
                    comment_lines = self.wrap_text_with_hyphens(ev.comment, max_comment)
                    for k_line in comment_lines:
                        current_text_y += 14
                        svg.append(f'<text x="{x + 6}" y="{current_text_y}" font-family="Segoe UI, Arial, sans-serif" font-size="11" font-style="italic" fill="{color_text}">{html.escape(k_line)}</text>')

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
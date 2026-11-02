import html
import re
import unittest
from datetime import datetime
from types import SimpleNamespace

from helpers import WEEK, make_event, make_generator, overlapping_tiles, timetable_tiles


class SeasonTest(unittest.TestCase):
    def setUp(self):
        self.gen = make_generator()

    def test_seasons_exclude_each_other_on_every_boundary_day(self):
        cases = {
            datetime(2026, 3, 30): False,
            datetime(2026, 3, 31): True,
            datetime(2026, 10, 26): True,
            datetime(2026, 10, 27): False,
        }
        summer = make_event(season='Sommer', start_date='31.03', end_date='27.10')
        winter = make_event(season='Winter', start_date='27.10', end_date='31.03')
        for date, in_summer in cases.items():
            self.assertEqual(self.gen.is_event_active(summer, date), in_summer, date)
            self.assertEqual(self.gen.is_event_active(winter, date), not in_summer, date)

    def test_seasonal_events_ignore_their_stored_dates(self):
        event = make_event(season='Sommer', start_date='01.05', end_date='30.09')
        self.assertTrue(self.gen.is_event_active(event, datetime(2026, 4, 1)))
        undated = make_event(season='Sommer')
        self.assertFalse(self.gen.is_event_active(undated, datetime(2026, 1, 1)))

    def test_changed_phases_apply_to_existing_events(self):
        gen = make_generator(summer='29.03', winter='25.10')
        event = make_event(season='Sommer', start_date='31.03', end_date='27.10')
        self.assertTrue(gen.is_event_active(event, datetime(2026, 3, 30)))
        self.assertFalse(gen.is_event_active(event, datetime(2026, 10, 26)))

    def test_manual_dates_include_the_end_date_and_can_span_new_year(self):
        event = make_event(season='Manuell', start_date='01.04', end_date='31.10')
        self.assertTrue(self.gen.is_event_active(event, datetime(2026, 10, 31)))
        self.assertFalse(self.gen.is_event_active(event, datetime(2026, 11, 1)))
        spanning = make_event(season='Manuell', start_date='01.11', end_date='28.02')
        self.assertTrue(self.gen.is_event_active(spanning, datetime(2027, 1, 15)))
        self.assertFalse(self.gen.is_event_active(spanning, datetime(2026, 3, 1)))

    def test_always_and_undated_manual_events_are_active(self):
        self.assertTrue(self.gen.is_event_active(make_event(), datetime(2026, 1, 1)))
        self.assertTrue(self.gen.is_event_active(make_event(season='Manuell'), datetime(2026, 1, 1)))

    def test_winter_title_keeps_the_year_the_season_started(self):
        cases = {
            datetime(2026, 3, 30): 'Winterstegplan 2025',
            datetime(2026, 3, 31): 'Sommerstegplan 2026',
            datetime(2026, 10, 27): 'Winterstegplan 2026',
            datetime(2027, 1, 1): 'Winterstegplan 2026',
            datetime(2027, 3, 31): 'Sommerstegplan 2027',
        }
        for date, title in cases.items():
            self.assertEqual(self.gen.get_base_title(date), title)

    def test_invalid_phase_config_falls_back(self):
        gen = make_generator(summer='kaputt')
        self.assertEqual(gen.get_base_title(datetime(2026, 6, 1)), 'Stegplan 2026')
        self.assertTrue(gen.is_event_active(make_event(season='Sommer'), datetime(2026, 6, 1)))


class WrapTextTest(unittest.TestCase):
    def test_long_first_word_does_not_add_an_empty_line(self):
        gen = make_generator()
        self.assertEqual(gen.wrap_text('Donaudampfschifffahrtsgesellschaft fährt', 23), ['Donaudampfschifffahrtsgesellschaft', 'fährt'])
        self.assertEqual(gen.wrap_text('für Anfänger und Wiedereinsteiger', 23), ['für Anfänger und', 'Wiedereinsteiger'])
        self.assertEqual(gen.wrap_text('', 23), [])


class TimetableLayoutTest(unittest.TestCase):
    def setUp(self):
        self.gen = make_generator()

    def layout(self, *times):
        svg = self.gen.generate_timetable_svg_string([make_event(s, e) for s, e in times], WEEK)
        return overlapping_tiles(svg), [round(tile[2], 1) for tile in timetable_tiles(svg)]

    def test_separate_events_use_the_full_width(self):
        self.assertEqual(self.layout(('08:00', '10:00'), ('10:00', '12:00')), (0, [207.0, 207.0]))

    def test_three_parallel_events_share_three_columns(self):
        self.assertEqual(self.layout(('17:00', '19:00'), ('17:15', '19:30'), ('18:00', '20:00')), (0, [66.3, 66.3, 66.3]))

    def test_chain_of_events_needs_only_two_columns(self):
        self.assertEqual(self.layout(('08:00', '10:00'), ('09:00', '11:00'), ('10:00', '12:00')), (0, [101.5, 101.5, 101.5]))

    def test_events_nested_in_a_long_one_need_only_two_columns(self):
        self.assertEqual(self.layout(('08:00', '14:00'), ('09:00', '10:00'), ('11:00', '12:00')), (0, [101.5, 101.5, 101.5]))

    def test_four_parallel_events_do_not_overlap(self):
        overlaps, widths = self.layout(('10:00', '19:00'), ('11:00', '19:00'), ('12:00', '19:00'), ('13:00', '19:00'))
        self.assertEqual(overlaps, 0)
        self.assertEqual(len(widths), 4)


class TimetableGridTest(unittest.TestCase):
    def setUp(self):
        self.gen = make_generator()

    def render(self, *times):
        return self.gen.generate_timetable_svg_string([make_event(s, e) for s, e in times], WEEK)

    def grid_labels(self, svg):
        return re.findall(r'class="time-label">(\d\d:00)<', svg)

    def test_grid_covers_only_the_hours_with_events(self):
        labels = self.grid_labels(self.render(('10:00', '12:00'), ('14:00', '15:30')))
        self.assertEqual((labels[0], labels[-1]), ('10:00', '15:00'))

    def test_empty_plan_shows_the_default_grid(self):
        labels = self.grid_labels(self.render())
        self.assertEqual((labels[0], labels[-1]), ('08:00', '20:00'))

    def test_page_keeps_its_height(self):
        for times in ((('10:00', '11:00'),), (('07:00', '08:00'), ('21:00', '22:00'))):
            self.assertIn('viewBox="0 0 1626 1150', self.render(*times))

    def test_early_event_extends_the_grid_and_is_drawn(self):
        svg = self.render(('06:00', '07:30'))
        self.assertEqual(len(timetable_tiles(svg)), 1)
        self.assertEqual(self.grid_labels(svg)[0], '06:00')

    def test_late_event_extends_the_grid_and_is_drawn(self):
        svg = self.render(('21:00', '22:30'))
        self.assertEqual(len(timetable_tiles(svg)), 1)
        self.assertEqual(self.grid_labels(svg)[-1], '22:00')

    def test_tiles_keep_their_proportions(self):
        long_tile, short_tile = timetable_tiles(self.render(('06:00', '09:00'), ('10:00', '11:00')))
        self.assertAlmostEqual(long_tile[3], 3 * short_tile[3])
        self.assertAlmostEqual(short_tile[3], (1150 - 130) / 5)

    def test_event_ending_on_the_full_hour_needs_no_extra_row(self):
        labels = self.grid_labels(self.render(('20:00', '21:00')))
        self.assertEqual(labels[-1], '20:00')

    def test_undrawable_events_are_logged_and_skipped(self):
        with self.assertLogs('generator', level='WARNING') as logs:
            svg = self.render(('kaputt', '12:00'), ('14:00', '13:00'), ('10:00', '12:00'))
        self.assertEqual(len(timetable_tiles(svg)), 1)
        self.assertEqual(len(logs.output), 2)


class TimetableDesignTest(unittest.TestCase):
    def setUp(self):
        self.gen = make_generator()

    def with_frame(self, *events):
        """Adds events on Sunday that stretch the grid from 08:00 to 21:00, so short tiles stay short."""
        frame = [make_event('08:00', '09:00', weekday='Sonntag', name='Rahmen'), make_event('20:00', '21:00', weekday='Sonntag', name='Rahmen')]
        return list(events) + frame

    def own_lines(self, svg):
        """Returns the tile lines without those of the frame events."""
        frame = ('Rahmen', '08:00 – 09:00 Uhr', '20:00 – 21:00 Uhr')
        return [line for _, line in self.tile_lines(svg) if line not in frame]

    def tile_lines(self, svg):
        return re.findall(r'font-size="(\d+)" class="tile-text [a-z-]+">([^<]*)<', svg)

    def test_text_and_lines_are_pure_black_on_white(self):
        svg = self.gen.generate_timetable_svg_string([make_event(supervisor1='Heini', comment='auch an Feiertagen')], WEEK)
        for rule in re.findall(r'\.(?:time-label|main-title|tile-text|line|line-solid) \{[^}]*\}', svg):
            self.assertRegex(rule, r'(fill|stroke): #000000')
        self.assertIn('.bg { fill: #ffffff; }', svg)
        self.assertRegex(svg, r'\.day-header \{ fill: #000000; \}')
        self.assertRegex(svg, r'\.day-label \{[^}]*fill: #ffffff')

    def test_nothing_is_transparent_or_blurred(self):
        svg = self.gen.generate_timetable_svg_string([make_event(), make_event('11:00', '13:00')], WEEK)
        for forbidden in ('opacity', 'filter', 'stroke-dasharray'):
            self.assertNotIn(forbidden, svg)

    def test_names_and_supervisors_are_wrapped_instead_of_cut(self):
        event = make_event('08:00', '12:00', name='Gemeinsames Rudern für Wiedereinsteiger', supervisor1='Christiane', supervisor2='Maximiliane', supervisor3='Bartholomäus')
        text = ' '.join(line for _, line in self.tile_lines(self.gen.generate_timetable_svg_string([event], WEEK)))
        self.assertNotIn('..', text)
        for word in ('Gemeinsames', 'Wiedereinsteiger', 'Christiane', 'Maximiliane', 'Bartholomäus'):
            self.assertIn(word, text)

    def test_font_sizes_stay_readable_in_print(self):
        cases = [
            ([make_event()], 14),
            ([make_event(), make_event('11:00', '13:00')], 13),
            ([make_event(), make_event('10:30', '13:00'), make_event('11:00', '14:00')], 12),
        ]
        for events, minimum in cases:
            for event in events:
                event.supervisor1 = 'Heini'
            sizes = [int(size) for size, _ in self.tile_lines(self.gen.generate_timetable_svg_string(events, WEEK))]
            self.assertGreaterEqual(min(sizes), minimum)

    def test_text_that_does_not_fit_stays_inside_the_tile(self):
        event = make_event('10:00', '11:00', name='Offenes Rudern', supervisor1='Heini', comment='ein sehr langer Kommentar ' * 6)
        with self.assertLogs('generator', level='WARNING'):
            svg = self.gen.generate_timetable_svg_string(self.with_frame(event), WEEK)
        tile = timetable_tiles(svg)[0]
        baselines = [float(y) for x, y in re.findall(r'<text x="([\d.]+)" y="([\d.]+)" font-size', svg) if tile[0] <= float(x) <= tile[0] + tile[2]]
        self.assertLessEqual(max(baselines), tile[1] + tile[3])
        self.assertTrue(self.own_lines(svg)[-1].endswith('…'))

    def test_short_tiles_always_show_name_and_time(self):
        svg = self.gen.generate_timetable_svg_string(self.with_frame(make_event('16:00', '16:30', name='Junioren U19 1')), WEEK)
        self.assertEqual(self.own_lines(svg), ['Junioren U19 1', '16:00 – 16:30'])

    def test_short_tile_on_a_full_day_grid_keeps_name_and_time(self):
        room = SimpleNamespace(name='Ergoraum', slug='ergoraum')
        events = [make_event('07:00', '08:00'), make_event('21:00', '22:00'), make_event('16:00', '16:30', name='Junioren U19 1')]
        svg = self.gen.generate_room_svg_string(room, events)
        lines = [line for _, line in self.tile_lines(svg)]
        self.assertIn('Junioren U19 1', lines)
        self.assertIn('16:00 – 16:30', lines)

    def test_short_tile_keeps_the_time_when_the_name_is_long(self):
        svg = self.gen.generate_timetable_svg_string(self.with_frame(make_event('16:00', '16:30', name='Gemeinsames Rudern für Wiedereinsteiger und Anfänger')), WEEK)
        lines = self.own_lines(svg)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith('…'))
        self.assertEqual(lines[1], '16:00 – 16:30')

    def test_short_tile_adds_supervisors_next_to_the_time_if_they_fit(self):
        svg = self.gen.generate_timetable_svg_string(self.with_frame(make_event('16:00', '16:30', supervisor1='Elisa')), WEEK)
        self.assertEqual(self.own_lines(svg)[-1], '16:00 – 16:30 · Elisa')

    def test_text_that_fits_logs_nothing(self):
        with self.assertNoLogs('generator', level='WARNING'):
            self.gen.generate_timetable_svg_string([make_event(supervisor1='Heini', comment='auch an Feiertagen')], WEEK)


class StegplanCardTest(unittest.TestCase):
    def setUp(self):
        self.gen = make_generator()

    def test_current_names_stay_on_one_line(self):
        for name in ('IGS Kreyenbrück', 'Offenes Rudern', 'Regattatraining'):
            self.assertEqual(self.gen.get_card_layout(make_event(name=name).to_dict())[0], [name])

    def test_long_name_wraps_and_grows_the_card(self):
        short = self.gen.get_card_layout(make_event().to_dict())
        long = self.gen.get_card_layout(make_event(name='Gemeinsames Rudern für Wiedereinsteiger').to_dict())
        self.assertGreater(len(long[0]), 1)
        self.assertEqual(long[3], short[3] + (len(long[0]) - 1) * 46)
        self.assertTrue(all(len(line) <= 17 for line in long[0]))

    def test_all_name_lines_are_drawn_and_escaped(self):
        event = make_event(name='Gemeinsames Rudern <für> alle')
        svg = self.gen.generate_stegplan_svg_string([event])
        for line in self.gen.get_card_layout(event.to_dict())[0]:
            self.assertIn(html.escape(line), svg)
        self.assertNotIn('<für>', svg)


class PdfTest(unittest.TestCase):
    def test_all_pdf_variants_are_generated(self):
        gen = make_generator()
        events = [make_event(), make_event('11:00', '13:00', weekday='Dienstag', supervisor1='Heini', comment='auch an Feiertagen')]
        date = datetime(2026, 11, 1)
        for orientation in ('portrait', 'landscape'):
            self.assertEqual(gen.generate_stegplan_pdf_for_date(events, date, orientation).read(4), b'%PDF')
        self.assertEqual(gen.generate_stundenplan_pdf_for_date(events, date).read(4), b'%PDF')


if __name__ == '__main__':
    unittest.main()

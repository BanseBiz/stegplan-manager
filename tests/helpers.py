import os
import re
import tempfile

from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from csv_handler import CsvHandler
from database import DatabaseManager, Event
from frontend import Frontend
from generator import DocumentGenerator
from localization import Localization

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEEK = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']
ADMIN_PASS = 'admin-password'


def load_localization():
    return Localization(os.path.join(ROOT, 'localization.json'))


def make_generator(summer='31.03', winter='27.10'):
    config = {'sommerphase_start': summer, 'winterphase_start': winter}
    return DocumentGenerator(config, load_localization())


def make_event(start='10:00', end='12:00', **fields):
    values = dict(
        name='Offenes Rudern', weekday='Montag', start_time=start, end_time=end,
        season='Immer', start_date='', end_date='',
        supervisor1='', supervisor2='', supervisor3='', comment=''
    )
    values.update(fields)
    return Event(**values)


def timetable_tiles(svg):
    """Returns (x, y, width, height) of all event tiles in a timetable SVG."""
    pattern = r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)" fill='
    return [tuple(map(float, match)) for match in re.findall(pattern, svg)]


def overlapping_tiles(svg):
    """Counts pairs of timetable tiles drawn on top of each other."""
    tiles = timetable_tiles(svg)
    pairs = 0
    for i, a in enumerate(tiles):
        for b in tiles[i + 1:]:
            if a[0] < b[0] + b[2] - 1 and b[0] < a[0] + a[2] - 1 and a[1] < b[1] + b[3] - 1 and b[1] < a[1] + a[3] - 1:
                pairs += 1
    return pairs


def create_test_app(database_uri='sqlite:///:memory:', **overrides):
    """Wires the app like app.py does, with SQLite instead of PostgreSQL."""
    output_dir = tempfile.mkdtemp()
    config = {
        'admin_user': 'admin',
        'admin_pass': ADMIN_PASS,
        'https_only': False,
        'svg_output_path': os.path.join(output_dir, 'stegplan.svg'),
        'timetable_output_path': os.path.join(output_dir, 'stundenplan.svg'),
        'sommerphase_start': '31.03',
        'winterphase_start': '27.10',
    }
    config.update(overrides)

    app = Flask('stegplan_test', template_folder=os.path.join(ROOT, 'templates'), static_folder=os.path.join(ROOT, 'static'))
    app.secret_key = 'test-secret'
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=database_uri,
    )
    CSRFProtect(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'

    db_manager = DatabaseManager()
    db_manager.init_app(app, config)

    loc = load_localization()
    doc_generator = DocumentGenerator(config, loc)

    @app.context_processor
    def inject_loc():
        return dict(t=loc.get)

    @login_manager.user_loader
    def load_user(user_id):
        return db_manager.get_user(user_id)

    Frontend(app, db_manager, doc_generator, CsvHandler(), config, loc)
    return app, db_manager


def login(client, username='admin', password=ADMIN_PASS):
    return client.post('/login', data={'username': username, 'password': password})

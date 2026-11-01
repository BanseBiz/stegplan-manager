import logging
import re
from urllib.parse import quote
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)

db = SQLAlchemy()

def build_db_uri(config):
    """Builds the database URI. Credentials may contain characters like @ or / and must be encoded."""
    user = quote(config['db_user'], safe='')
    password = quote(config['db_pass'], safe='')
    return f"postgresql://{user}:{password}@{config['db_host']}:{config['db_port']}/{config['db_name']}"

def make_slug(name):
    """Turns a room name into the part of its public address."""
    slug = name.lower().translate(str.maketrans({'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'}))
    return re.sub(r'[^a-z0-9]+', '-', slug).strip('-') or 'raum'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False) # Stays stable on rename, it is part of public URLs
    sort_order = db.Column(db.Integer, default=0, nullable=False)

class Setting(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=False)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=True) # NULL means the event belongs to the stegplan
    name = db.Column(db.String(100), nullable=False)
    weekday = db.Column(db.String(20), nullable=False)
    start_time = db.Column(db.String(10), nullable=False) # Format: "HH:MM"
    end_time = db.Column(db.String(10), nullable=False)   # Format: "HH:MM"
    season = db.Column(db.String(20), default="Immer")
    start_date = db.Column(db.String(5), default="")
    end_date = db.Column(db.String(5), default="")
    supervisor1 = db.Column(db.String(50), default="")
    supervisor2 = db.Column(db.String(50), default="")
    supervisor3 = db.Column(db.String(50), default="")
    comment = db.Column(db.String(200), default="")

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "weekday": self.weekday,
            "start_time": self.start_time, "end_time": self.end_time,
            "season": getattr(self, 'season', 'Immer') or 'Immer',
            "start_date": getattr(self, 'start_date', ''), 
            "end_date": getattr(self, 'end_date', ''),
            "supervisor1": self.supervisor1, "supervisor2": self.supervisor2,
            "supervisor3": self.supervisor3, "comment": self.comment
        }

class DatabaseManager:
    def init_app(self, app, config):
        """Initializes the database with the Flask app and creates default admin."""
        db.init_app(app)
        with app.app_context():
            db.create_all()
            self.migrate_schema()
            logger.info("Database initialized successfully.")
            if not User.query.first():
                admin_user = config.get('admin_user', 'admin')
                admin_pass = config.get('admin_pass', 'change-in-production')
                new_admin = User(username=admin_user, password_hash=generate_password_hash(admin_pass))
                db.session.add(new_admin)
                db.session.commit()
                logger.info(f"Default admin user '{admin_user}' created.")

    def migrate_schema(self):
        """Adds columns that db.create_all() does not add to existing tables."""
        columns = [column['name'] for column in inspect(db.engine).get_columns('event')]
        if 'room_id' not in columns:
            db.session.execute(text('ALTER TABLE event ADD COLUMN room_id INTEGER REFERENCES room(id)'))
            db.session.commit()
            logger.info("Added column event.room_id.")

    # --- User Operations ---
    def get_user(self, user_id):
        return User.query.get(int(user_id))

    def get_user_by_username(self, username):
        return User.query.filter_by(username=username).first()

    def get_all_users(self):
        return User.query.order_by(User.id).all()

    def add_user(self, username, password_hash):
        new_user = User(username=username, password_hash=password_hash)
        db.session.add(new_user)
        db.session.commit()

    def delete_user(self, user_id):
        user = self.get_user(user_id)
        if user:
            db.session.delete(user)
            db.session.commit()

    def update_user_password(self, user_id, new_password_hash):
        user = self.get_user(user_id)
        if user:
            user.password_hash = new_password_hash
            db.session.commit()

    # --- Setting Operations ---
    def get_setting(self, key, default=None):
        setting = db.session.get(Setting, key)
        return setting.value if setting else default

    def set_setting(self, key, value):
        db.session.merge(Setting(key=key, value=value))
        db.session.commit()

    # --- Room Operations ---
    def get_all_rooms(self):
        return Room.query.order_by(Room.sort_order, Room.name).all()

    def get_room(self, room_id):
        return Room.query.get_or_404(room_id)

    def get_room_by_slug(self, slug):
        return Room.query.filter_by(slug=slug).first()

    def get_room_by_name(self, name):
        return Room.query.filter_by(name=name).first()

    def add_room(self, name, sort_order=0):
        base_slug = make_slug(name)
        slug = base_slug
        suffix = 2
        while self.get_room_by_slug(slug):
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        room = Room(name=name, slug=slug, sort_order=sort_order)
        db.session.add(room)
        db.session.commit()
        return room

    def update_room(self, room_id, name, sort_order):
        room = self.get_room(room_id)
        room.name = name
        room.sort_order = sort_order
        db.session.commit()
        return room

    def delete_room(self, room_id):
        """Deletes a room with all of its events."""
        room = self.get_room(room_id)
        Event.query.filter_by(room_id=room.id).delete()
        db.session.delete(room)
        db.session.commit()

    def count_events(self, room_id=None):
        return Event.query.filter_by(room_id=room_id).count()

    # --- Event Operations ---
    def get_events(self, room_id=None):
        """Returns the events of a room, or of the stegplan without a room_id."""
        return Event.query.filter_by(room_id=room_id).all()

    def get_all_plans(self):
        """Returns (room, events) of all plans in display order. The stegplan comes first with room None."""
        return [(None, self.get_events())] + [(room, self.get_events(room.id)) for room in self.get_all_rooms()]

    def get_event(self, event_id):
        return Event.query.get_or_404(event_id)

    def add_event(self, **kwargs):
        new_event = Event(**kwargs)
        db.session.add(new_event)
        db.session.commit()
        return new_event

    def add_new_events(self, events_data, room_id=None):
        """Adds events that do not exist in the plan yet. Returns the number of added and skipped events."""
        known = {self.event_key(event.to_dict()) for event in self.get_events(room_id)}
        added, skipped = 0, 0
        for data in events_data:
            key = self.event_key(data)
            if key in known:
                skipped += 1
                continue
            known.add(key)
            db.session.add(Event(room_id=room_id, **data))
            added += 1
        db.session.commit()
        return added, skipped

    def event_key(self, data):
        """Identifies an event by its content. Stored dates only have a meaning for manual events."""
        fields = ['name', 'weekday', 'start_time', 'end_time', 'supervisor1', 'supervisor2', 'supervisor3', 'comment']
        season = data.get('season') or 'Immer'
        if season == 'Manuell':
            fields += ['start_date', 'end_date']
        return (season,) + tuple((data.get(field) or '').strip() for field in fields)

    def update_event(self, event_id, **kwargs):
        event = self.get_event(event_id)
        for key, value in kwargs.items():
            setattr(event, key, value)
        db.session.commit()
        return event

    def delete_event(self, event_id):
        event = self.get_event(event_id)
        db.session.delete(event)
        db.session.commit()

    def delete_all_events(self, room_id=None):
        """Deletes all events of a room, or of the stegplan without a room_id."""
        Event.query.filter_by(room_id=room_id).delete()
        db.session.commit()
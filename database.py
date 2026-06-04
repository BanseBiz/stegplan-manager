import logging
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
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
            logger.info("Database initialized successfully.")
            if not User.query.first():
                admin_user = config.get('admin_user', 'admin')
                admin_pass = config.get('admin_pass', 'change-in-production')
                new_admin = User(username=admin_user, password_hash=generate_password_hash(admin_pass))
                db.session.add(new_admin)
                db.session.commit()
                logger.info(f"Default admin user '{admin_user}' created.")

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

    # --- Event Operations ---
    def get_all_events(self):
        return Event.query.all()

    def get_event(self, event_id):
        return Event.query.get_or_404(event_id)

    def add_event(self, **kwargs):
        new_event = Event(**kwargs)
        db.session.add(new_event)
        db.session.commit()
        return new_event

    def add_events_bulk(self, events_data):
        for data in events_data:
            db.session.add(Event(**data))
        db.session.commit()

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

    def delete_all_events(self):
        Event.query.delete()
        db.session.commit()
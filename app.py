import json
import time
import threading
import logging
from datetime import datetime, timedelta
from flask import Flask
from flask_login import LoginManager
from database import DatabaseManager
from csv_handler import CsvHandler
from generator import DocumentGenerator
from frontend import Frontend
from localization import Localization
from flask_wtf.csrf import CSRFProtect

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- 1. Load configuration ---
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

app = Flask(__name__)

if not config.get('secret_key'):
    logger.critical("No 'secret_key' found in config.json. Shutting down.")
    raise ValueError("A 'secret_key' must be provided in config.json.")

insecure_default = "change-in-production"
for key in ['secret_key', 'db_pass', 'admin_pass']:
    if config.get(key) == insecure_default:
        logger.critical(f"Default insecure value found for '{key}' in config.json. Shutting down.")
        raise ValueError(f"You must change the default value '{insecure_default}' for '{key}' in config.json before running.")

app.secret_key = config['secret_key']

# Sicherheit: Upload-Größe auf 2 MB beschränken & Formulare absichern
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
csrf = CSRFProtect(app)

# --- 2. Initialize Login Manager ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Build database URI
db_uri = f"postgresql://{config['db_user']}:{config['db_pass']}@{config['db_host']}:{config['db_port']}/{config['db_name']}"
app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- 3. Initialize Components ---
db_manager = DatabaseManager()
db_manager.init_app(app, config)

csv_handler = CsvHandler()

loc = Localization()
doc_generator = DocumentGenerator(config, loc)

@app.context_processor
def inject_loc():
    return dict(t=loc.get)

# Initialize Frontend Routes
frontend = Frontend(app, db_manager, doc_generator, csv_handler, config, loc)

@login_manager.user_loader
def load_user(user_id):
    return db_manager.get_user(user_id)

# --- 4. Background Tasks ---
def schedule_midnight_generation(app_context, db_mgr, doc_gen):
    """Runs in the background and triggers SVG generation every night at 00:01."""
    while True:
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        # Set to 00:01 so that now() in the SVG generator definitely catches the new day
        next_run = datetime(year=tomorrow.year, month=tomorrow.month, day=tomorrow.day, hour=0, minute=1, second=0)
        sleep_seconds = (next_run - now).total_seconds()
        time.sleep(sleep_seconds)
        
        with app_context:
            try:
                events = db_mgr.get_all_events()
                doc_gen.generate_stegplan_svg(events)
                logger.info("Automatic nightly SVG generation successful.")
            except Exception as e:
                logger.error(f"Error during nightly SVG generation: {e}")

if __name__ == '__main__':
    # Start background thread for midnight generation
    threading.Thread(
        target=schedule_midnight_generation, 
        args=(app.app_context(), db_manager, doc_generator), 
        daemon=True
    ).start()
    
    app_host = config.get('app_host', '127.0.0.1')
    app_port = config.get('app_port', 5000)
    
    try:
        from waitress import serve
        logger.info(f"Starting production server on http://{app_host}:{app_port}")
        serve(app, host=app_host, port=app_port)
    except ImportError:
        logger.warning("Waitress not installed. Falling back to Flask dev server. Please run 'pip install waitress'.")
        app.run(host=app_host, port=app_port, debug=False)
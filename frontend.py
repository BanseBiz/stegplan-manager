import os
import io
import logging
import re
from datetime import datetime
from flask import request, render_template, redirect, url_for, send_from_directory, send_file, Response
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

logger = logging.getLogger(__name__)

class Frontend:
    """Handles web routes and HTTP requests."""

    def __init__(self, app, db_manager, doc_generator, csv_handler, config, loc):
        self.app = app
        self.db_manager = db_manager
        self.doc_generator = doc_generator
        self.csv_handler = csv_handler
        self.config = config
        self.loc = loc
        self.register_routes()

    def admin_required(self, f):
        """Decorator that checks if the logged-in user is the admin."""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            admin_username = self.config.get('admin_user', 'admin')
            if not current_user.is_authenticated or current_user.username != admin_username:
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function

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

    def register_routes(self):
        
        @self.app.context_processor
        def inject_config():
            """Makes the configuration available to all templates."""
            return dict(config=self.config)

        # --- Authentication ---
        @self.app.route('/login', methods=['GET', 'POST'])
        def login():
            """Login page for administration."""
            if request.method == 'POST':
                username = request.form.get('username')
                password = request.form.get('password')
                user = self.db_manager.get_user_by_username(username)
                if user and check_password_hash(user.password_hash, password):
                    login_user(user)
                    return redirect(url_for('index'))
                return render_template('login.html', error="Invalid username or password.")
            return render_template('login.html')

        @self.app.route('/logout')
        @login_required
        def logout():
            logout_user()
            return redirect(url_for('login'))

        # --- Dashboard ---
        @self.app.route('/')
        @login_required
        def index():
            """Displays all events and checks if the SVG exists."""
            events = self.db_manager.get_all_events()
            day_order = {'Montag': 1, 'Dienstag': 2, 'Mittwoch': 3, 'Donnerstag': 4, 'Freitag': 5, 'Samstag': 6, 'Sonntag': 7}
            events_sorted = sorted(events, key=lambda x: (day_order.get(x.weekday, 99), x.start_time))
            
            svg_path = self.config.get('svg_output_path', '/var/www/res/stegplan.svg')
            svg_exists = os.path.exists(svg_path)
            
            timetable_path = self.config.get('timetable_output_path', '/var/www/res/stundenplan.svg')
            stundenplan_exists = os.path.exists(timetable_path)
            
            return render_template('index.html', events=events_sorted, svg_exists=svg_exists, stundenplan_exists=stundenplan_exists)

        # --- SVG Serving ---
        @self.app.route('/stegplan.svg')
        def serve_svg():
            """Serves the SVG file from the configured directory."""
            svg_path = self.config.get('svg_output_path', '/var/www/res/stegplan.svg')
            directory = os.path.dirname(svg_path)
            filename = os.path.basename(svg_path)
            return send_from_directory(directory, filename, etag=False, last_modified=None)

        @self.app.route('/stundenplan.svg')
        def serve_stundenplan_svg():
            """Serves the timetable SVG file from the configured directory."""
            timetable_path = self.config.get('timetable_output_path', '/var/www/res/stundenplan.svg')
            directory = os.path.dirname(timetable_path)
            filename = os.path.basename(timetable_path)
            return send_from_directory(directory, filename, etag=False, last_modified=None)

        # --- PDF Downloads ---
        @self.app.route('/download/stegplan.pdf')
        @login_required
        def download_stegplan_pdf():
            """Converts the stegplan to PDF (optionally for a specific date and orientation)."""
            date_str = request.args.get('date')
            orientation = request.args.get('orientation', 'portrait')
            target_date = datetime.now()
            
            if date_str:
                try:
                    target_date = datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError:
                    pass

            all_events = self.db_manager.get_all_events()
            pdf_stream = self.doc_generator.generate_stegplan_pdf_for_date(all_events, target_date, orientation)
            
            base_filename = self.loc.get('filename_schedule')
            filename = f'{base_filename}_{target_date.strftime("%Y%m%d")}.pdf'
            return send_file(pdf_stream, download_name=filename, as_attachment=True, mimetype='application/pdf')

        @self.app.route('/download/stundenplan.pdf')
        @login_required
        def download_stundenplan_pdf():
            """Converts the timetable to PDF (optionally for a specific date)."""
            date_str = request.args.get('date')
            target_date = datetime.now()
            
            if date_str:
                try:
                    target_date = datetime.strptime(date_str, '%Y-%m-%d')
                except ValueError:
                    pass

            all_events = self.db_manager.get_all_events()
            pdf_stream = self.doc_generator.generate_stundenplan_pdf_for_date(all_events, target_date)
            
            base_filename = self.loc.get('filename_timetable')
            filename = f'{base_filename}_{target_date.strftime("%Y%m%d")}.pdf'
            return send_file(pdf_stream, download_name=filename, as_attachment=True, mimetype='application/pdf')

        # --- Event Management ---
        @self.app.route('/add', methods=['GET', 'POST'])
        @login_required
        def add_event():
            """Show form / evaluate new event."""
            error = None
            if request.method == 'POST':
                start_date = request.form.get('start_date', '').strip()
                end_date = request.form.get('end_date', '').strip()

                if not self.is_valid_date(start_date) or not self.is_valid_date(end_date):
                    error = "error_invalid_date"
                    return render_template('edit_event.html', event=None, error=error)

                self.db_manager.add_event(
                    name=request.form['name'],
                    weekday=request.form['weekday'],
                    start_time=request.form['start_time'],
                    end_time=request.form['end_time'],
                    season=request.form.get('season', 'Immer'),
                    start_date=start_date,
                    end_date=end_date,
                    supervisor1=request.form.get('supervisor1', ''),
                    supervisor2=request.form.get('supervisor2', ''),
                    supervisor3=request.form.get('supervisor3', ''),
                    comment=request.form.get('comment', '')
                )
                try:
                    self.doc_generator.generate_stegplan_svg(self.db_manager.get_all_events())
                except Exception as e:
                    logger.error(f"Error generating SVG: {e}")
                return redirect(url_for('index'))
            return render_template('edit_event.html', event=None)

        @self.app.route('/edit/<int:id>', methods=['GET', 'POST'])
        @login_required
        def edit_event(id):
            """Edit an existing event."""
            event = self.db_manager.get_event(id)
            error = None
            if request.method == 'POST':
                start_date = request.form.get('start_date', '').strip()
                end_date = request.form.get('end_date', '').strip()

                if not self.is_valid_date(start_date) or not self.is_valid_date(end_date):
                    error = "error_invalid_date"
                    return render_template('edit_event.html', event=event, error=error)

                self.db_manager.update_event(
                    id,
                    name=request.form['name'],
                    weekday=request.form['weekday'],
                    start_time=request.form['start_time'],
                    end_time=request.form['end_time'],
                    season=request.form.get('season', 'Immer'),
                    start_date=start_date,
                    end_date=end_date,
                    supervisor1=request.form.get('supervisor1', ''),
                    supervisor2=request.form.get('supervisor2', ''),
                    supervisor3=request.form.get('supervisor3', ''),
                    comment=request.form.get('comment', '')
                )
                try:
                    self.doc_generator.generate_stegplan_svg(self.db_manager.get_all_events())
                except Exception as e:
                    logger.error(f"Error generating SVG: {e}")
                return redirect(url_for('index'))
            return render_template('edit_event.html', event=event)

        @self.app.route('/delete/<int:id>', methods=['POST'])
        @login_required
        def delete_event(id):
            """Delete an event."""
            self.db_manager.delete_event(id)
            try:
                self.doc_generator.generate_stegplan_svg(self.db_manager.get_all_events())
            except Exception as e:
                logger.error(f"Error generating SVG: {e}")
            return redirect(url_for('index'))

        @self.app.route('/delete-all', methods=['POST'])
        @login_required
        def delete_all_events():
            """Delete all events."""
            try:
                self.db_manager.delete_all_events()
                self.doc_generator.generate_stegplan_svg(self.db_manager.get_all_events())
            except Exception as e:
                logger.error(f"Error deleting all events: {e}")
            return redirect(url_for('index'))

        # --- CSV Import / Export ---
        @self.app.route('/import-csv', methods=['POST'])
        @login_required
        def import_csv():
            """Imports events from an uploaded CSV file."""
            if 'csv_file' not in request.files:
                return redirect(url_for('index'))
            
            file = request.files['csv_file']
            if file.filename == '':
                return redirect(url_for('index'))
                
            if file and file.filename.endswith('.csv'):
                try:
                    file_bytes = file.stream.read()
                    events_to_add = self.csv_handler.parse_csv_to_events(file_bytes)
                    self.db_manager.add_events_bulk(events_to_add)
                    self.doc_generator.generate_stegplan_svg(self.db_manager.get_all_events())
                except Exception as e:
                    logger.error(f"Error during CSV import: {e}")
                    
            return redirect(url_for('index'))

        @self.app.route('/export-csv')
        @login_required
        def export_csv():
            """Exports all events to a CSV file."""
            events = self.db_manager.get_all_events()
            csv_string = self.csv_handler.generate_csv_from_events(events)
            
            response = Response(csv_string, mimetype='text/csv')
            filename = f"{self.loc.get('filename_csv_export')}.csv"
            response.headers["Content-Disposition"] = f"attachment; filename={filename}"
            return response

        # --- User Management ---
        @self.app.route('/users')
        @login_required
        @self.admin_required
        def manage_users():
            """Page for user management (admins only)."""
            users = self.db_manager.get_all_users()
            admin_username = self.config.get('admin_user', 'admin')
            return render_template('users.html', users=users, admin_username=admin_username)

        @self.app.route('/users/add', methods=['POST'])
        @login_required
        @self.admin_required
        def add_user():
            """Adds a new user (admins only)."""
            username = request.form.get('username')
            password = request.form.get('password')
            if username and password and len(password) >= 8:
                if not self.db_manager.get_user_by_username(username):
                    self.db_manager.add_user(username, generate_password_hash(password))
            return redirect(url_for('manage_users'))

        @self.app.route('/users/delete/<int:user_id>', methods=['POST'])
        @login_required
        @self.admin_required
        def delete_user(user_id):
            """Deletes a user (admins only)."""
            user_to_delete = self.db_manager.get_user(user_id)
            admin_username = self.config.get('admin_user', 'admin')
            # Prevent the admin from deleting themselves
            if user_to_delete and user_to_delete.username != admin_username:
                self.db_manager.delete_user(user_id)
            return redirect(url_for('manage_users'))

        @self.app.route('/change-password', methods=['GET', 'POST'])
        @login_required
        def change_password():
            """Allows logged-in users to change their password."""
            error = None
            success = None
            if request.method == 'POST':
                current_password = request.form.get('current_password')
                new_password = request.form.get('new_password')
                confirm_password = request.form.get('confirm_password')

                if not check_password_hash(current_user.password_hash, current_password):
                    error = "Das aktuelle Passwort ist nicht korrekt."
                elif new_password != confirm_password:
                    error = "Die neuen Passwörter stimmen nicht überein."
                elif len(new_password) < 8:
                    error = "Das neue Passwort muss mindestens 8 Zeichen lang sein."
                else:
                    self.db_manager.update_user_password(current_user.id, generate_password_hash(new_password))
                    success = "Dein Passwort wurde erfolgreich geändert."
            return render_template('change_password.html', error=error, success=success)

        @self.app.route('/generate-svg', methods=['POST'])
        @login_required
        def generate_svg():
            """Manual trigger for SVG generation."""
            try:
                self.doc_generator.generate_stegplan_svg(self.db_manager.get_all_events())
                return redirect(url_for('index'))
            except Exception as e:
                logger.error(f"Manual SVG generation failed: {e}")
                return f"Error generating SVG: {e}", 500
import os
import io
import logging
from datetime import datetime
from flask import abort, flash, request, render_template, redirect, url_for, send_from_directory, send_file, Response
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

logger = logging.getLogger(__name__)

class Frontend:
    """Handles web routes and HTTP requests."""

    MAX_CSV_ERRORS = 5
    CONTENT_SECURITY_POLICY = (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    )

    def __init__(self, app, db_manager, doc_generator, csv_handler, config, loc):
        self.app = app
        self.db_manager = db_manager
        self.doc_generator = doc_generator
        self.csv_handler = csv_handler
        self.config = config
        self.loc = loc
        self.app.config.update(
            SESSION_COOKIE_SECURE=self.config.get('https_only', True),
            SESSION_COOKIE_SAMESITE='Lax'
        )
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

    def flash_csv_errors(self, errors):
        """Shows the first errors of a rejected CSV file."""
        for line, key, value in errors[:self.MAX_CSV_ERRORS]:
            flash(self.loc.get(key, line, value), 'error')
        if len(errors) > self.MAX_CSV_ERRORS:
            flash(self.loc.get('csv_error_more', len(errors) - self.MAX_CSV_ERRORS), 'error')

    def is_admin(self):
        return current_user.is_authenticated and current_user.username == self.config.get('admin_user', 'admin')

    def can_manage(self, room):
        """Checks if the current user may see and change a room, or the stegplan for None."""
        if self.is_admin():
            return True
        if not current_user.is_authenticated:
            return False
        if room is None:
            return bool(current_user.manages_stegplan)
        return room.id in {managed.id for managed in current_user.managed_rooms}

    def require_access(self, room):
        """Returns the room if the current user manages it. Other plans do not exist for them."""
        if not self.can_manage(room):
            abort(404)
        return room

    def visible_rooms(self):
        """Returns the rooms the current user manages, in display order."""
        return [room for room in self.db_manager.get_all_rooms() if self.can_manage(room)]

    def assignable_users(self):
        """Returns the users that can be assigned to plans. The admin always has access."""
        admin_username = self.config.get('admin_user', 'admin')
        return [user for user in self.db_manager.get_all_users() if user.username != admin_username]

    def selected_user_ids(self):
        """Returns the ids of the assignable users checked in the submitted form."""
        checked = set(request.form.getlist('managers'))
        return [user.id for user in self.assignable_users() if str(user.id) in checked]

    def room_from_request(self):
        """Returns the room a request refers to, or None for the stegplan, if the current user manages it."""
        slug = request.values.get('room')
        return self.require_access(self.get_room_or_404(slug) if slug else None)

    def get_room_or_404(self, slug):
        room = self.db_manager.get_room_by_slug(slug)
        if not room:
            abort(404)
        return room

    def room_of(self, event):
        """Returns the room of an event, or None for the stegplan, if the current user manages it."""
        return self.require_access(self.db_manager.get_room(event.room_id) if event.room_id else None)

    def plan_url(self, room):
        """Returns the dashboard address of a room or the stegplan."""
        return url_for('room_plan', slug=room.slug) if room else url_for('index')

    def overview_notes(self):
        """Returns the notes of the overview, the defaults until the admin changes them."""
        return self.db_manager.get_setting('overview_notes', self.loc.get('overview_notes_default'))

    def regenerate_overview(self):
        """Regenerates the SVG file of the overview."""
        try:
            self.doc_generator.generate_overview_svg(self.db_manager.get_overview_plans(), self.overview_notes())
        except Exception as e:
            logger.error(f"Error generating overview SVG: {e}")

    def regenerate_plan(self, room):
        """Regenerates the SVG files of a room or the stegplan and the overview. Returns False if that failed."""
        generated = True
        try:
            if room:
                self.doc_generator.generate_room_svg(room, self.db_manager.get_events(room.id))
            else:
                self.doc_generator.generate_stegplan_svg(self.db_manager.get_events())
        except Exception as e:
            logger.error(f"Error generating SVG: {e}")
            generated = False
        self.regenerate_overview()
        return generated

    def event_form_data(self, start_date, end_date):
        """Returns the event fields of a submitted form."""
        return dict(
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

    def render_event_form(self, room, event=None, error=None):
        other_rooms = []
        if room and not event:
            other_rooms = [other for other in self.visible_rooms() if other.id != room.id]
        return render_template('edit_event.html', event=event, error=error, room=room, other_rooms=other_rooms, back_url=self.plan_url(room))

    def render_dashboard(self, room):
        """Displays the events and previews of a room or the stegplan."""
        events = self.db_manager.get_events(room.id if room else None)
        day_order = {'Montag': 1, 'Dienstag': 2, 'Mittwoch': 3, 'Donnerstag': 4, 'Freitag': 5, 'Samstag': 6, 'Sonntag': 7}
        events_sorted = sorted(events, key=lambda x: (day_order.get(x.weekday, 99), x.start_time))

        svg_path = self.config.get('svg_output_path', '/var/www/res/stegplan.svg')
        timetable_path = self.config.get('timetable_output_path', '/var/www/res/stundenplan.svg')
        room_svg_exists = bool(room) and os.path.exists(self.doc_generator.get_room_svg_path(room))

        return render_template(
            'index.html', events=events_sorted, room=room, rooms=self.visible_rooms(), plan_actions=True,
            svg_exists=os.path.exists(svg_path), stundenplan_exists=os.path.exists(timetable_path), room_svg_exists=room_svg_exists
        )

    def pdf_target_date(self):
        """Returns the date requested for a PDF, today if it is missing or invalid."""
        date_str = request.args.get('date')
        if date_str:
            try:
                return datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                pass
        return datetime.now()

    def register_routes(self):
        
        @self.app.context_processor
        def inject_config():
            """Makes the configuration and the access to the stegplan available to all templates."""
            return dict(config=self.config, stegplan_access=self.can_manage(None))

        @self.app.after_request
        def set_security_headers(response):
            """Adds security headers to every response."""
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Referrer-Policy'] = 'same-origin'
            if self.config.get('https_only', True):
                response.headers['Strict-Transport-Security'] = 'max-age=2592000'
            # Only for pages: the SVGs need their inline <style> and are embedded elsewhere
            if response.mimetype == 'text/html':
                response.headers['Content-Security-Policy'] = self.CONTENT_SECURITY_POLICY
            return response

        # --- Authentication ---
        @self.app.route('/login', methods=['GET', 'POST'])
        def login():
            """Login page for administration."""
            if request.method == 'POST':
                username = request.form.get('username')
                password = request.form.get('password', '')
                user = self.db_manager.get_user_by_username(username)
                if user and check_password_hash(user.password_hash, password):
                    login_user(user)
                    return redirect(url_for('index'))
                return render_template('login.html', error="error_invalid_login")
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
            """Displays the stegplan events, or leads users without access to their first plan."""
            if not self.can_manage(None):
                rooms = self.visible_rooms()
                return redirect(self.plan_url(rooms[0]) if rooms else url_for('overview'))
            return self.render_dashboard(None)

        @self.app.route('/raum/<slug>')
        @login_required
        def room_plan(slug):
            """Displays the events of a room."""
            return self.render_dashboard(self.require_access(self.get_room_or_404(slug)))

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

        @self.app.route('/raumplan/<slug>.svg')
        def serve_room_svg(slug):
            """Serves the SVG file of a room."""
            svg_path = self.doc_generator.get_room_svg_path(self.get_room_or_404(slug))
            directory = os.path.dirname(svg_path)
            filename = os.path.basename(svg_path)
            return send_from_directory(directory, filename, etag=False, last_modified=None)

        @self.app.route('/nutzungszeiten.svg')
        def serve_overview_svg():
            """Serves the SVG file of the overview."""
            svg_path = self.doc_generator.get_overview_svg_path()
            directory = os.path.dirname(svg_path)
            filename = os.path.basename(svg_path)
            return send_from_directory(directory, filename, etag=False, last_modified=None)

        # --- PDF Downloads ---
        @self.app.route('/download/stegplan.pdf')
        @login_required
        def download_stegplan_pdf():
            """Converts the stegplan to PDF (optionally for a specific date and orientation)."""
            self.require_access(None)
            orientation = request.args.get('orientation', 'portrait')
            target_date = self.pdf_target_date()

            all_events = self.db_manager.get_events()
            pdf_stream = self.doc_generator.generate_stegplan_pdf_for_date(all_events, target_date, orientation)
            
            base_filename = self.loc.get('filename_schedule')
            filename = f'{base_filename}_{target_date.strftime("%Y%m%d")}.pdf'
            return send_file(pdf_stream, download_name=filename, as_attachment=True, mimetype='application/pdf')

        @self.app.route('/download/stundenplan.pdf')
        @login_required
        def download_stundenplan_pdf():
            """Converts the timetable to PDF (optionally for a specific date)."""
            self.require_access(None)
            target_date = self.pdf_target_date()

            all_events = self.db_manager.get_events()
            pdf_stream = self.doc_generator.generate_stundenplan_pdf_for_date(all_events, target_date)
            
            base_filename = self.loc.get('filename_timetable')
            filename = f'{base_filename}_{target_date.strftime("%Y%m%d")}.pdf'
            return send_file(pdf_stream, download_name=filename, as_attachment=True, mimetype='application/pdf')

        @self.app.route('/download/raum/<slug>.pdf')
        @login_required
        def download_room_pdf(slug):
            """Converts the plan of a room to PDF (optionally for a specific date)."""
            room = self.require_access(self.get_room_or_404(slug))
            target_date = self.pdf_target_date()

            pdf_stream = self.doc_generator.generate_room_pdf_for_date(room, self.db_manager.get_events(room.id), target_date)

            filename = f"{self.loc.get('filename_room')}-{room.slug}_{target_date.strftime('%Y%m%d')}.pdf"
            return send_file(pdf_stream, download_name=filename, as_attachment=True, mimetype='application/pdf')

        # --- Event Management ---
        @self.app.route('/add', methods=['GET', 'POST'])
        @login_required
        def add_event():
            """Show form / evaluate new event."""
            room = self.room_from_request()
            if request.method == 'POST':
                start_date = request.form.get('start_date', '').strip()
                end_date = request.form.get('end_date', '').strip()

                if not self.csv_handler.is_valid_date(start_date) or not self.csv_handler.is_valid_date(end_date):
                    return self.render_event_form(room, error="error_invalid_date")

                data = self.event_form_data(start_date, end_date)
                self.db_manager.add_event(room_id=room.id if room else None, **data)
                self.regenerate_plan(room)

                # Copies in further rooms are independent events
                if room:
                    copy_ids = request.form.getlist('copy_to_rooms')
                    for other in self.visible_rooms():
                        if other.id != room.id and str(other.id) in copy_ids:
                            self.db_manager.add_event(room_id=other.id, **data)
                            self.regenerate_plan(other)
                return redirect(self.plan_url(room))
            return self.render_event_form(room)

        @self.app.route('/edit/<int:id>', methods=['GET', 'POST'])
        @login_required
        def edit_event(id):
            """Edit an existing event."""
            event = self.db_manager.get_event(id)
            room = self.room_of(event)
            if request.method == 'POST':
                start_date = request.form.get('start_date', '').strip()
                end_date = request.form.get('end_date', '').strip()

                if not self.csv_handler.is_valid_date(start_date) or not self.csv_handler.is_valid_date(end_date):
                    return self.render_event_form(room, event, "error_invalid_date")

                self.db_manager.update_event(id, **self.event_form_data(start_date, end_date))
                self.regenerate_plan(room)
                return redirect(self.plan_url(room))
            return self.render_event_form(room, event)

        @self.app.route('/delete/<int:id>', methods=['POST'])
        @login_required
        def delete_event(id):
            """Delete an event."""
            room = self.room_of(self.db_manager.get_event(id))
            self.db_manager.delete_event(id)
            self.regenerate_plan(room)
            return redirect(self.plan_url(room))

        @self.app.route('/delete-all', methods=['POST'])
        @login_required
        def delete_all_events():
            """Delete all events of a room or the stegplan."""
            room = self.room_from_request()
            try:
                self.db_manager.delete_all_events(room.id if room else None)
            except Exception as e:
                logger.error(f"Error deleting all events: {e}")
            self.regenerate_plan(room)
            return redirect(self.plan_url(room))

        # --- CSV Import / Export ---
        @self.app.route('/import-csv', methods=['POST'])
        @login_required
        def import_csv():
            """Imports events from an uploaded CSV file into a room or the stegplan."""
            room = self.room_from_request()
            file = request.files.get('csv_file')
            if not file or file.filename == '':
                return redirect(self.plan_url(room))

            if not file.filename.lower().endswith('.csv'):
                flash(self.loc.get('csv_error_file_type'), 'error')
                return redirect(self.plan_url(room))

            try:
                events_to_add, errors = self.csv_handler.parse_csv_to_events(file.stream.read())
                if errors:
                    self.flash_csv_errors(errors)
                    return redirect(self.plan_url(room))
                added, skipped = self.db_manager.add_new_events(events_to_add, room.id if room else None)
                flash(self.loc.get('csv_import_result', added, skipped), 'success')
            except Exception as e:
                logger.error(f"Error during CSV import: {e}")
                flash(self.loc.get('csv_import_failed'), 'error')
                return redirect(self.plan_url(room))

            if not self.regenerate_plan(room):
                flash(self.loc.get('csv_generation_failed'), 'error')
            return redirect(self.plan_url(room))

        @self.app.route('/export-csv')
        @login_required
        def export_csv():
            """Exports the events of a room or the stegplan to a CSV file."""
            room = self.room_from_request()
            events = self.db_manager.get_events(room.id if room else None)
            csv_string = self.csv_handler.generate_csv_from_events(events)
            
            response = Response(csv_string, mimetype='text/csv')
            filename = f"orvo-raum-{room.slug}.csv" if room else f"{self.loc.get('filename_csv_export')}.csv"
            response.headers["Content-Disposition"] = f"attachment; filename={filename}"
            return response

        # --- Overview ---
        @self.app.route('/uebersicht')
        @login_required
        def overview():
            """Displays the overview of all plans."""
            return render_template(
                'overview.html', rooms=self.visible_rooms(), notes=self.overview_notes(), is_admin=self.is_admin(),
                overview_exists=os.path.exists(self.doc_generator.get_overview_svg_path())
            )

        @self.app.route('/uebersicht/notes', methods=['POST'])
        @login_required
        @self.admin_required
        def save_overview_notes():
            """Saves the notes of the overview (admins only)."""
            self.db_manager.set_setting('overview_notes', request.form.get('notes', '').strip())
            self.regenerate_overview()
            flash(self.loc.get('overview_notes_saved'), 'success')
            return redirect(url_for('overview'))

        # --- Room Management ---
        @self.app.route('/rooms')
        @login_required
        @self.admin_required
        def manage_rooms():
            """Page for room management (admins only)."""
            rooms = self.db_manager.get_all_rooms()
            event_counts = {room.id: self.db_manager.count_events(room.id) for room in rooms}
            stegplan_managers = [user for user in self.assignable_users() if user.manages_stegplan]
            next_order = max((room.sort_order for room in rooms), default=0) + 1
            return render_template(
                'rooms.html', rooms=rooms, event_counts=event_counts, stegplan_count=self.db_manager.count_events(),
                stegplan_managers=stegplan_managers, next_order=next_order
            )

        def read_room_form(room_id=None):
            """Returns the submitted name and order of a room, or None after flashing an error."""
            name = request.form.get('name', '').strip()
            try:
                sort_order = int(request.form.get('sort_order', 0))
            except ValueError:
                sort_order = 0
            if not name or len(name) > 100:
                flash(self.loc.get('room_error_name'), 'error')
                return None
            existing = self.db_manager.get_room_by_name(name)
            if existing and existing.id != room_id:
                flash(self.loc.get('room_error_duplicate', name), 'error')
                return None
            return name, sort_order

        @self.app.route('/rooms/add', methods=['POST'])
        @login_required
        @self.admin_required
        def add_room():
            """Adds a new room with an empty plan and continues with its settings (admins only)."""
            values = read_room_form()
            if not values:
                return redirect(url_for('manage_rooms'))
            room = self.db_manager.add_room(*values)
            self.regenerate_plan(room)
            return redirect(url_for('edit_room', room_id=room.id))

        @self.app.route('/rooms/<int:room_id>', methods=['GET', 'POST'])
        @login_required
        @self.admin_required
        def edit_room(room_id):
            """Edits name, order, overview flag and managers of a room (admins only). Its public address stays the same."""
            room = self.db_manager.get_room(room_id)
            if request.method == 'POST':
                values = read_room_form(room_id)
                if values:
                    self.db_manager.update_room(room_id, *values, show_in_overview='show_in_overview' in request.form)
                    self.db_manager.set_room_managers(room_id, self.selected_user_ids())
                    self.regenerate_plan(room)
                    flash(self.loc.get('room_saved', room.name), 'success')
                    return redirect(url_for('manage_rooms'))
                return redirect(url_for('edit_room', room_id=room_id))
            selected = {user.id for user in room.managers}
            return render_template('room_edit.html', room=room, users=self.assignable_users(), selected=selected)

        @self.app.route('/rooms/stegplan', methods=['GET', 'POST'])
        @login_required
        @self.admin_required
        def edit_stegplan():
            """Edits the managers of the stegplan (admins only)."""
            if request.method == 'POST':
                self.db_manager.set_stegplan_managers(self.selected_user_ids())
                flash(self.loc.get('room_saved', self.loc.get('tab_stegplan')), 'success')
                return redirect(url_for('manage_rooms'))
            selected = {user.id for user in self.assignable_users() if user.manages_stegplan}
            return render_template('room_edit.html', room=None, users=self.assignable_users(), selected=selected)

        @self.app.route('/rooms/delete/<int:room_id>', methods=['POST'])
        @login_required
        @self.admin_required
        def delete_room(room_id):
            """Deletes a room with all of its events (admins only)."""
            room = self.db_manager.get_room(room_id)
            try:
                self.doc_generator.delete_room_svg(room)
            except OSError as e:
                logger.error(f"Error removing room SVG: {e}")
            self.db_manager.delete_room(room_id)
            self.regenerate_overview()
            return redirect(url_for('manage_rooms'))

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
                current_password = request.form.get('current_password', '')
                new_password = request.form.get('new_password', '')
                confirm_password = request.form.get('confirm_password', '')

                if not check_password_hash(current_user.password_hash, current_password):
                    error = "error_current_pw"
                elif new_password != confirm_password:
                    error = "error_pw_mismatch"
                elif len(new_password) < 8:
                    error = "error_pw_length"
                else:
                    self.db_manager.update_user_password(current_user.id, generate_password_hash(new_password))
                    success = "success_pw_changed"
            return render_template('change_password.html', error=error, success=success)

        @self.app.route('/generate-svg', methods=['POST'])
        @login_required
        def generate_svg():
            """Manual trigger for SVG generation of all plans."""
            try:
                self.doc_generator.generate_stegplan_svg(self.db_manager.get_events())
                for room in self.db_manager.get_all_rooms():
                    self.doc_generator.generate_room_svg(room, self.db_manager.get_events(room.id))
                self.regenerate_overview()
                return redirect(url_for('index'))
            except Exception as e:
                logger.error(f"Manual SVG generation failed: {e}")
                return f"Error generating SVG: {e}", 500
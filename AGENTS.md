# ORVO Stegplan - AI Agents Context

This document serves as a central knowledge base for AI-powered coding assistants to understand the context, structure, and architecture of the `stegplan` project.

## Project Overview
The project is a web-based application for managing schedule plans (Stegplan) and timetables for a rowing club (ORVO). 
Users can create, edit, and delete events. The application automatically generates visually appealing vector graphics (SVGs) from this data and also offers them as PDF downloads.

## Tech Stack
- **Backend:** Python 3, Flask
- **Production Server:** Waitress (WSGI)
- **Database:** PostgreSQL (managed via Flask-SQLAlchemy, Repository Pattern)
- **Authentication:** Flask-Login, Werkzeug (Password Hashing), Flask-WTF (CSRF Protection)
- **Frontend:** HTML5, Jinja2 Templates, Tailwind CSS (compiled into `static/style.css`), plain JavaScript (`static/app.js`)
- **Generation & Export:** 
  - SVG: Custom-built via string concatenation in Python.
  - PDF: `cairosvg` for converting SVG to PDF.
  - Hyphenation: `pyphen` (German) for intelligent text wrapping in the SVGs.
- **Localization:** Custom JSON-based i18n module.

## Project Structure

- `/app.py`: The entry point. Initializes config, database, components, and starts the Waitress server and the midnight SVG-generation background thread.
- `/database.py`: Contains SQLAlchemy models (`User`, `Room`, `Event`, `Setting`) and the `DatabaseManager` (Repository Pattern) handling all DB interactions.
- `/frontend.py`: Contains the `Frontend` class with all Flask routes, authentication checks, and web UI logic.
- `/generator.py`: Contains the `DocumentGenerator` for assembling the complex SVG strings and converting them to PDFs.
- `/csv_handler.py`: Handles CSV parsing (import) and creation (export).
- `/localization.py` & `/localization.json`: Custom i18n system. Injects a `t(key)` function into Jinja templates.
- `/config.json`: External configuration file. Contains database credentials, output paths (`svg_output_path`, `timetable_output_path`, `room_output_dir`, `overview_output_path`), host/port, season start dates, and the initial admin account.
- `/stegplan.service`: systemd unit file for deploying the application as a background service on a Linux server.
- `/templates/`: Jinja2 views.
  - `layout.html`: Base template including navigation and the PDF dialogs.
  - `index.html`: Dashboard with the event overview and SVG previews.
  - `edit_event.html`: Form for new/existing events.
  - `users.html`: User management (admins only).
  - `rooms.html`: Room management (admins only).
  - `overview.html`: Overview of all plans, the admin edits its notes here.
  - `plan_tabs.html`: Tabs between the plans, included by `index.html` and `overview.html`.
  - `login.html` & `change_password.html`: Authentication views.

## Architecture & Special Features

1. **Database & Initialization:**
   - Handled by `DatabaseManager`. Automatic creation of tables and default admin user on startup.
   - `db.create_all()` does not extend existing tables. New columns on existing tables need an idempotent, additive step in `DatabaseManager.migrate_schema`.
   - An event belongs to a room via `Event.room_id`, `NULL` means the stegplan. Always pass the plan to `get_events`, `delete_all_events` and `add_new_events`, otherwise room events are missed or the wrong plan is changed.
   - Events have seasonal limits (`season`, `start_date`, `end_date`) to filter visibility based on the generated date. `Sommer` and `Winter` events follow `sommerphase_start` / `winterphase_start` from `config.json`; only `Manuell` events use their stored dates.

2. **SVG Generation (IMPORTANT):**
   - SVG is assembled directly via Python lists (`svg.append(...)`) and f-strings in `generator.py`.
   - Two plans are generated: Stegplan (2-column tile layout) and Stundenplan (classic A4 timetable grid). Each room adds a timetable with a grid fitted to its events (`generate_room_svg`).
   - The overview (`generate_overview_svg`) lists all active events by plan in a fixed layout with notes stored in `Setting`. Its layout follows the former hand-made `26-nutzungszeiten.svg`, so keep the look when changing it. `Frontend.regenerate_plan` also updates the overview, other changes must call `regenerate_overview`.
   - Generated automatically on event modification and nightly at 00:01 via a daemon thread in `app.py`.
   - The Stundenplan is printed in black and white: text and lines are pure black on white, without tinted backgrounds, transparency or shadows. Color is only an accent and must never be the only carrier of information.

3. **Time and Text Processing:**
   - Start and end times of events are stored as strings in the `HH:MM` 24-hour format.
   - The project uses `pyphen` for correct German hyphenation within the SVG tiles (function `wrap_text_with_hyphens`).

4. **Localization & Permissions:**
   - All UI text is loaded from `localization.json` via the `t()` function.
   - The app is hidden behind `@login_required`, except `/login` and the generated plans `/stegplan.svg`, `/stundenplan.svg`, `/raumplan/<slug>.svg` and `/nutzungszeiten.svg`, which are public on purpose.
   - There is a designated "Admin User" defined in `config.json` who has exclusive access to `/users` and `/rooms`.

## Coding Conventions for AI Agents

- **Language:** Code, variables, class names, database columns, and comments MUST be in **English**. User interface strings MUST be extracted into `localization.json` and referenced via keys.
- **Styling (CSS):** Use Tailwind classes exclusively in HTML. Do not write custom CSS unless absolutely necessary within the SVG (`<style>` tag). `static/style.css` is generated: after adding classes to templates or `static/app.js`, rebuild it with the Tailwind v3 standalone CLI (see `README.md`).
- **Content Security Policy:** Pages are served with a strict CSP. No inline scripts, event handlers (`onclick=`), `style=` attributes or external resources in templates. JavaScript belongs in `static/app.js` and gets its values from `data-*` attributes.
- **No unnecessary dependencies:** Before suggesting new pip packages, check if it can be done with the Python standard library (as already done with `csv` or `datetime`).
- **Error Handling:** When making changes to the code that modifies the SVG or the database, wrap it in a robust `try-except` block, as is customary in the codebase.
- **Logging:** Use Python's `logging` module (`logger.info`, `logger.error`) instead of `print()`.

## Typical Development Workflows

- **Add a new field:** 1. Update DB model `Event` in `database.py` and extend `to_dict()`. 2. Add field to `add_event` / `edit_event` routes in `frontend.py`. 3. Update frontend templates (`edit_event.html`, `index.html`). 4. Adjust SVG generation in `generator.py`. 5. Add translations to `localization.json`.
- **Adjust CSV Interface:** When modifying import/export in `csv_handler.py`, ensure new fields are mapped. The import accepts `,` and `;` as delimiter and `utf-8-sig` or `cp1252` as encoding. A file with an invalid row is rejected as a whole, and exact duplicates are skipped (`DatabaseManager.event_key`).
- **Run the tests:** `python -m unittest discover -s tests` (standard library, in-memory SQLite). `app.py` connects to PostgreSQL on import and cannot be imported in tests, so testable logic belongs in the other modules.

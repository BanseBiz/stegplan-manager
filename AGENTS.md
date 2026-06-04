# ORVO Stegplan - AI Agents Context

This document serves as a central knowledge base for AI-powered coding assistants to understand the context, structure, and architecture of the `stegplan` project.

## Project Overview
The project is a web-based application for managing schedule plans (Stegplan) and timetables for a rowing club (ORVO). 
Users can create, edit, and delete events. The application automatically generates visually appealing vector graphics (SVGs) from this data and also offers them as PDF downloads.

## Tech Stack
- **Backend:** Python 3, Flask
- **Production Server:** Waitress (WSGI)
- **Database:** PostgreSQL (managed via Flask-SQLAlchemy, Repository Pattern)
- **Authentication:** Flask-Login, Werkzeug (Password Hashing)
- **Frontend:** HTML5, Jinja2 Templates, Tailwind CSS (via CDN)
- **Generation & Export:** 
  - SVG: Custom-built via string concatenation in Python.
  - PDF: `cairosvg` for converting SVG to PDF.
  - Hyphenation: `pyphen` (German) for intelligent text wrapping in the SVGs.
- **Localization:** Custom JSON-based i18n module.

## Project Structure

- `/app.py`: The entry point. Initializes config, database, components, and starts the Waitress server and the midnight SVG-generation background thread.
- `/database.py`: Contains SQLAlchemy models (`User`, `Event`) and the `DatabaseManager` (Repository Pattern) handling all DB interactions.
- `/frontend.py`: Contains the `Frontend` class with all Flask routes, authentication checks, and web UI logic.
- `/generator.py`: Contains the `DocumentGenerator` for assembling the complex SVG strings and converting them to PDFs.
- `/csv_handler.py`: Handles CSV parsing (import) and creation (export).
- `/localization.py` & `/localization.json`: Custom i18n system. Injects a `t(key)` function into Jinja templates.
- `/config.json`: External configuration file. Contains database credentials, output paths (`svg_output_path`, `timetable_output_path`), host/port, season start dates, and the initial admin account.
- `/stegplan.service`: systemd unit file for deploying the application as a background service on a Linux server.
- `/templates/`: Jinja2 views.
  - `layout.html`: Base template including navigation and Tailwind CDN.
  - `index.html`: Dashboard with the event overview and SVG previews.
  - `edit_event.html`: Form for new/existing events.
  - `users.html`: User management (admins only).
  - `login.html` & `change_password.html`: Authentication views.

## Architecture & Special Features

1. **Database & Initialization:**
   - Handled by `DatabaseManager`. Automatic creation of tables and default admin user on startup.
   - Events have seasonal limits (`season`, `start_date`, `end_date`) to filter visibility based on the generated date.

2. **SVG Generation (IMPORTANT):**
   - SVG is assembled directly via Python lists (`svg.append(...)`) and f-strings in `generator.py`.
   - Two plans are generated: Stegplan (2-column tile layout) and Stundenplan (classic A4 timetable grid).
   - Generated automatically on event modification and nightly at 00:01 via a daemon thread in `app.py`.

3. **Time and Text Processing:**
   - Start and end times of events are stored as strings in the `HH:MM` 24-hour format.
   - The project uses `pyphen` for correct German hyphenation within the SVG tiles (function `wrap_text_with_hyphens`).

4. **Localization & Permissions:**
   - All UI text is loaded from `localization.json` via the `t()` function.
   - Basically, the entire app (except `/login`) is hidden behind `@login_required`.
   - There is a designated "Admin User" defined in `config.json` who has exclusive access to `/users`.

## Coding Conventions for AI Agents

- **Language:** Code, variables, class names, database columns, and comments MUST be in **English**. User interface strings MUST be extracted into `localization.json` and referenced via keys.
- **Styling (CSS):** Use Tailwind classes exclusively in HTML. Do not write custom CSS unless absolutely necessary within the SVG (`<style>` tag).
- **No unnecessary dependencies:** Before suggesting new pip packages, check if it can be done with the Python standard library (as already done with `csv` or `datetime`).
- **Error Handling:** When making changes to the code that modifies the SVG or the database, wrap it in a robust `try-except` block, as is customary in the codebase.
- **Logging:** Use Python's `logging` module (`logger.info`, `logger.error`) instead of `print()`.

## Typical Development Workflows

- **Add a new field:** 1. Update DB model `Event` in `database.py` and extend `to_dict()`. 2. Add field to `add_event` / `edit_event` routes in `frontend.py`. 3. Update frontend templates (`edit_event.html`, `index.html`). 4. Adjust SVG generation in `generator.py`. 5. Add translations to `localization.json`.
- **Adjust CSV Interface:** When modifying import/export in `csv_handler.py`, ensure new fields are mapped. Note the delimiters and encoding (`utf-8-sig`).

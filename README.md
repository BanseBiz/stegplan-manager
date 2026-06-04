# ORVO Stegplan

A web-based application to manage schedule plans (Stegplan) and timetables for a rowing club. It features a responsive UI, database storage, and a powerful engine to generate SVGs and PDFs dynamically.

## Features

- **Event Management:** Create, edit, and delete recurring or seasonal events.
- **Seasonal Filtering:** Define "Summer" and "Winter" phases. Events only show up in the SVG/PDF when they are active.
- **Vector Graphics (SVG):** Generates beautiful, responsive SVG plans out of the box using custom Python-rendering (no external tools required).
- **PDF Export:** Converts timetables and schedule plans directly to PDF for printing or distribution. Supports exporting plans for future dates.
- **Localization:** Fully localized interface (German default) with a clean `localization.json` configuration.
- **CSV Im-/Export:** Easily back up data or import existing schedules from Excel.
- **User Management:** Secure admin and user roles using Flask-Login and password hashing.

## Tech Stack

- **Backend:** Python 3, Flask, Waitress (WSGI Production Server)
- **Database:** PostgreSQL via SQLAlchemy
- **PDF Engine:** CairoSVG
- **Text Processing:** Pyphen (for correct German hyphenation in SVGs)
- **Frontend:** HTML5, Jinja2, Tailwind CSS (via CDN)

## Installation & Setup

### 1. Prerequisites

Make sure you have Python 3 and a running PostgreSQL instance.

**Important for PDF Rendering (Arch Linux/Linux):**
CairoSVG needs system fonts to render SVGs accurately into PDFs. Install standard TTF fonts on your server:
```bash
# Example for Arch Linux:
sudo pacman -Syu ttf-liberation ttf-dejavu noto-fonts
fc-cache -fv
```

### 2. Clone and Install

```bash
git clone git@github.com:BanseBiz/stegplan-manager.git stegplan
cd stegplan

# Create virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install Flask Flask-SQLAlchemy Flask-Login Werkzeug cairosvg pyphen waitress psycopg2-binary
```

### 3. Configuration

Create a `config.json` in the root directory based on this template:

```json
{
  "db_host": "localhost",
  "db_port": 5432,
  "db_name": "orvo_db",
  "db_user": "orvo_admin",
  "db_pass": "your-db-password",
  "svg_output_path": "/path/to/output/stegplan.svg",
  "timetable_output_path": "/path/to/output/stundenplan.svg",
  "admin_user": "admin",
  "admin_pass": "change-in-production",
  "app_port": 5000,
  "app_host": "127.0.0.1",
  "secret_key": "change-in-production",
  "sommerphase_start": "31.03",
  "winterphase_start": "27.10",
}
```

### 4. Run the Application

```bash
python app.py
```
The app will automatically initialize the database, create the admin user, and start the Waitress production server.

## License

This project is licensed under the MIT License - see the LICENSE.md file for details.

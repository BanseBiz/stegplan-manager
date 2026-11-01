# ORVO Stegplan

A web-based application to manage schedule plans (Stegplan) and timetables for a rowing club. It features a responsive UI, database storage, and a powerful engine to generate SVGs and PDFs dynamically.

## Features

- **Event Management:** Create, edit, and delete recurring or seasonal events.
- **Seasonal Filtering:** Define "Summer" and "Winter" phases. Events only show up in the SVG/PDF when they are active.
- **Vector Graphics (SVG):** Generates beautiful, responsive SVG plans out of the box using custom Python-rendering (no external tools required).
- **PDF Export:** Converts timetables and schedule plans directly to PDF for printing or distribution. Supports exporting plans for future dates.
- **Localization:** Fully localized interface (German default) with a clean `localization.json` configuration.
- **Room Plans:** Add any number of rooms. Each room has its own events, CSV im-/export, PDF and public timetable.
- **Overview:** A public list of all active events, sorted by stegplan and rooms, with notes maintained by the admin.
- **CSV Im-/Export:** Easily back up data or import existing schedules from Excel.
- **User Management:** Secure admin and user roles using Flask-Login and password hashing.

## Tech Stack

- **Backend:** Python 3, Flask, Waitress (WSGI Production Server)
- **Database:** PostgreSQL via SQLAlchemy
- **PDF Engine:** CairoSVG
- **Text Processing:** Pyphen (for correct German hyphenation in SVGs)
- **Frontend:** HTML5, Jinja2, Tailwind CSS (compiled, served from `static/`)

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
pip install -r requirements.txt
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
  "winterphase_start": "27.10"
}
```

Room plans are written to `room_output_dir`, which defaults to the directory of `svg_output_path`. The overview is written to `overview_output_path`, which defaults to `nutzungszeiten.svg` in the same directory.

The app marks its session cookie as `Secure` and sends HSTS by default. To run it over plain HTTP on your machine, add `"https_only": false`, otherwise login fails.

### 4. Run the Application

```bash
python app.py
```
The app will automatically initialize the database, create the admin user, and start the Waitress production server.

## Plans and Public Addresses

| Plan | Public SVG | Dashboard |
|---|---|---|
| Stegplan | `/stegplan.svg` | `/` |
| Stundenplan | `/stundenplan.svg` | `/` |
| Room | `/raumplan/<slug>.svg` | `/raum/<slug>` |
| Overview | `/nutzungszeiten.svg` | `/uebersicht` |

The admin manages rooms under `/rooms`. A room keeps its address when it is renamed, so embedded plans keep working. Everybody logged in can maintain the events of a room.

The overview lists the events that are active today and is regenerated with every change, on startup and at night. The app overwrites the file at `overview_output_path` when it starts, so import all plans before you point it at a file that is in use.

## Deployment

The app listens on localhost and expects a reverse proxy that terminates HTTPS.

The app extends existing tables on startup when a new version needs it. Back up the database first (`pg_dump`). The database user must own the tables.

### systemd

`stegplan.service` runs the app from `/opt/stegplan` as user `stegplan`, using a virtual environment:

```bash
cd /opt/stegplan
python3 -m venv venv
venv/bin/pip install -r requirements.txt
sudo cp stegplan.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stegplan
```

### Login Rate Limit (nginx)

The app itself does not limit login attempts. This snippet limits failed and successful `POST /login` requests per client IP; loading the login page stays unlimited.

```nginx
# http block
map $request_method $stegplan_login_key {
    POST    $binary_remote_addr;
    default "";
}
limit_req_zone $stegplan_login_key zone=stegplan_login:10m rate=5r/m;

# server block, next to the existing "location /"
location = /login {
    limit_req zone=stegplan_login burst=5 nodelay;
    limit_req_status 429;
    proxy_pass http://127.0.0.1:5000;  # same target and proxy_set_header lines as "location /"
}
```

## Styles

`static/style.css` is generated and checked in, the server needs no Node.js or build step. After changing Tailwind classes in `templates/` or `static/app.js`, rebuild it with the [standalone CLI v3.4.17](https://github.com/tailwindlabs/tailwindcss/releases/tag/v3.4.17). Stay on v3, the templates use classes that v4 removed.

```bash
./tailwindcss -c tailwind.config.js -o static/style.css --minify
```

## Tests

The tests use the standard library and an in-memory database, no PostgreSQL required:

```bash
python -m unittest discover -s tests
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

# CantorHub

Django 6 member portal for **Just Gospel Frankfurt**, a gospel choir.

## Setup

### Development (SQLite)

Resets the database, imports avatars, and starts the dev server:

```bash
./migrate.sh
```

Or run only the dev server after migrate has been run:

```bash
export DEBUG=1
python manage.py runserver 0.0.0.0:8000
```

### Production (MySQL)

Provide the database credentials as environment variables. The app uses MySQL when `DB_HOST` is set and falls back to SQLite otherwise.

```bash
# Required
export DB_HOST=your-mysql-host
export DB_NAME=cantorhub
export DB_USER=cantorhub
export DB_PASSWORD=secret

# Optional (default: 3306)
export DB_PORT=3306
```

Run the production start script inside Docker:

```bash
./start.sh  # Resets DB, collects static, starts nginx + gunicorn
```

Or build and run the container manually:

```bash
docker build -t cantoreub .
docker run -e DB_HOST=db -e DB_NAME=cantorhub -e DB_USER=cantorhub -e DB_PASSWORD=secret -p 8000:8000 cantoreub
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DEBUG` | `0` | Set to `1` for development mode |
| `SECRET_KEY` | hardcoded dev value | Django secret key (override in production) |
| `DB_HOST` | — | MySQL host (unset → SQLite) |
| `DB_NAME` | `cantorhub` | MySQL database name |
| `DB_USER` | `cantorhub` | MySQL user |
| `DB_PASSWORD` | — | MySQL password |
| `DB_PORT` | `3306` | MySQL port |
| `EMAIL_HOST` | — | SMTP host (empty → console backend) |
| `EMAIL_PORT` | `0` | SMTP port |
| `EMAIL_HOST_USER` | — | SMTP user |
| `EMAIL_HOST_PASSWORD` | — | SMTP password |
| `EMAIL_USE_TLS` | `0` | Set to `1` to enable TLS |
| `EMAIL_USE_SSL` | `0` | Set to `1` to enable SSL |
| `DEFAULT_FROM_EMAIL` | `webmaster@example.org` | Default sender address |
| `EJABBERD_API_URL` | `http://127.0.0.1:5280` | ejabberd REST API URL |
| `EJABBERD_HOST` | `example.net` | ejabberd virtual host |
| `EJABBERD_MUC_SERVICE` | `conference.example.net` | ejabberd MUC service |
| `EJABBERD_BOT_JID` | `forum@example.org` | XMPP bot JID |
| `EJABBERD_BOT_PASSWORD` | — | XMPP bot password |
| `EJABBERD_BOT_PORT` | `5222` | XMPP bot port |
| `ICAL_SECRET` | `cantorhub-ical-change-me-f7a3c2` | Shared secret for iCal subscription URLs |

## Runtime Configuration (database)

Most operational settings are **not** environment variables — they live in the
`intern.Konfiguration` key/value table and can be edited at runtime (Django admin
or `/intern/konfiguration/`) without a redeploy. Defaults are seeded on first
migrate from `intern/apps.py` (`_CONFIG_DEFAULTS`). Read them in code via
`intern.app_settings.get_config()` / `get_config_bool()` / `get_config_int()`.

| Key | Default | Description |
|---|---|---|
| `EJABBERD_API_URL` | `http://127.0.0.1:5280` | ejabberd REST API URL |
| `EJABBERD_HOST` | — | ejabberd XMPP domain |
| `EJABBERD_MUC_SERVICE` | — | ejabberd MUC service domain |
| `EJABBERD_BOT_JID` | — | Forum bot JID |
| `EJABBERD_BOT_PASSWORD` | — | Forum bot password |
| `EJABBERD_BOT_PORT` | `5222` | Forum bot XMPP port |
| `ICAL_SECRET` | random on seed | Secret token for the iCal feed URL |
| `EMAIL_HOST` | — | SMTP server (empty → mail is logged, not sent) |
| `EMAIL_PORT` | `25` | SMTP port |
| `EMAIL_HOST_USER` | — | SMTP username |
| `EMAIL_HOST_PASSWORD` | — | SMTP password |
| `EMAIL_USE_TLS` | `0` | Use STARTTLS |
| `EMAIL_USE_SSL` | `0` | Use SSL |
| `DEFAULT_FROM_EMAIL` | `webmaster@example.org` | Sender address for outgoing mail |
| `UPLOAD_MAX_MB` | `50` | Maximum upload size (MB) |
| `MAP_CENTER_ID` | `1` | `Ort` id used as the overview map center |
| `MAP_DEFAULT_ZOOM` | `12` | Default zoom level of the overview map |
| `PWRESET_MAX_PER_HOUR` | `5` | Max password-reset requests per IP per hour |
| `NOTIFY_POLL_MS` | `10000` | Notification poll interval (ms) |
| `NOTIFY_DISMISS_MS` | `6000` | Notification display duration (ms) |

## Architecture

```
Browser → nginx (port 8000) → gunicorn (port 8001) → Django
```

Nginx serves `/static/` and `/media/` directly; everything else is proxied to gunicorn. In development, `manage.py runserver` handles everything.

All application logic lives in the `intern/` app; `config/` holds only settings and URL routing.

## Key Components

### Core Models
- **User**: Extended Django User model with additional fields for member information
- **Artikel**: Versioned articles/news items
- **Forum**: Discussion forums
- **Mitteilung**: Messages within forums
- **Ort**: Locations
- **Termin**: Events/performances
- **Lied**: Songs with various metadata
- **Konzert**: Concert programs linking songs to events
- **Zusage**: Attendance responses to events
- **Abstimmung**: Voting/decision tracking
- **TabellenPreferenzen**: Table column preferences for users

### Key Features
- Member management with voice types (soprano, alto, tenor, bass, combo, conductor)
- Event management with attendance tracking
- Song database with file attachments
- Forum system for communication (optionally bridged to XMPP MUC rooms)
- File management through django-filer
- Custom password hashing for legacy PHP compatibility
- Versioned articles with edit history, unified/side-by-side diffs, and version-to-version navigation
- Interactive map of members and locations (Leaflet + OpenStreetMap tiles)
- Light/dark theme toggle

## Management Commands

| Command | Description |
|---|---|
| `ejabberd_sync --sync` | Sync XMPP users/rooms when EJABBERD_HOST+EJABBERD_BOT_JID are set |
| `ejabberd_bot` | Run XMPP bot for MUC message forwarding |
| `ejabberd_admin <action>` | Admin ops: delete_forum, delete_user, clear_invites, invite, remove_user, list_rooms, list_users, sync_vcard, sync_password |
| `import_files --path Avatare` | Import avatars from directory into django-filer |
| `index_files` | Re-index django-filer files |

## Migration Quirks

`migrate.sh` / `start.sh` delete `intern/migrations/0002_add_filer.py` and temporarily move `0003_import.py` out before regenerating migrations. This is intentional — `0002` is always regenerated fresh and `0003` depends on it being newly created. Do not check `0002_add_filer.py` into git.

## License

Proprietary — for internal use by Just Gospel Frankfurt.

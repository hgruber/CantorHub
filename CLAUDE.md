# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Development setup (resets database, imports avatars, starts server):**
```bash
./migrate.sh
```

**Run dev server only (after migrate.sh has been run):**
```bash
export DEBUG=1
python manage.py runserver 0.0.0.0:8000
```

**Create and apply migrations:**
```bash
python manage.py makemigrations intern --name <migration_name>
python manage.py migrate
```

**Production start (inside Docker):**
```bash
./start.sh  # Resets DB, collects static, starts nginx + gunicorn
```

**Build and run Docker container:**
```bash
docker build -t cantoreub .
docker run -p 8000:8000 cantoreub
```

**Management commands:**
| Command | Description |
|---|---|
| `ejabberd_sync --sync` | Sync XMPP users/rooms when EJABBERD_ENABLED=1 |
| `ejabberd_bot` | Run XMPP bot for MUC message forwarding |
| `matrix_sync --sync` | Sync Matrix rooms when MATRIX_ENABLED=1 |
| `matrix_sync --backfill` | Backfill forum messages to Matrix |
| `matrix_sync --create-user PK` | Create Matrix user for a member |
| `matrix_sync --set-bot-avatar FILE` | Set bot avatar |

## Architecture

CantorHub is a Django 6 member portal for "Just Gospel Frankfurt", a gospel choir. All application logic lives in the single `intern/` app; `config/` holds only settings and URL routing.

### Request flow

```
Browser → nginx (port 8000) → gunicorn (port 8001) → Django
```

Nginx serves `/static/` and `/media/` directly; everything else is proxied to gunicorn. In development, `manage.py runserver` handles everything.

### URL structure

- `/` — public homepage (`templates/index.html`)
- `/admin/` — Django admin
- `/intern/*` — all authenticated views (`intern/urls.py`)
- `/_matrix/app/v1/*` — Matrix AppService hooks (no auth required)

### Key models (`intern/models.py`)

| Model | Purpose |
|---|---|
| `User` | Extended `AbstractUser` — adds voice type, address, XMPP/Matrix JID, coordinates |
| `Artikel` | Versioned articles/news items |
| `Forum` | Discussion threads; adds `matrix_room_id` for Matrix bridge |
| `Mitteilung` | Forum messages; adds `matrix_event_id`/`xmpp_stanza_id` for bridge deduplication |
| `Termin` / `Ort` | Events and locations |
| `Lied` | Songs in the repertoire |
| `Konzert` | Ordered song list for a specific event (links `Lied` ↔ `Termin`) |
| `Zusage` | Per-member attendance response to an event |
| `Abstimmung` | Voting records |
| `TabellenPreferenzen` | Per-user table column visibility preferences |

### File management

Uses `django-filer`. Folder IDs are hard-coded constants in `settings.py` (e.g. `FOLDER_AVATARE = 1`, `FOLDER_MUSIK = 5`). The `import_files` management command imports avatars from the `Avatare/` directory into filer on first setup.

### External integrations

**XMPP/ejabberd** (`EJABBERD_ENABLED=1`): Bidirectional bridge between Forum MUC rooms and ejabberd. Messages sync in both directions. Uses REST API for admin operations and a long-running slixmpp bot for message relay.

**Matrix/Synapse** (`MATRIX_ENABLED=1`): Bidirectional bridge between Forum threads and Matrix rooms via AppService. Files upload as native Matrix media. Supports user provisioning, Space organization, and message backfill. Requires `MATRIX_ADMIN_TOKEN` for user creation.

See `xmpp.md` and `matrix.md` for detailed implementation notes.

### Notable utilities (`intern/`)

- `replacements.py` — wiki-like markup processor (lists, code blocks, `[[Datei:...]]` file links)
- `php_pbkdf2_hasher.py` — legacy password hasher for migrating users from a prior PHP system; listed in `PASSWORD_HASHERS` in settings
- `fuzzy.py` — fuzzy song title matching used in article references
- `context_processors.py` — injects global template context

**External integrations:**
- `ejabberd.py` — REST API client for ejabberd admin API and message sending
- `matrix.py` — Matrix AppService client for room/user management and messaging

**Management commands:**
- `ejabberd_bot` — slixmpp XMPP bot for MUC message forwarding
- `ejabberd_sync` — sync XMPP users/rooms at startup
- `matrix_sync` — Matrix room sync, backfill, user creation, and maintenance

### Migration quirks

`migrate.sh` / `start.sh` delete `intern/migrations/0002_add_filer.py` and temporarily move `0003_import.py` out before regenerating migrations. This is intentional — `0002` is always regenerated fresh and `0003` depends on it being newly created. Do not check `0002_add_filer.py` into git.

### Database

SQLite in development (`db.sqlite3`, excluded from git). MySQL-compatible for production via `pymysql`.

### Environment variables

- `DEBUG` — set to `1` for development mode
- `SECRET_KEY` — hardcoded in `settings.py` (development only; override for production)

**XMPP Integration:**
- `EJABBERD_ENABLED`, `EJABBERD_API_URL`, `EJABBERD_HOST`, `EJABBERD_MUC_SERVICE`
- `EJABBERD_BOT_JID`, `EJABBERD_BOT_PASSWORD`, `EJABBERD_BOT_PORT`

**Matrix Integration:**
- `MATRIX_ENABLED`, `MATRIX_HOMESERVER`, `MATRIX_AS_TOKEN`, `MATRIX_HS_TOKEN`
- `MATRIX_BOT_USER`, `MATRIX_PUBLIC_URL`, `MATRIX_SPACE_NAME`, `MATRIX_ADMIN_TOKEN`

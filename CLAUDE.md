# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Language:** This file must be written strictly in English. Do not add German prose; code identifiers and string literals (e.g. filenames, variable names) may remain in their original form.

## Commands

**Fresh install — resets DB, imports avatars, starts server (DEV + Container):**
```bash
./migrate.sh              # DEBUG not set → nginx + gunicorn (prod/container)
DEBUG=1 ./migrate.sh      # DEV: runserver
```

**Start with existing DB (no wipe):**
```bash
./start.sh                # DEBUG not set → nginx + gunicorn (prod/container)
DEBUG=1 ./start.sh        # DEV: runserver
```

**Run dev server only (after migrate.sh has been run):**
```bash
python manage.py runserver 0.0.0.0:8000
```

**Create and apply migrations:**
```bash
python manage.py makemigrations intern --name <migration_name>
python manage.py migrate
```

**Build and run Docker container:**
```bash
docker build -t cantoreub .
docker run -p 8000:8000 cantoreub
```

**Management commands:**
| Command | Description |
|---|---|
| `ejabberd_admin sync` | Full startup sync (ensure bot, assign MUC JIDs, configure rooms); no-op if ejabberd is not configured (`is_ejabberd_configured()`) |
| `ejabberd_bot` | Run XMPP bot for MUC message forwarding; no-op if ejabberd is not configured |
| `ejabberd_admin <group> <verb>` | Admin ops grouped by noun: `bot ensure`; `room {list,assign-jids,configure,delete,avatar,members,occupants,options}`; `user {list,delete,vcard,password}`; `invite {add,remove,clear}`; `server users` |
| `send_reconfirmation --user USERNAME` | Send data-reconfirmation mail to one active member |
| `send_reconfirmation --all` | Send data-reconfirmation mail to all active members with an email address |
| `send_reconfirmation --user USERNAME --print-url` | Print the confirmation URL for one member without sending mail (for testing) |
| `send_reconfirmation --all --print-url` | Print confirmation URLs for all members (tab-separated `username<TAB>url`) without sending mail |
| `make_invite_url EMAIL` | Print a signed 7-day invite link for the Neuantrag form (`/intern/beitritt/<token>/`) without sending mail |
| `cleanup_changelog [--days N] [--dry-run]` | Delete `ChangeLog` entries older than the retention period (default 3 years = 1095 days), enforcing the privacy-policy §9 claim. Runs in the background on every `start.sh` |

## Architecture

CantorHub is a Django 6 member portal for "Just Gospel Frankfurt", a gospel choir. All application logic lives in the `intern/` app; `config/` holds only settings and URL routing. Views are split into domain modules under `intern/views/` (`auth.py`, `files.py`, `folders.py`, `forums.py`, `titel.py`, `termine.py`, `mitglieder.py`, `artikel.py`, `karte.py`, `orte.py`, `gallerie.py`). The package's `__init__.py` re-exports all public views, so `urls.py` uses `views.forum_list` etc. unchanged.

### Request flow

```
Browser → nginx (port 8000) → gunicorn (port 8001) → Django
```

Nginx serves `/static/`, `/media/`, and `/tiles/` directly; everything else is proxied to gunicorn. In development, `manage.py runserver` handles everything.

### URL structure

- `/` — public homepage (`templates/index.html`)
- `/datenschutz/` — public privacy policy (`templates/datenschutz.html`, no login required, `TemplateView` in `config/urls.py`)
- `/tiles/<z>/<x>/<y>.png` — OSM tile proxy (no login required). In production nginx intercepts this and serves from its disk cache (`/app/tiles/`, 7-day TTL) without hitting Django. In dev, `tiles_proxy` in `karte.py` fetches from OSM server-side so the user's IP is never sent to OSM.
- `/admin/` — Django admin
- `/intern/*` — all authenticated views (`intern/urls.py`)
- `/intern/karte/geocode/` — Nominatim geocoding proxy (`geocode_proxy` in `karte.py`, login required); passes query params server-side so the user's IP is never sent to Nominatim.

### Detail pages

All list views use django-tables2 with clickable rows (`data-href` on `<tr>`). Each table row navigates to a detail page. Detail pages have an edit button in the top bar (via `edit`/`id` context variables rendered in `base.html`).

| URL pattern | View | Template |
|---|---|---|
| `/intern/forum/<id>/` | `forum_view` | `forum.html` |
| `/intern/forum/<id>/edit/` | `forum_edit` | `forum_edit.html` |
| `/intern/termin/<id>/` | `termin_view` | `termin.html` |
| `/intern/termin/<id>/edit/` | `termin_edit` | `termin_edit.html` |
| `/intern/titel/<id>/` | `titel_view` | `titel.html` |
| `/intern/titel/<id>/edit/` | `titel_edit` | `titel_edit.html` |
| `/intern/mitglied/<id>/` | `member_view` | `mitglied.html` |
| `/intern/mitglied/<id>/edit/` | `member_edit` | `member_edit.html` |
| `/intern/gallerie/<ordner_id>/` | `gallerie_view` | `gallerie.html` |

Detail pages use the `.detail-page` / `.detail-card` CSS layout (2-column card grid, single column on mobile). Edit pages use the `.wiki` container with `.form-grid`.

### Attendance (Zusage) options

`Zusage.option` values: `"1"` = Zusage, `"2"` = Absage, `"3"` = Eventuell, empty/missing = Keine Angabe. The attendance table on the termin detail page groups users by `Stimme` (S, A, T, B, C, M) and splits into two tables on mobile.

The forum edit page (`/intern/forum/<id>/edit/`) and its XMPP behaviour — room-info card, invite flow, avatar sync (`_sync_forum_avatar`), MUC room invariants (`configure_room`), the Forum→MUC relay and the `_relay_cursor` restart gap — are documented in `xmpp.md`.

### Article editor & versioning

`Artikel` rows are immutable versions keyed by `(name, version)` — articles are addressed by `name`, not `id`. Saving an edit at `/intern/artikel/<name>/edit/` creates a new `Artikel` row with `version + 1` rather than mutating the existing one. The editor (`artikel.html`, edit branch) renders the `.article-editor` shell: an identity bar, a collapsible `.ae-help` syntax cheat-sheet, the textarea inside a `.wiki` container (kept so `abstimmung.js`'s `{abstimmung:...}` helper still binds), and a footer action bar.

`article_view` shows the latest version by default, or a specific one via `?version=<n>`. When viewing an outdated version it renders the `.version-banner` — a warning plus a version stepper with previous/next links (`prev_version` / `next_version`, computed via DB queries so gaps in the version sequence are skipped) and an "Aktuelle Version" button. History and unified/side-by-side diffs live at `/intern/artikel/<name>/history/` and `/diff/`.

### Member application flow (Mitglieds-Beitritt)

Two ways to add a member, both behind the `+` in `/intern/mitglied/` (perm `intern.add_user`).
The off-canvas panel (`templates/mitglied_add_panel.html`, included via the
`add_panel_include` context var in `table.html`) is two-step:

1. **Invite** (default step): an admin enters only an e-mail and submits to
   `mitglied_invite` (`views/mitglieder.py`). This sends a branded e-mail with a
   non-guessable link to the public join form. No user is created yet. The link
   carries the e-mail in a `TimestampSigner` token (salt `intern.mitglied_invite`,
   **7-day** validity) — `make_invite_token()` / `_read_invite_token()` in
   `views/auth.py`. Stateless: no DB model, no placeholder user.
2. **Manuell anlegen** (JS-revealed): the existing `MitgliedAddForm` posting to
   `mitglied_add`, which creates an **active** member immediately (unchanged).

The public join form lives at `/intern/beitritt/<token>/` (`mitglied_beitritt` in
`views/auth.py`, **no** `login_required`). `MitgliedBeitrittForm` (`forms.py`) validates
all member fields — required: first/last name, all address fields, `geburtstag`,
`username` (regex `^[A-Za-z0-9._-]{3,30}$` + case-insensitive uniqueness via
`username__iexact`), two matching passwords (`validate_password`),
and three mandatory consent checkboxes (Datenschutz — links to `/datenschutz/`, Datenverarbeitung, Satzung —
links to the PDF configured via `SATZUNG_FILE_ID`). On success the member is created with `is_active=False`, a PDF of the completed
application is saved to the filer folder **„Verwaltung/Mitglieder"** (Vorstand-only,
via `_save_antrag_pdf` in `views/auth.py` using reportlab; best-effort, never blocks
registration), a confirmation mail goes to the applicant, and a notification mail
goes to all active members with `intern.change_user` (`_member_managers()`). The public
pages (`mitglied_beitritt.html`, `_success.html`, `_invalid.html`) extend the standalone
`mitglied_public_base.html` shell (no sidebar), not `base.html`.

The application is logged in the ChangeLog as a distinct action
`ChangeLog.ACTION_APPLICATION` (`"apply"` → "Neuer Mitgliedsantrag"): the view sets
`user._audit_application = True` before saving and `signals._write_audit_log` maps that
to the application action (the action code is ≤8 chars to fit `action`'s `max_length`).

All e-mails in this flow (`templates/emails/mitglied_invite.html`,
`mitglied_beitritt_success.html`, `mitglied_antrag_admin.html`) and the password-reset
mail go through `intern.mail.send_branded_mail()` (branded card with `cid:logo`).

**Applicants are created with `date_joined=None`** (the field is overridden on `User` to be
nullable). This is the discriminator for the activation mail: when an admin later sets
`is_active=True`, `signals._send_activation_mail()` checks `user.date_joined is None` →
first-time activation → sends `emails/mitglied_willkommen.html` and stamps `date_joined`
via `User.objects.filter(pk=...).update(date_joined=timezone.now())` (avoids recursive
signal). If `date_joined` is already set → reactivation → sends `emails/mitglied_reaktiviert.html`.
Both mail texts are configurable via `MAIL_WILLKOMMEN` / `MAIL_REAKTIVIERT` in
`Konfiguration` (all standard placeholders available; see `mail.format_config_mail()`). No mail is sent if the user
has no email address.

### Member re-confirmation flow (Datenbestätigung)

Allows the board to request that existing members re-confirm their stored data and
re-acknowledge the privacy policy, bylaws, and membership fee schedule.

**Trigger:** `manage.py send_reconfirmation --user <username>|--all` (uses `VEREINS_URL` from config; override with `--base-url URL`)
(e.g. `--base-url https://portal.example.com`). The command calls
`send_bestaetigung_mail(user, base_url)` in `views/auth.py`, which:
1. Creates a `TimestampSigner` token (salt `"intern.mitglied_bestaetigung"`, **30-day** validity) encoding the user PK.
2. Reads the email body text from the `Konfiguration` key **`MAIL_BESTAETIGUNG`** —
   editable via `/intern/konfiguration/` without code changes.
   All standard placeholders available plus `{link}`; falls back to `None` (generic HTML only) if
   the key is empty.
3. Sends the branded mail (`emails/mitglied_bestaetigung_aufforderung.html`) with the text as
   `text_body`.

**Public form:** `/intern/bestaetigung/<token>/` (`mitglied_bestaetigung` in `views/auth.py`,
no `login_required`). Shows the member's current data (read-only) plus three mandatory
checkboxes (`MitgliedBestaetigungForm` in `forms.py`): data correct, Datenschutz, Satzung.

**On submit:** `_save_bestaetigung_pdf(user)` generates a PDF (reportlab) with all stored
data + confirmed checkboxes, saves it to **„Verwaltung/Mitglieder"** in filer, and attaches it
to the quittance mail (`emails/mitglied_bestaetigung_bestaetigt.html`) sent to the member. The
quittance mail body is configurable via `MAIL_BESTAETIGUNG_BESTAETIGT` in `Konfiguration`.
No Vorstand notification. Three public templates extend `mitglied_public_base.html`:
`mitglied_bestaetigung.html`, `_success.html`, `_invalid.html`.

`MAIL_BESTAETIGUNG` and `MAIL_ANTRAG` are seeded by `_CONFIG_DEFAULTS` in `intern/apps.py` on `post_migrate`, like all other `MAIL_*` keys.

### Key models (`intern/models.py`)

| Model | Purpose |
|---|---|
| `User` | Extended `AbstractUser` — adds voice type, address, XMPP JID, coordinates |
| `Artikel` | Versioned articles/news items |
| `Forum` | Discussion threads; `bild` (FilerFileField), `aktiv` (Boolean), `xmpp_muc_jid` for XMPP bridge |
| `Mitteilung` | Forum messages; adds `xmpp_stanza_id` for bridge deduplication. Display helpers `sender_name()` / `sender_avatar_url()` / `is_from_bot()` fall back to "Unbekannt"+`kein_photo.png` for `sender=None` and to nick `CantorBot`+`bot.png` for the bot JID |
| `Termin` / `Ort` | Events and locations |
| `Lied` | Songs in the repertoire |
| `Konzert` | Ordered song list for a specific event (links `Lied` ↔ `Termin`) |
| `Zusage` | Per-member attendance response to an event |
| `Abstimmung` | Voting records |
| `TabellenPreferenzen` | Per-user table column visibility preferences |

### File management

Uses `django-filer`. Folder IDs are hard-coded constants in `settings.py` (e.g. `FOLDER_AVATARE = 1`, `FOLDER_MUSIK = 5`). The `import_files` management command imports avatars from the `Avatare/` directory into filer on first setup. `intern` overrides the filer-built-in `import_files` command (`intern/management/commands/import_files.py`) to set `_migrating.active = True` during the import, suppressing per-file index/thumbnail threads — otherwise importing a large directory would exhaust MySQL's connection limit. Indexing and thumbnailing are handled by the subsequent batch jobs instead.

`index_files` and `thumbnail_files` run as background jobs after a fresh install in `migrate.sh`, building the search index and pre-generating thumbnails for all files. They are intentionally absent from `start.sh` (existing DB) — files are already indexed there. Files uploaded through the app are indexed and thumbnailed immediately via a `post_save` signal on `filer.File` (`on_filer_file_saved` in `signals.py`): a daemon thread calls `index_file()` and pre-generates all three thumbnail sizes so the upload response is not delayed. A semaphore caps concurrent thumbnail threads at 4 to prevent MySQL connection exhaustion; each thread closes its DB connection when done. The signal is suppressed (`_migrating.active`) during management commands that bulk-import files; file-creating functions in `0003_import.py` also set the flag explicitly as a backstop.

### External integrations

**XMPP/ejabberd** (active when `EJABBERD_HOST` + `EJABBERD_BOT_JID` are set): Bidirectional bridge between Forum MUC rooms and ejabberd. Messages sync in both directions. Uses REST API for admin operations and a long-running slixmpp bot for message relay.

See `xmpp.md` for detailed implementation notes.

### Frontend design system (`intern/static/intern/css/intern.css`)

All colors use CSS custom properties defined in `:root` (light mode). Dark mode is a `[data-theme="dark"]` block that overrides all color tokens. Theme is toggled via a button in the sidebar footer; persisted to `localStorage`; falls back to `prefers-color-scheme`. An inline `<script>` in `base.html` head sets `data-theme` before paint to avoid flash.

When adding new colors, always use CSS variables and add dark-mode values to `[data-theme="dark"]`. Avoid hardcoded hex colors in component styles.

Map pages use Leaflet. `intern/static/intern/js/osm-map.js` patches `L.TileLayer.prototype.createTile` to set `referrerPolicy = "origin"` — OpenStreetMap's tile servers reject requests without a `Referer` header. It is loaded once in `base.html` (right after Leaflet) so every map on the site is covered; the per-page map-init scripts must not re-add this patch.

### Known technical debt

Tracked in separate files: general code/UX debt (branding, risk-ranked items) in
`technical-debt.md`; privacy-policy compliance items in `datenschutz.md`.

### Logging

`settings.py` defines a `LOGGING` dict. The `intern` logger hierarchy is set to `INFO`; root and `django` loggers to `WARNING`. All output goes to stdout via `StreamHandler` (`stream: ext://sys.stdout`), which appears in `podman logs` and `journalctl`. Using stdout ensures systemd assigns the correct `PRIORITY` based on the Python log level, so INFO/WARNING entries are not colored red in journalctl. Custom loggers use `logging.getLogger(__name__)` — they all fall under `intern.*` and are therefore visible.

### Notable utilities (`intern/`)

- `mail.py` — `send_branded_mail(subject, to, template, context, text_body=None, attachments=None)`: renders an HTML template into a branded mail with the embedded logo (`cid:logo`) and a plain-text fallback; resolves the sender via `get_from_email()`; never raises. `attachments` is an optional list of `(filename, bytes, content_type)` tuples — when present the outer MIME type is `multipart/mixed`. Used by the password-reset and member-application mails (the beitritt confirmation includes the application PDF as attachment).
- `replacements.py` — wiki-like markup processor (lists, code blocks, `[[Datei:...]]` file links)
- `php_pbkdf2_hasher.py` — legacy password hasher for migrating users from a prior PHP system; listed in `PASSWORD_HASHERS` in settings
- `fuzzy.py` — fuzzy song title matching used in article references
- `context_processors.py` — injects global template context (`VERSION`, `upload_max_mb`, notify poll/dismiss intervals)
- `app_settings.py` — runtime config helpers (`get_config`, `get_config_bool`, `get_config_int`, `get_from_email`, `get_map_center`, `get_document_url`) backed by the `Konfiguration` table; see "Runtime configuration" below. `get_document_url(key)` resolves a Filer file ID stored in `Konfiguration` to a public HMAC token URL (`/intern/datei/<pk>/<token>/<filename>`), returning `"#"` when unconfigured.

**External integrations:**
- `ejabberd.py` — REST API client for ejabberd admin API (room config, affiliations, invitations, vCards). Message sending is done by the bot over its live session, not here.

**Management commands:**
- `ejabberd_bot` — slixmpp XMPP bot for MUC message forwarding
- `ejabberd_admin` — operator CLI for all ejabberd admin ops; `ejabberd_admin sync` runs the startup user/room sync (was the separate `ejabberd_sync` command, now merged)

### Migration quirks

`migrate.sh` / `start.sh` delete `intern/migrations/0002_add_filer.py` and temporarily move `0003_import.py` out before regenerating migrations. This is intentional — `0002` is always regenerated fresh and `0003` depends on it being newly created. Do not check `0002_add_filer.py` into git.

### Database

SQLite in development (`db.sqlite3`, excluded from git). MySQL-compatible for production via `pymysql`.

**Note on DB reset:** The full DB wipe in `migrate.sh` exists only during the current **test phase**. After the final migration it will be removed — the test system will simply receive a copy of the prod DB, and prod and test will have separate start strategies (no more destructive reset on start). Until then: every `migrate.sh` run discards all data.

### Environment variables

Only bootstrap settings (needed before the DB is available) are real env vars:

- `DEBUG` — set to `1` for development mode
- `SECRET_KEY` — hardcoded in `settings.py` (development only; override for production)
- `DB_HOST`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_PORT` — MySQL connection (unset → SQLite)

### Runtime configuration (`Konfiguration` table)

Operational settings are stored in the `intern.Konfiguration` key/value table, not
env vars, so they can be changed at runtime (admin or `/intern/konfiguration/`)
without a redeploy. **Read them via `intern.app_settings` helpers** (`get_config`,
`get_config_bool`, `get_config_int`) — never `os.environ`/`settings` for these —
and never call the helpers at settings/import time (the DB may not be ready).

Environment variables take priority over DB values in `get_config()`, **and are also
persisted to the DB during `post_migrate`** (`_seed_config` in `intern/apps.py` calls
`update_or_create` for every key that has a matching ENV var). This means a container
started with `-e EJABBERD_BOT_JID=...` writes the value into the DB — on subsequent
starts the ENV var can be dropped and the DB value is used. Use
`is_ejabberd_configured()` (not a flag) to check whether the XMPP integration is active.

Defaults are seeded on `post_migrate` from `_CONFIG_DEFAULTS` in `intern/apps.py`;
**add new keys there** (with a German `description`) so fresh installs get them.
The full key catalog and the mail-placeholder reference (`format_config_mail` /
`format_config_text`, the standard `{vorname}`/`{vereinsname}`/… placeholders, and the
"to add a new automated email" recipe) live in `configuration.md`.

`VEREINSNAME` is exposed via `get_vereinsname()` in `app_settings.py`, injected into
every template context by `config/context_processors.py` (`{{ vereinsname }}`), and
into every email render in `mail.py`.

For outgoing mail always pass `get_from_email()` as the sender (resolves
`DEFAULT_FROM_EMAIL` from the DB, falling back to `settings.DEFAULT_FROM_EMAIL`).
Frontend-facing values (`NOTIFY_POLL_MS`, `NOTIFY_DISMISS_MS`) reach JS via
`context_processors.project_meta` → `data-*` attributes on `<body>` → `notify.js`.

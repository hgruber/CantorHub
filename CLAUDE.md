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
| `ejabberd_admin <action>` | Admin ops: delete_forum, delete_user, clear_invites, invite, remove_user, list_rooms, list_users, sync_vcard, sync_password |
| `apply_initial_config [--file PATH]` | Write KEY=VALUE pairs from a shell config file into the `Konfiguration` table. Tries `/app/initial.sh` (Docker) then `<project>/initial.sh` (local) by default; `--file` overrides. `migrate.sh` calls this with `--file migrate.sh` so its exported vars land in the DB. |

## Architecture

CantorHub is a Django 6 member portal for "Just Gospel Frankfurt", a gospel choir. All application logic lives in the `intern/` app; `config/` holds only settings and URL routing. Views are split into domain modules under `intern/views/` (`auth.py`, `files.py`, `folders.py`, `forums.py`, `titel.py`, `termine.py`, `mitglieder.py`, `artikel.py`, `karte.py`, `orte.py`). The package's `__init__.py` re-exports all public views, so `urls.py` uses `views.forum_list` etc. unchanged.

### Request flow

```
Browser → nginx (port 8000) → gunicorn (port 8001) → Django
```

Nginx serves `/static/` and `/media/` directly; everything else is proxied to gunicorn. In development, `manage.py runserver` handles everything.

### URL structure

- `/` — public homepage (`templates/index.html`)
- `/admin/` — Django admin
- `/intern/*` — all authenticated views (`intern/urls.py`)

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

Detail pages use the `.detail-page` / `.detail-card` CSS layout (2-column card grid, single column on mobile). Edit pages use the `.wiki` container with `.form-grid`.

### Attendance (Zusage) options

`Zusage.option` values: `"1"` = Zusage, `"2"` = Absage, `"3"` = Eventuell, empty/missing = Keine Angabe. The attendance table on the termin detail page groups users by `Stimme` (S, A, T, B, C, M) and splits into two tables on mobile.

### Forum edit page

`/intern/forum/<id>/edit/` lets admins set `thema`, `bild`, and (when `EJABBERD_ENABLED`) `xmpp_muc_jid`. When EJABBERD is enabled, the MUC JID is auto-derived as `forum-{id}@{EJABBERD_MUC_SERVICE}` if not set; the first invite also persists it to the DB so the bot picks it up. XMPP sections are hidden entirely when `EJABBERD_ENABLED=False` (no fallback). When enabled, shows: a room-info card (exists, persistent, members\_only, public, moderated, anonymous, allow\_user\_invites, lang, title, owners with bot marker, bot presence via `get_room_options`), invited (affiliations `member`/`admin`/`owner`), attending (occupants), without invitation (active users with xmpp not in affiliations), without XMPP account, and **Gäste/Fremde** (occupants whose bare JID matches no active user and is not the bot JID). The invite button calls `ejabberd.set_room_affiliation(..., "member")` silently.

When `bild` is set or changed, `_sync_forum_avatar(forum_obj)` is called (best-effort) to push the image as MUC room avatar via `ejabberd.set_room_vcard(muc_jid, avatar_file, name)`. This sets the `vcard` room option via `change_room_option` (XEP-0054 vcard-temp XML with `PHOTO/TYPE/BINVAL`). Clients like Conversations fetch the room vCard via IQ and show the avatar. Two quirks found in testing: (1) ejabberd's fxml parser requires **double-quoted** XML namespace attributes — single quotes cause a 500 internal_error; (2) `vcard_xupdate="external"` via `change_room_option` returns 500 — the accepted format is the hex SHA1 hash of the raw image bytes, which ejabberd then includes in the room presence (XEP-0153) so clients like Conversations automatically fetch and display the avatar. Called from `forum_edit` (on every save, idempotent) and `forum_add` (if bild set on creation); no crash if the MUC room doesn't exist yet. The `bild` column also appears in the forum list table (`ForumTabelle`) as a thumbnail in the first column.

`get_room_options` returns a flat `{option_name: value}` dict (all values are strings, e.g. `"true"`); `ejabberd.option_is_true(options, key)` coerces them to bool (handles string/JSON-bool/list-of-objects formats across ejabberd versions). The "Besitzer" of a bot-created room is the bot JID itself (it created the room by joining first); `owner_is_bot` flags this in the UI.

### MUC room configuration

`ejabberd.configure_room(muc_jid, title=None)` is the single source of truth for room invariants and enforces (overwriting manual changes) on every bot (re)join and on `ejabberd_sync --sync`: `persistent=true`, `anonymous=true`, `public=false`, `members_only=true`, `allow_user_invites=true`, `lang=de`, plus `title` when given (the forum `thema`). Defined as `_ROOM_OPTIONS` in `ejabberd.py`. Called from `ejabberd_bot._configure_room` (on join) and `ejabberd_sync._configure_rooms` (all existing rooms at startup).

Forum→MUC delivery: `forum_send` only writes the `Mitteilung`; the persistent `ejabberd_bot` relays it to the MUC room over its live session (`CantorBot._relay_messages`, a 3 s timer reading `_db_pending_forum_messages`). This replaced a per-message short-lived slixmpp connection that was unreliable (flaky first TLS handshake → random timeouts) and collided on the `CantorBot` nick. The relayed message echoes back under nick `CantorBot` and is skipped by echo prevention.

`anonymous=true` (semi-anonymous) is deliberate: OMEMO in a MUC technically requires a non-anonymous room, so a semi-anonymous room makes clients (Conversations, Gajim) default to **unencrypted** — required for the Forum⇄MUC bridge to read messages. The bot still resolves real sender JIDs via the admin REST API (`get_room_occupants`), which exposes them regardless of room anonymity; clients/members no longer see each other's real JIDs.

### Article editor & versioning

`Artikel` rows are immutable versions keyed by `(name, version)` — articles are addressed by `name`, not `id`. Saving an edit at `/intern/artikel/<name>/edit/` creates a new `Artikel` row with `version + 1` rather than mutating the existing one. The editor (`artikel.html`, edit branch) renders the `.article-editor` shell: an identity bar, a collapsible `.ae-help` syntax cheat-sheet, the textarea inside a `.wiki` container (kept so `abstimmung.js`'s `{abstimmung:...}` helper still binds), and a footer action bar.

`article_view` shows the latest version by default, or a specific one via `?version=<n>`. When viewing an outdated version it renders the `.version-banner` — a warning plus a version stepper with previous/next links (`prev_version` / `next_version`, computed via DB queries so gaps in the version sequence are skipped) and an "Aktuelle Version" button. History and unified/side-by-side diffs live at `/intern/artikel/<name>/history/` and `/diff/`.

### Key models (`intern/models.py`)

| Model | Purpose |
|---|---|
| `User` | Extended `AbstractUser` — adds voice type, address, XMPP JID, coordinates |
| `Artikel` | Versioned articles/news items |
| `Forum` | Discussion threads; `bild` (FilerFileField), `aktiv` (Boolean), `xmpp_muc_jid` for XMPP bridge |
| `Mitteilung` | Forum messages; adds `xmpp_stanza_id` for bridge deduplication |
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

See `xmpp.md` for detailed implementation notes.

### Frontend design system (`intern/static/intern/css/intern.css`)

All colors use CSS custom properties defined in `:root` (light mode). Dark mode is a `[data-theme="dark"]` block that overrides all color tokens. Theme is toggled via a button in the sidebar footer; persisted to `localStorage`; falls back to `prefers-color-scheme`. An inline `<script>` in `base.html` head sets `data-theme` before paint to avoid flash.

When adding new colors, always use CSS variables and add dark-mode values to `[data-theme="dark"]`. Avoid hardcoded hex colors in component styles.

Map pages use Leaflet. `intern/static/intern/js/osm-map.js` patches `L.TileLayer.prototype.createTile` to set `referrerPolicy = "origin"` — OpenStreetMap's tile servers reject requests without a `Referer` header. It is loaded once in `base.html` (right after Leaflet) so every map on the site is covered; the per-page map-init scripts must not re-add this patch.

### Known technical debt

Items found during code review, ordered by estimated risk of the fix:

- **Branding is hardcoded** ("Just Gospel Frankfurt", logos, domain) across
  templates, `replacements.py`, `tables.py`, and static SVGs. Blocks open-sourcing
  as a white-label app. Full extraction plan in `branding.md`.

**Medium risk (15-30%)** — need testing after fixing:
- `Zusage.option` is `CharField(max_length=255)` but only uses `"1"`, `"2"`, `"3"`, `""`. Should be a choices field with a migration.
- `Mitteilung.mitteilung` allows `null=True` but `formatiert()` calls `apply_replacements()` which may crash on `None`. Guard the method or remove `null=True`.
- `intern.js` (1022 lines) puts all JS in one file with global namespace pollution (`appMainDz`, `toggle()`, `fileAction()`, `saveOrder()`). Should be split into modules.
- Dropzone, Sortable, Leaflet, and `osm-map.js` are loaded unconditionally in `base.html` on every page. Should be page-specific `<script>` loads.
- `sortablejs@latest` in `base.html` is unpinned — a breaking upstream update could break the app.
- Inline `<script>` blocks in 6 templates (`karte.html`, `termin.html`, `termin_edit.html`, `mitglied.html`, `artikel_history.html`, `ort_detail.html`) should be extracted to separate JS files. The shared OSM tile-referer patch has already been pulled out into `osm-map.js`; the map-init scripts themselves remain inline.
- Inline `style=` attributes in templates bypass the design system and lack dark mode support.

**Higher risk (35-55%)** — need careful planning:
- Many hardcoded hex colors in `intern.css` (attendance badges, diff views, wiki code block, toasts) lack CSS variables and some lack dark-mode overrides. The version banner now uses `--warn-*` tokens with dark-mode values.
- `main.css` (public homepage) defines `.content` with different properties than `intern.css` — potential clash if both load on the same page.
- `alert()`/`confirm()` in `intern.js` for UX feedback should be replaced with toast/modal components, but `confirm()` gates destructive actions so control flow changes.
- `visible_fields()` in `views/files.py` has dual behavior: returns column list on GET, saves and redirects on POST. Splitting it requires touching call sites in `titel.py` and `mitglieder.py`.
- URL parameter naming is inconsistent across views (`id` vs `pk` vs `forum` vs `titel`). Standardizing requires updating URL patterns, view signatures, templates, and `reverse()` calls.

### Logging

`settings.py` defines a `LOGGING` dict. The `intern` logger hierarchy is set to `INFO`; root and `django` loggers to `WARNING`. All output goes to stderr via `StreamHandler`, which appears in `podman logs` and `journalctl`. Custom loggers use `logging.getLogger(__name__)` — they all fall under `intern.*` and are therefore visible.

### Notable utilities (`intern/`)

- `replacements.py` — wiki-like markup processor (lists, code blocks, `[[Datei:...]]` file links)
- `php_pbkdf2_hasher.py` — legacy password hasher for migrating users from a prior PHP system; listed in `PASSWORD_HASHERS` in settings
- `fuzzy.py` — fuzzy song title matching used in article references
- `context_processors.py` — injects global template context (`VERSION`, `upload_max_mb`, notify poll/dismiss intervals)
- `app_settings.py` — runtime config helpers (`get_config`, `get_config_bool`, `get_config_int`, `get_from_email`, `get_map_center`) backed by the `Konfiguration` table; see "Runtime configuration" below

**External integrations:**
- `ejabberd.py` — REST API client for ejabberd admin API (room config, affiliations, invitations, vCards). Message sending is done by the bot over its live session, not here.

**Management commands:**
- `ejabberd_bot` — slixmpp XMPP bot for MUC message forwarding
- `ejabberd_sync` — sync XMPP users/rooms at startup

### Migration quirks

`migrate.sh` / `start.sh` delete `intern/migrations/0002_add_filer.py` and temporarily move `0003_import.py` out before regenerating migrations. This is intentional — `0002` is always regenerated fresh and `0003` depends on it being newly created. Do not check `0002_add_filer.py` into git.

### Database

SQLite in development (`db.sqlite3`, excluded from git). MySQL-compatible for production via `pymysql`.

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

Defaults are seeded on `post_migrate` from `_CONFIG_DEFAULTS` in `intern/apps.py`;
**add new keys there** (with a German `description`) so fresh installs get them.
Current keys: the `EJABBERD_*` set, `ICAL_SECRET`, the `EMAIL_*` set,
`DEFAULT_FROM_EMAIL`, `UPLOAD_MAX_MB`, `MAP_CENTER_ID`, `MAP_DEFAULT_ZOOM`,
`PWRESET_MAX_PER_HOUR`, `NOTIFY_POLL_MS`, `NOTIFY_DISMISS_MS`.

For outgoing mail always pass `get_from_email()` as the sender (resolves
`DEFAULT_FROM_EMAIL` from the DB, falling back to `settings.DEFAULT_FROM_EMAIL`).
Frontend-facing values (`NOTIFY_POLL_MS`, `NOTIFY_DISMISS_MS`) reach JS via
`context_processors.project_meta` → `data-*` attributes on `<body>` → `notify.js`.

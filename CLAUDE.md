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

`/intern/forum/<id>/edit/` shows user lists sourced from XMPP MUC room data (when `EJABBERD_ENABLED` and `xmpp_muc_jid` exists): invited (room members), attending (room occupants), without invitation (active users not in room), without XMPP account (active users without `xmpp` JID). The invite button calls `ejabberd.send_invitation()` + `ejabberd.set_room_affiliation()`. Falls back to message-based lists when XMPP is disabled.

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

### Known technical debt

Items found during code review, ordered by estimated risk of the fix:

**Medium risk (15-30%)** — need testing after fixing:
- `Zusage.option` is `CharField(max_length=255)` but only uses `"1"`, `"2"`, `"3"`, `""`. Should be a choices field with a migration.
- `Mitteilung.mitteilung` allows `null=True` but `formatiert()` calls `apply_replacements()` which may crash on `None`. Guard the method or remove `null=True`.
- `intern.js` (1022 lines) puts all JS in one file with global namespace pollution (`appMainDz`, `toggle()`, `fileAction()`, `saveOrder()`). Should be split into modules.
- Dropzone, Sortable, and Leaflet are loaded unconditionally in `base.html` on every page. Should be page-specific `<script>` loads.
- `sortablejs@latest` in `base.html` is unpinned — a breaking upstream update could break the app.
- Inline `<script>` blocks in 6 templates (`karte.html`, `termin.html`, `termin_edit.html`, `mitglied.html`, `artikel_history.html`, `ort_detail.html`) should be extracted to separate JS files.
- Inline `style=` attributes in templates bypass the design system and lack dark mode support.

**Higher risk (35-55%)** — need careful planning:
- Many hardcoded hex colors in `intern.css` (attendance badges, diff views, wiki code block, toasts, outdated banner) lack CSS variables and some lack dark-mode overrides.
- `main.css` (public homepage) defines `.content` with different properties than `intern.css` — potential clash if both load on the same page.
- `alert()`/`confirm()` in `intern.js` for UX feedback should be replaced with toast/modal components, but `confirm()` gates destructive actions so control flow changes.
- `visible_fields()` in `views/files.py` has dual behavior: returns column list on GET, saves and redirects on POST. Splitting it requires touching call sites in `titel.py` and `mitglieder.py`.
- URL parameter naming is inconsistent across views (`id` vs `pk` vs `forum` vs `titel`). Standardizing requires updating URL patterns, view signatures, templates, and `reverse()` calls.

### Notable utilities (`intern/`)

- `replacements.py` — wiki-like markup processor (lists, code blocks, `[[Datei:...]]` file links)
- `php_pbkdf2_hasher.py` — legacy password hasher for migrating users from a prior PHP system; listed in `PASSWORD_HASHERS` in settings
- `fuzzy.py` — fuzzy song title matching used in article references
- `context_processors.py` — injects global template context (`VERSION`)

**External integrations:**
- `ejabberd.py` — REST API client for ejabberd admin API and message sending

**Management commands:**
- `ejabberd_bot` — slixmpp XMPP bot for MUC message forwarding
- `ejabberd_sync` — sync XMPP users/rooms at startup

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

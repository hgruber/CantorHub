# Architecture: request flow, URLs, logging, cache, configuration

How a request reaches Django, what Django assumes about the machinery in front of it, and
where the runtime knobs live. The operator-facing side of the same subject — what to put
into haproxy and nginx, and how to verify it — is in `README.md`.

## Request flow

```
Browser → haproxy (TLS) → nginx (port 8000) → gunicorn (127.0.0.1:8001) → Django
```

Nginx serves `/static/`, `/media/`, and `/tiles/` directly; everything else is proxied to
gunicorn. In development, `manage.py runserver` handles everything.

## What Django assumes about the proxy

Two of those assumptions cannot be checked from inside Django, so getting them wrong fails
silently:

- **The client IP.** `_client_ip()` (`views/auth.py`) takes the *last* entry of
  `X-Forwarded-For` — a client-supplied header always ends up further left and can
  therefore never win. That only holds because nginx runs the realip module, which turns
  `$remote_addr` into the real client address before it is forwarded as the single XFF
  entry. Without it every visitor arrives as the proxy's address, which silently turns both
  rate limits (password reset, mailing-list sign-up) into *global* ones — one sender then
  locks out everybody — and makes `Auftrittsabo.bestaetigt_ip` worthless as Art. 7(1)
  evidence. Getting it wrong is fail-safe: realip simply does not engage and behaviour falls
  back to what it was.
- **`X-Forwarded-Proto: https`.** When it does not match `SECURE_PROXY_SSL_HEADER`,
  `request.is_secure()` is permanently `False` and every `build_absolute_uri()` emits
  `http://` links: the password-reset mail, and via `_base_url()` the opt-in and unsubscribe
  links of every mailing-list mail.

`X-Forwarded-Host` and `X-Forwarded-Port` are **deleted** by nginx and correspondingly
`USE_X_FORWARDED_HOST` / `USE_X_FORWARDED_PORT` are off: no hop in this chain sets either
header, so whatever arrives is the client's own invention — and Django would feed it into
`request.get_host()`/`get_port()` and hence into every `build_absolute_uri()`. The real host
travels in the `Host` header, which nginx forwards. Do not switch those settings back on
without a proxy that actually writes the headers.

gunicorn binds to `127.0.0.1:8001` on purpose — nginx is in the same container, and a
wildcard bind would be reachable over the podman bridge, bypassing nginx and thus realip.
The dev branch (`runserver 0.0.0.0:8001`) stays open deliberately.

**Client IPs are logged in two of the three channels**, and the distinction matters for the
§10 retention promise (see `datenschutz.md`):

- The **access log is IP-free**: `log_format simple` in `nginx.conf` has no `$remote_addr`,
  gunicorn runs without an access log, and Django's `LOGGING` carries no request context. A
  normal request therefore leaves no address behind.
- The **error log does record it**: nginx writes `client: <IP>` on every error — a 404 under
  `/static/` or `/media/`, a rejected `auth_request` subrequest.
- The **haproxy log** (`%ci`) is the third place, one hop earlier.

## URL structure

- `/` — public homepage (`index.html` of the `startseite` template engine, see
  `docs/startseite.md`), `/startseite/*` its images and CSS
- `/einrichtung/` — first-run setup of a new installation (`intern/einrichtung.py`); `404`
  once a superuser exists
- `/datenschutz/` — public privacy policy (`intern/templates/datenschutz.html`, no login
  required, `TemplateView` in `config/urls.py`)
- `/auftritte/`, `/auftritte/bestaetigen/<token>/`, `/auftritte/abmelden/<token>/` — public
  gig-reminder mailing list, no login (`mailinglist.md`)
- `/.well-known/carddav` → `301` → `/carddav/`, and `/carddav/*` — read-only CardDAV address
  book (HTTP Basic, **not** the portal session; `dav.md`)
- `/.well-known/caldav` → `301` → `/caldav/`, and `/caldav/*` — read-only CalDAV calendar,
  same auth. Both services advertise each other, so one base URL finds both
- `/tiles/<z>/<x>/<y>.png` — OSM tile proxy (no login required). In production nginx
  intercepts this and serves from its disk cache (`/data/tiles/`, 7-day TTL) without hitting
  Django. In dev, `tiles_proxy` in `karte.py` fetches from OSM server-side so the user's IP
  is never sent to OSM.
- `/admin/` — Django admin
- `/intern/*` — all authenticated views (`intern/urls.py`)
- `/intern/changelog/` — the release notes from `CHANGELOG.md` (`auslieferungen` in
  `views/auslieferungen.py`, `perm_or_home` with `manage_user_permissions` or `manage_folder_permissions`); the version
  line in the sidebar footer is shown to everyone and links here under the same rights only,
  older releases are loaded in batches. Not to be confused with `/intern/aenderungsprotokoll/`,
  which is the audit trail. See `frontend.md`.
- `/intern/karte/geocode/` — Nominatim geocoding proxy (`geocode_proxy` in `karte.py`, login
  required); passes query params server-side so the user's IP is never sent to Nominatim.

## Logging

`settings.py` defines a `LOGGING` dict. The `intern` logger hierarchy is set to `INFO`; root
and `django` loggers to `WARNING`. All output goes to stdout via `StreamHandler` (`stream:
ext://sys.stdout`), which appears in `podman logs` and `journalctl`. Using stdout ensures
systemd assigns the correct `PRIORITY` based on the Python log level, so INFO/WARNING entries
are not coloured red in journalctl. Custom loggers use `logging.getLogger(__name__)` — they
all fall under `intern.*` and are therefore visible.

## Sessions

Sessions live in the database (Django's default backend). `SESSION_SAVE_EVERY_REQUEST` is
**off**: with it, every request rewrote the session row — a transaction plus an fsync of
roughly ten milliseconds — and that included every nginx `auth_request` under `/media/` and
both polls. A gallery page with 48 thumbnails therefore issued 48 *writing* requests that
queued behind each other on three worker processes. Measured on the media check: 22.5 ms with,
1.5 ms without.

`intern.middleware.Ersteinrichtung` (listed right after `SecurityMiddleware`) redirects every
request except `/einrichtung/` and `/static/` to the first-run setup while the database has no
superuser — a new installation, see `README.md`, „First start on an empty database". Until then
`ALLOWED_HOSTS` is `["*"]` (set by `InternConfig.ready()` when no address is configured); on the
first request after the setup each worker replaces it with the hosts of the stored address
(`einrichtung.hosts_festlegen`). That is why it sits before `CommonMiddleware`, which checks the
host. The check is one `exists()` query until it first answers yes; from then on the process
remembers it and the middleware costs nothing.

`intern.middleware.SitzungAuffrischen` (listed right after `AuthenticationMiddleware`) keeps
the sliding expiry instead: for a logged-in member it stores the current time in the session
key `_aufgefrischt`, but at most once every `AUFFRISCH_INTERVALL` seconds (five minutes).
Writing that key marks the session as modified, so Django saves it and pushes `expire_date`
forward. The consequence is that the four-hour idle timeout is accurate to five minutes rather
than to the second. Anything that changes the session anyway — logging in, dismissing the event
banner — is saved immediately as before. The decision itself is the pure function
`muss_auffrischen(stand, jetzt, intervall)`, tested without a database.

`intern.middleware.DatenschutzPruefung` sits right behind it and sends an account with access
but without membership to the privacy confirmation first; it costs one group query per request
under `/intern/` and is described in `docs/members.md`, „Privacy confirmation without
membership".

## Per-request cache

Beyond the configuration cache described below, `intern/anfragespeicher.py` holds values that
recur within one request but cannot change inside it: the set of folders a member may browse
(`visible_folder_ids()`, asked three times per folder listing, three queries and a walk up the
tree each time) and the fallback avatars (`fallback_avatar_datei()`, once per bot message in a
forum). Lifetime and wiring are the configuration cache's: `request_started` opens it,
`request_finished` drops it, both in `signals.py`, and **outside a request it deliberately does
not engage** — the two endless loops would otherwise serve their start-up state forever. Writing
a `FolderPermission` or a `Folder` empties it, because that shifts which folders are visible and
from where their rights are inherited.

## Cache

`CACHES` uses `DatabaseCache` (table `cache_table`), and it carries exactly one thing: the
two IP rate limits — password reset (`views/auth.py`) and mailing-list sign-up
(`views/auftritte.py`). Nothing else in the project uses the Django cache; the
`_nick_jid_cache` in `ejabberd_bot.py` is a plain dict.

The backend has to be shared, not per-process: with the default LocMemCache each of the three
gunicorn workers counts on its own, so the effective limit is 3× the configured value and
which worker a request lands on is luck. `OPTIONS.MAX_ENTRIES` is raised to 10000 for the
same reason the limits exist — Django's default of 300 makes `DatabaseCache` cull a third of
all rows on overflow (`CULL_FREQUENCY` 3), which an attacker could use to evict the very
counters that throttle them.

The table is created by `python manage.py createcachetable` in `start.sh`. That is plain DDL,
**not** a migration, and idempotent. If the table is
missing the throttles fail loudly rather than silently switching themselves off — that is
deliberate, hence no `try/except` around the cache calls.

Unaffected by all of this: the DB-backed cooldown on `Auftrittsabo.optin_gesendet_am`, which
is the brake that actually prevents mail-bombing a foreign address.

## Database

SQLite in development (`db.sqlite3`, excluded from git). MySQL-compatible for production via
`pymysql`.

## Environment variables

Only bootstrap settings (needed before the DB is available) are real env vars, and each of them
is exactly one variable:

- `DATABASE_URL` — `mysql://user:pw@host:port/name` or `sqlite:////data/db.sqlite3`; unset →
  SQLite in the data directory. Parsed by `config/datenbank.py`.
- `VEREINS_URL` — base URL of the portal. `settings.py` derives `ALLOWED_HOSTS` and
  `CSRF_TRUSTED_ORIGINS` from it (`hosts_aus_url`); `InternConfig.ready()` reads the value from
  the `Konfiguration` table when the variable is absent, so it is optional. Neither set nor
  configured → any host until the first-run setup stores the address, afterwards only
  `localhost`, plus a warning in the log.
- `CANTORHUB_DATA` — directory for everything that changes (`/data` in the image, set there;
  the project directory in development). Feeds `MEDIA_ROOT`, the secret key file and the SQLite
  fallback; nginx knows `/data/media` and `/data/tiles` as fixed paths.
- `CANTORHUB_VERSION` — the bare version string, baked in at build time by `build.sh` from
  `git describe --tags`. `settings.VERSION` prefixes the product name.
- `SECRET_KEY` — optional override. Normally the key is generated on first start and kept as
  `$CANTORHUB_DATA/secret_key` with mode 0600 (`config/geheimnis.py`), so it survives restarts
  and image updates and with it every session. In `DEBUG` mode a fixed insecure constant is
  used, which keeps the test run from writing anything to disk.
- `DEBUG` — set to `1` for development mode

**Neither `config/datenbank.py` nor `config/geheimnis.py` imports Django**, and `settings.py`
must not touch the database at import time: the whole test suite is `SimpleTestCase` and runs
without one.

## Runtime configuration (`Konfiguration` table)

Operational settings are stored in the `intern.Konfiguration` key/value table, not env vars,
so they can be changed at runtime (admin or `/intern/konfiguration/`) without a redeploy.
**Read them via `intern.app_settings` helpers** (`get_config`, `get_config_bool`,
`get_config_int`) — never `os.environ`/`settings` for these — and never call the helpers at
settings/import time (the DB may not be ready).

**Within one request the whole table is read once.** `get_config()` is called a dozen times per
page — nine of them from the context processor alone — and each call used to be its own SELECT.
`request_started` now opens a per-request cache in `app_settings` that loads all rows in a single
query, `request_finished` drops it again (both wired in `intern/signals.py`, along with a
`post_save`/`post_delete` invalidation so a writer sees its own change). Outside a request the
cache deliberately does not engage: `ejabberd_bot` and `send_auftritt_erinnerungen` run as endless
loops and would otherwise serve the configuration of their start-up moment forever. There, every
key stays one query, as before.

For the one case where that hurts — bulk mail — `app_settings.konfiguration_gepuffert()` opens the
cache for a bounded block. `send_branded_mail()` reads sixteen config values per recipient
(Vereinsname three times, brand colour, footer, sender), so a run over 50 subscribers was 800
queries for values that cannot change mid-run. The context manager wraps **one pass** of
`send_auftritt_erinnerungen` / `send_reconfirmation`, never the endless loop itself — the sleep
interval is read after each pass and has to stay outside, or a changed interval would never take
effect. It is re-entrant: inside a request it leaves the existing cache alone instead of dropping
it on exit.

Environment variables take priority over DB values in `get_config()`, **and are also persisted
to the DB during `post_migrate`** (`_seed_config` in `intern/apps.py` calls `update_or_create`
for every key that has a matching ENV var). A container started with `-e
EJABBERD_BOT_JID=...` writes the value into the DB — on subsequent starts the ENV var can be
dropped and the DB value is used. Use `is_ejabberd_configured()` (not a flag) to check whether
the XMPP integration is active.

**Adding a key takes three edits**, and two tests enforce the last two:

1. `_CONFIG_DEFAULTS` in `intern/apps.py`, with a German `description`, so fresh installs get
   it.
2. A group in `intern/konfig_gruppen.py` (exact key or prefix) — otherwise
   `KonfigGruppenTest` fails, because it asserts that every `_CONFIG_DEFAULTS` key lands in a
   group other than „sonstiges". The page groups the keys into nine collapsible cards derived
   from the key name; the grouping is not stored in the DB.
3. An entry in `FELDTYPEN` in the same file (`bool` / `int` / `string` / `text`) so the edit
   page renders the matching widget instead of a textarea for every value. `KonfigTypenTest`
   enforces it. The stored value stays a string regardless — `get_config_bool` /
   `get_config_int` still parse it. An unknown key falls back to `text`.

Edits — via `/intern/konfiguration/` or the admin — are recorded in the `ChangeLog` audit trail
(`Änderungsprotokoll`) like any other tracked model (`_AUDIT_FIELDS["Konfiguration"]` in
`intern/signals.py`). Keys whose name contains `PASSWORD`/`SECRET`/`TOKEN` have their `value`
diff redacted to `***` rather than logged in plaintext. The `post_migrate` env-var reseed in
`_seed_config` runs with `_migrating.active` set, so it never shows up as a spurious "System"
change on every restart.

Choir-specific initial values (`VEREINSNAME`, `VEREINSNAME_KURZ`, `HOMEPAGE_UEBER_UNS`,
`HOMEPAGE_AUFNAHME`, …) live in `seed_konfiguration` in `intern/migrations/0003_import.py` —
those keys carry an empty-string default in `apps.py` and get their real content only via the
data migration, so the codebase stays deployable for other organisations without pre-filled
choir text.

`VEREINSNAME` is exposed via `get_vereinsname()` in `app_settings.py`, injected into every
template context by `config/context_processors.py` (`{{ vereinsname }}`), and into every email
render in `mail.py`. For outgoing mail always pass `get_from_email()` as the sender.
Frontend-facing values (`NOTIFY_POLL_MS`, `NOTIFY_DISMISS_MS`) reach JS via
`context_processors.project_meta` → `data-*` attributes on `<body>` → `notify.js`.

Beyond the three readers, `app_settings.py` holds `get_from_email()`, `get_vereinsname()`,
`get_map_center()` (the `Ort` used as the map's centre, from `MAP_CENTER_ID`) and
`get_document_url(key)`, which resolves a Filer file ID stored in a `*_FILE_ID` key to a public
HMAC token URL (`/intern/datei/<pk>/<token>/<filename>`) and returns `"#"` when unconfigured —
that is how the public join form links the Satzung and the Beitragsordnung without exposing the
file area.

`get_base_url(override=None, fallback="")` is the one way to build the portal's base URL
outside a request (mails, management commands): `VEREINS_URL`, trimmed of any trailing slash.
**Its default `fallback` is deliberately empty** — for mail an unset `VEREINS_URL` is an abort
condition (a relative unsubscribe link is a dead one), and a silent `http://localhost` would
hide that. Only the two commands that merely print a URL pass one.

The full key catalog and the mail-placeholder reference live in `configuration.md`.

## Notable utilities (`intern/`)

- `pdf.py` — `new_letterhead_pdf(title, subtitle, vereinsname, vereinsname_lang,
  vereinsadresse)` returns `(buf, canvas, content_y)`; draws the branded letterhead (logo,
  thin `#c14468` accent lines) and footer. `draw_section`, `draw_field`, `draw_checkbox`,
  `draw_signature` build the content area. Used by `_save_antrag_pdf` and
  `_save_bestaetigung_pdf` in `views/auth.py`.
- `mail.py`, `mail_markup.py` — see `mail.md`.
- `replacements.py` — wiki-like markup processor (lists, code blocks, `[[Datei:...]]` file
  links); see `articles.md`.
- `auslieferungen.py` — the release notes from `CHANGELOG.md`: decomposition, inline markup and
  the batch slice behind `/intern/changelog/`. No Markdown dependency, no Django import; the
  file is an image artefact, so there is no sanitizer in the path. See `frontend.md`.
- `verwendung.py` — which references a file has, and which of them a delete or rename would
  break; see `files.md`.
- `folder_access.py`, `avatar_access.py` — the two access axes over files; see `files.md`.
- `hashers.py` — `PortalPBKDF2Hasher`, the hasher that writes new passwords: PBKDF2-SHA256 with
  a deliberately reduced iteration count, because Django 6's default of 1,200,000 costs half a
  second of CPU per login. The module docstring carries the reasoning and the constraint.
- `php_pbkdf2_hasher.py` — legacy password hasher for users migrated from the prior PHP
  system; listed in `PASSWORD_HASHERS`. See `../migration.md`.
- `context_processors.py` — global template context (`VERSION`, `upload_max_mb`, notify
  poll/dismiss intervals, `vereinsname`, the next-event banner). **Computed once per
  request** and remembered on the request object: the processor costs about eleven
  milliseconds and seven queries, and it used to run several times per page — once for the
  page, once more inside `{% render_table %}` (django_tables2 renders the table template
  with `request=`), and in the event list once per row, because `TemplateColumn` does the
  same. That list needed 17 runs, 232 ms and 130 queries; it is now 35 ms and 13 queries.
  For the same reason `TerminTabelle.aufstellung` is a plain `Column` whose `render_`
  method calls `render_to_string` **without** a request.
- `ejabberd.py` — REST API client for the ejabberd admin API; see `xmpp.md`.

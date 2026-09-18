# CantorHub

A self-hosted member portal for a choir, built with Django 6. This file is for the people who
**run** a CantorHub instance. Developers start at `CLAUDE.md`; the one-time import from the
legacy PHP portal is described in `migration.md`.

## What it does

- **Members** — profiles with voice type, address and photo, per-field privacy settings, a
  self-service join form behind a signed invitation link, and a re-confirmation flow for the
  board.
- **Events** — calendar and month grid, attendance responses per member, locations on a map,
  and a song programme per concert.
- **Repertoire** — songs with sheet music, recordings and notes.
- **Forums** — discussions with emoji reactions, optionally bridged both ways to XMPP chat
  rooms so members can use a normal messenger app.
- **Wiki** — versioned articles with history and diffs.
- **Files** — a folder archive with permissions, previews, full-text search, file versions and
  an audio player.
- **Public homepage** with the upcoming public gigs, plus a gig-reminder mailing list with
  double opt-in.
- **Phone sync** — read-only CardDAV address book and CalDAV calendar (both off by default).
- Light/dark theme, mobile layout, German throughout.

## Running it

The container image carries the Python dependencies, nginx and its configuration; **the
application code is bind-mounted, not copied into the image**. Inside the container, `start.sh`
applies pending migrations, starts the background jobs and then runs nginx (port 8000) in front
of gunicorn (three worker processes with four threads each — the threads matter because every
file under `/media/` is checked by a Django subrequest, and short requests would otherwise wait
behind a page being rendered).

Nginx serves `/media/` with `Cache-Control: private, max-age=604800`, so a member's browser
fetches an image or a recording once rather than on every page view. `private` keeps it out of
shared caches, and the week is safe because the content under a path never changes: overwriting
a file writes a new blob and moves the references (see `docs/files.md`). If a file ever has to be
replaced *in place* out of band, change its path — or the week has to pass.

```bash
podman build -t cantorhub .
podman run -d --name cantorhub -p 8000:8000 \
    -v /srv/cantorhub:/app \
    -e DB_HOST=db -e DB_NAME=cantorhub -e DB_USER=cantorhub -e DB_PASSWORD=secret \
    -e CANTORHUB_VERSION="CantorHub v0.999" \
    cantorhub
```

Without `DB_HOST` the portal falls back to SQLite (`db.sqlite3` next to the code) — fine for a
test instance, not for production. `CANTORHUB_VERSION` fills the version line in the sidebar
(the image deliberately ships no `git`; without the variable it just shows „CantorHub").

For local development:

```bash
DEBUG=1 ./start.sh                       # migrations, background jobs, dev server on :8001
python manage.py runserver 0.0.0.0:8000  # dev server only
```

`migrate.sh` exists as well — **it deletes the whole database** and belongs to the migration.
Do not run it on a live instance.

### Updating

Application code: `git pull` in the mounted directory and restart the container.

**`nginx.conf` is the exception — it lives inside the image.** Changes to it take effect only
after a rebuild plus a container restart; a `git pull` alone silently keeps the old
configuration. Verify what is actually loaded:

```bash
podman exec cantorhub nginx -T | grep real_ip
```

## Bootstrap environment variables

Only the settings needed before the database is reachable are environment variables:

| Variable | Default | Description |
|---|---|---|
| `DEBUG` | unset | `1` enables development mode (dev server, debug pages) |
| `SECRET_KEY` | — | Django secret key. **Required unless `DEBUG=1`** — without it the application refuses to start (`ImproperlyConfigured`); in development it falls back to a fixed insecure value |
| `DB_HOST` | — | MySQL host; unset → SQLite |
| `DB_NAME` | `cantorhub` | MySQL database name |
| `DB_USER` | `cantorhub` | MySQL user |
| `DB_PASSWORD` | — | MySQL password |
| `DB_PORT` | `3306` | MySQL port |

Two settings are still hardcoded in `config/settings.py` and need editing when the portal moves
to a new hostname: `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`. A missing entry shows up as
"Bad Request (400)" or as rejected form submissions.

Everything else — mail server, XMPP, map, upload limits, all mail texts — lives in the database
and is edited at runtime under `/intern/konfiguration/`. As a convenience, any such key may also
be passed as an environment variable on first start: it is then written into the database during
`post_migrate`, after which the variable can be dropped again.

## Reverse proxy

The expected chain is:

```
Browser → haproxy (TLS) → nginx (port 8000, in the container) → gunicorn (127.0.0.1:8001) → Django
```

Two headers must be right, and **Django cannot detect either of them going wrong**:

- **`X-Forwarded-Proto: https`** — haproxy has to set the literal string. `%[ssl_fc]` renders as
  `1`/`0` and never matches, and then every generated link is `http://`: the password-reset mail
  and the opt-in/unsubscribe links of every mailing-list mail. Use
  `set-header X-Forwarded-Proto https if { ssl_fc }` (or `%[ssl_fc,iif(https,http)]` from haproxy
  2.3 on).
- **The client address.** nginx resolves it with the realip module
  (`set_real_ip_from 10.88.0.0/16; real_ip_header X-Forwarded-For;`). The trusted range is the
  podman network — **adjust it if the deployment moves.** Without it every visitor arrives as the
  proxy's address, which turns both rate limits (password reset, mailing-list sign-up) into
  global ones — a single sender then locks out everybody — and makes the stored consent IP of the
  mailing list worthless as evidence.

`X-Forwarded-Host` and `X-Forwarded-Port` are deliberately stripped by nginx; do not add a hop
that sets them.

To check what nginx actually resolves, request a file that does not exist (no login needed,
leaves nothing behind) and read the `client:` field of the resulting error line:

```bash
curl -s -o /dev/null https://<host>/static/proxy-check-gibtsnicht.css
journalctl -u <unit> -n 30 --no-pager | grep proxy-check
```

Uploads are limited twice: `client_max_body_size 512M` in `nginx.conf` and the `UPLOAD_MAX_MB`
configuration key, which is what members see enforced in the browser.

## Runtime configuration

Everything operational is a key/value row in the database, editable under
`/intern/konfiguration/` (grouped into nine cards) or in the Django admin. The complete catalog
is in `docs/configuration.md`; these are the ones that decide whether things work at all:

| Key | Why it matters |
|---|---|
| `VEREINS_URL` | Base URL used to build links in mails. **Unset, the gig-reminder daemon refuses to send at all** (an unsubscribe link must be absolute), and activation mails lose their button |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`/`_SSL` | SMTP. Empty host → mail is logged, not sent |
| `DEFAULT_FROM_EMAIL` | Sender address of every outgoing mail |
| `MAIL_BEI_AKTIVIERUNG` | `0` suppresses activation and reactivation mails — useful while testing |
| `ANTRAG_EMAIL` | Where new membership applications are announced; empty → everyone who may edit members |
| `MAIL_*` | The full text of every automated mail (see `docs/mail.md`) |
| `VEREINSNAME`, `VEREINSNAME_LANG`, `VEREINSNAME_KURZ`, `VEREINSADRESSE` | Name and address used in the UI, mails and PDFs |
| `BRAND_FARBE` | Accent colour (hex) used in the UI, mail headers/buttons and the PDF letterhead |
| `HOMEPAGE_UEBER_UNS`, `HOMEPAGE_AUFNAHME` | The copy on the public homepage |
| `SATZUNG_FILE_ID`, `BEITRAGSORDNUNG_FILE_ID` | Filer file IDs of the two PDFs the join form links to |
| `UPLOAD_MAX_MB` | Maximum upload size |
| `MAP_CENTER_ID`, `MAP_DEFAULT_ZOOM` | Centre and zoom of the overview map |
| `PWRESET_MAX_PER_HOUR` | Password-reset requests per IP per hour |
| `ICAL_SECRET` | Secret in the public iCal feed URL — rotating it invalidates existing subscriptions |
| `CARDDAV_AKTIV`, `CALDAV_AKTIV` | Master switches of the phone sync, **both `0` by default** |
| `EJABBERD_*` | XMPP integration; inactive while host and bot JID are empty |

### Optional services

- **XMPP forum bridge** — becomes active once `EJABBERD_HOST` and `EJABBERD_BOT_JID` are set.
  `start.sh` then runs the sync and the relay bot. Server-side requirements and the admin CLI are
  in `docs/xmpp.md`.
- **CardDAV / CalDAV** — while the switch is `0`, the URLs answer `404`, i.e. the service does not
  exist. Turning it on means member data (including photos and, optionally, birthdays) lands in
  personal phone address books and their cloud backups: **inform the members first** — the privacy
  policy covers this in its „Sichtbarkeit Deiner Daten im Portal" section. Members then use
  `https://<host>/` with their normal portal login;
  one base URL finds the address book and both calendars. Anyone who would rather not be in the
  address book at all can switch that off in their own profile — no board action needed, so say so
  when you announce the service.
- **iCal feed** — `/intern/calendar/<ICAL_SECRET>.ics`, needs no login and works with Google
  Calendar, which cannot subscribe to CalDAV.
- **Gig-reminder mailing list** — public sign-up at `/auftritte/` with double opt-in; reminders go
  out for events flagged as public gigs. Needs `VEREINS_URL` and a working SMTP server.

## Background jobs

`start.sh` launches these; there is no scheduler, they are plain loops or one-shot jobs:

| Job | What it does |
|---|---|
| `ejabberd_bot` | Relays messages between forums and XMPP rooms (only when XMPP is configured) |
| `send_auftritt_erinnerungen --loop` | Sends the gig reminders when they fall due (event time minus N weeks, with a 24 h grace window) |
| `cleanup_changelog` | Deletes audit-log entries older than 3 years — this is what backs the retention promise in the privacy policy |
| `cleanup_dateiversionen --days 36500 --keep 25` | Prunes superseded file revisions and their blobs |

Two things about the cleanup jobs are worth knowing:

- They **never touch live files or content** — `cleanup_dateiversionen` only ever deletes
  revisions that have been replaced, and by construction those are invisible in the folder view.
- The parameters in `start.sh` deliberately switch the **age** rule off (36500 days ≈ 100 years),
  so only the count rule applies: each file keeps its newest 25 revisions, forever. This protects
  the profile-picture history imported from the legacy system. In other words, **there is
  currently no time-based deletion of old file revisions.**

Server logs are the third retention item and are not handled by the application — see below.

## Management commands

Run with `podman exec cantorhub python manage.py <command>`.

| Command | Description |
|---|---|
| `send_reconfirmation --user USERNAME` / `--all` | Ask one member / all active members with an address to re-confirm their data |
| `send_reconfirmation … --print-url` | Print the confirmation URLs instead of sending mail — one URL for `--user`, tab-separated `username<TAB>url` lines for `--all`. Add `--base-url https://portal.example.com` to override `VEREINS_URL` |
| `make_invite_url EMAIL` | Print a signed invitation link to the join form without sending mail (valid `MITGLIED_EINLADUNG_TAGE` days, default 7) |
| `send_auftritt_erinnerungen [--dry-run] [--now ISO] [--termin ID] [--force]` | One pass of the gig reminders. `--now` tests the timing without touching the clock; `--force` ignores existing send markers (use after a crashed batch) |
| `cleanup_changelog [--days N] [--dry-run]` | Delete audit-log entries past the retention period (config key `AENDERUNGSPROTOKOLL_AUFBEWAHRUNG_TAGE`, default 1095 days) |
| `cleanup_dateiversionen [--keep N] [--days N] [--dry-run]` | Prune old file revisions and their blobs (config keys `DATEIVERSION_AUFBEWAHRUNG_ANZAHL` / `DATEIVERSION_AUFBEWAHRUNG_TAGE`; command defaults: keep 10, 730 days) |
| `cleanup_erinnerung_versand [--days N] [--dry-run]` | Delete `ErinnerungVersand` send markers past the retention period (config key `ERINNERUNG_VERSAND_AUFBEWAHRUNG_TAGE`, default 365 days). Wire into `start.sh` alongside the other cleanup jobs |
| `ejabberd_admin sync` | Full XMPP startup sync — bot account, room JIDs, room configuration |
| `ejabberd_admin <group> <verb>` | XMPP admin operations: `bot ensure`; `room {list,assign-jids,configure,delete,avatar,members,occupants,options}`; `user {list,delete,vcard,password}`; `invite {add,remove,clear}`; `server users` |
| `ejabberd_bot` | Run the XMPP relay bot in the foreground |
| `index_files`, `thumbnail_files` | Rebuild the file search index / pre-generate thumbnails |
| `seitenmessung [--nutzer NAME] [--laeufe N] [--seite TEXT]` | Measure the response time and query count of the main pages. It copies the SQLite file first and throws the copy away afterwards, so the running database is never written to; the last column names a query that occurs more than three times, which is how a per-row query gives itself away |
| `createsuperuser` | Django's own — create an administrator |

**Never run `filer_check --delete-orphans`.** File revisions are stored without a database row on
purpose, so that command would delete the entire version history.

## Logs and troubleshooting

Everything logs to stdout/stderr and therefore lands in `podman logs` / journald; rotation is a
host-side setting.

- The **access log contains no IP addresses** by design. The **error log does** (`client: <IP>`),
  which is the quickest way to check what the proxy chain resolves.
- **Mails contain `http://` links** → haproxy is not setting `X-Forwarded-Proto: https` literally.
- **Mails are not arriving** → check `EMAIL_HOST`; with an empty host, mail is only logged. The
  log line names the recipient.
- **The gig reminders do nothing** → the daemon warns and writes no send marker when `VEREINS_URL`
  or `EMAIL_HOST` is missing. Both are re-read every iteration, so fixing the configuration is
  enough — no restart needed.
- **One member locks everyone out of password reset** → the realip configuration is not in effect,
  so all requests are counted against the proxy's address.
- **A phone will not connect to CardDAV/CalDAV** → the service switch is still `0`; the URLs then
  answer `404` rather than asking for a password.

## Backup

Two things have to be backed up together:

1. the **database** (all content, members, configuration), and
2. the **`media/` directory** (every uploaded file, every profile picture, and every superseded
   revision of both).

Restoring only one of them leaves dangling references. Note that a deleted file frees its stored
data only when the last folder entry pointing at it is gone — the same file can legitimately
appear in several folders.

## License

Proprietary — for internal use by the operating choir.

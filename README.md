# CantorHub

A self-hosted member portal for a choir, built with Django 6. This file is for the people who
**run** a CantorHub instance. Developers start at `CLAUDE.md`; the one-time import from the
legacy PHP portal is described in `migration.md` (history only — it has run).

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

The container image is self-contained: application code, collected static files, nginx and its
configuration all live inside it, and it carries its version number. Nothing is bind-mounted
except **one volume for the changing data** (`/data`). Inside the container, `start.sh` applies
pending migrations, starts the background jobs and then runs nginx (port 8000) in front of
gunicorn (three worker processes with four threads each — the threads matter because every file
under `/media/` is checked by a Django subrequest, and short requests would otherwise wait
behind a page being rendered).

Nginx serves `/media/` with `Cache-Control: private, max-age=604800`, so a member's browser
fetches an image or a recording once rather than on every page view. `private` keeps it out of
shared caches, and the week is safe because the content under a path never changes: overwriting
a file writes a new blob and moves the references (see `docs/files.md`). If a file ever has to be
replaced *in place* out of band, change its path — or the week has to pass.

```bash
./build.sh                               # names the image after `git describe --tags`

podman run -d --name cantorhub -p 8000:8000 \
    -v cantorhub-data:/data \
    -e DATABASE_URL=mysql://cantorhub:secret@db:3306/cantorhub \
    -e VEREINS_URL=https://chor.example.de \
    cantorhub:v1.0.0
```

`VEREINS_URL` is optional: without it the first-run setup takes the address from the first
call and stores it (see below). If set, it is written into the database on every start and wins
over the stored value. Without `DATABASE_URL` the portal falls back to SQLite in `/data` — fine
for a test instance, not for production.

A throwaway demo needs neither: `podman run --rm -p 8000:8000 cantorhub` starts on an empty
SQLite inside the container, `http://localhost:8000/` leads straight into the first-run setup,
and stopping the container discards everything.

### First start on an empty database

Point `DATABASE_URL` at an empty database (or at none) and start the image: `migrate` builds the
schema, and since there is no administrator yet, every page redirects to `/einrichtung/`.
**Whoever finishes that page first becomes the administrator** — there is no token or other
guard, so on a public address do it right after the first start. Until then Django accepts any
hostname, because the address is not known yet; the form prefills it from the call itself.

The page asks for the first account (it becomes superuser and joins „Mitglied“ and
„Vorstand“), the portal address, the sender address and, optionally, the SMTP server. Finishing
it creates the permission groups, the standard folders, the Vorstand folder right, the start
page „Aktuell“, the help pages („Hilfe“ and `Hilfe:…`, written for members with little computer
experience, including the phone set-up of calendar, contacts and chat, and for the board what running
an own server needs and costs) and neutral placeholder
pictures for members without a photo, logs the new account in and opens
`/intern/konfiguration/`, whose banner lists the settings still missing (the hoster and the
data-protection authority for the privacy policy). The box „Beispieldaten anlegen“ (on by default) adds a
place, a few German folk songs, six weekly rehearsals, a concert with its running order and
homepage announcement, and the forum „Allgemeines“ — ordinary entries, to be edited or deleted. From then on `/einrichtung/` is
gone, and every worker restricts the accepted hostnames to the stored address on its next
request — no restart needed. An existing installation is never affected: it has an
administrator, so the step is skipped.

### The data volume

Everything that changes lives under `/data`; nothing of it belongs in the image:

```
/data/media/              uploads, filer blobs and thumbnails (MEDIA_ROOT)
/data/tiles/              nginx cache for the OSM map tiles
/data/secret_key          generated on first start, mode 0600
/data/db.sqlite3          only without DATABASE_URL
```

The secret key is **not** an environment variable: it is generated on the first start and kept
in the volume, so it survives restarts and image updates — and with it every logged-in session.
Setting `SECRET_KEY` still takes precedence if you would rather manage it yourself.

For local development nothing changes; without `CANTORHUB_DATA` everything stays next to the
code as before:

```bash
DEBUG=1 ./start.sh                       # migrations, background jobs, dev server on :8001
python manage.py runserver 0.0.0.0:8000  # dev server only
```

Schema changes ship as checked-in migrations; `start.sh` applies the ones still missing with
`python manage.py migrate` on every start, before anything else runs. Nothing to do by hand.

### Updating

Build a new image and restart the container — the code is part of the image, so there is no
`git pull` on the server any more, and `nginx.conf` is no longer a special case. The volume is
untouched by an update. To verify what is actually loaded:

```bash
podman exec cantorhub nginx -T | grep real_ip
```

If the server hosts the bare repository the project is pushed to, `post-receive.sh` does the
build there. Install it once:

```bash
scp post-receive.sh root@server:/root/podman/CantorHub.git/hooks/post-receive
ssh root@server chmod +x /root/podman/CantorHub.git/hooks/post-receive
```

From then on a push to `master` changes nothing on the server; **a version tag builds the
image**. The hook accepts a tag only if it is named `v<major>.<minor>.<patch>` (optionally with
a pre-release suffix, `v1.0.0-rc1`) and sits on `master`, exports that tag with `git archive`
into a scratch directory, and builds `cantorhub:<tag>` plus `cantorhub:latest` from it. Older
version images beyond the newest three are removed, and the build log is appended to
`/var/log/cantorhub-build.log`. `NEUSTART=1` at the top of the script restarts the container after
a successful build — leave that off until the unit no longer mounts the old working copy over
`/app`.

A pre-release moves `:latest` **only while no final version is tagged yet**: during the run-up to
1.0.0 the service, which starts `:latest`, follows every `v1.0.0-rcN`; once `v1.0.0` exists,
`:latest` belongs to final versions and a later `v1.1.0-rc1` no longer drags production along.
The hook decides that from the tags in the repository, so there is no switch to remember.

```bash
git tag -a v1.0.1 -m "Release 1.0.1"
git push origin master v1.0.1     # the build runs on the server, output comes back as `remote:`
```

### The changelog is part of the release

A second hook makes sure a release says what changed. Install it next to the first one:

```bash
scp update.sh root@server:/root/podman/CantorHub.git/hooks/update
ssh root@server chmod +x /root/podman/CantorHub.git/hooks/update
```

`update` runs once per ref, before the ref is written, and **refuses a version tag whose commit
carries no filled section for exactly that version in `CHANGELOG.md`** — a heading
`## v1.0.1 — 2026-09-21` followed by at least one bullet. Only the tag is refused; `master` still
lands, and since a branch push changes nothing on the server, nothing is built. The work
therefore never waits for the changelog, the delivery does. A release is:

1. rename the `## Unveröffentlicht` heading in `CHANGELOG.md` to `## v1.0.1 — <date>`
2. commit it
3. `git tag -a v1.0.1 -m "Release 1.0.1"`
4. `git push origin master v1.0.1`

**Pre-releases are cheap.** `v1.0.0-rc2` is accepted if a filled `## v1.0.0-rc2`, `## v1.0.0` or
`## Unveröffentlicht` section exists — whichever comes first. So during an rc phase you keep
collecting under `## Unveröffentlicht` and tag as often as you like; the section that has to be
written is the one for the final version, and writing it is the release step above. The rc
sections already in the file simply stay where they are, below the final version.

**How a section is written.** The file follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/):
inside a version, the entries are grouped by the kind of change, under `### Hinzugefügt` /
`### Geändert` / `### Behoben` / `### Entfernt` (also `Veraltet` and `Sicherheit` if they apply),
and each entry is **at most three sentences** — what changed, not why. The reasoning, the
measurements, the alternatives that were rejected: that belongs in the commit message, which is
where anyone wanting the details should look. Three hashes for the groups, never two: `## Added`
would be read as a release section and would reach the portal as a card. The hook does not care —
it only looks for `## ` headings and at least one bullet inside — but the page does.

A rejection names the missing section and the way out; forgetting it costs one commit and a
`git tag -f`. In an emergency the marker `[ohne-changelog]` in the message of an annotated tag
lets the tag through, and that is written to `/var/log/cantorhub-build.log`:

```bash
git tag -f -a v1.0.1 -m "Release 1.0.1 [ohne-changelog]"
git push --force origin v1.0.1
```

`git push -o changelog=skip` would be the more convenient escape hatch and the hook does look for
it, but git hands push options to `pre-receive` and `post-receive` only — measured with 2.55, the
`update` hook sees none — so the tag message is the escape hatch that works.

## Bootstrap environment variables

Only what has to be known before the database is reachable is an environment variable — and
only the first line is one you normally set:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | SQLite in `/data` | `mysql://user:password@host:3306/name` or `sqlite:////data/db.sqlite3`. Characters like `@` or `/` in the password must be percent-encoded (`%40`, `%2F`) |
| `VEREINS_URL` | — | Base URL of the portal. Fills `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` and is written into the database on every start; optional — the first-run setup stores the address otherwise |
| `DEBUG` | unset | `1` enables development mode (dev server, debug pages) |
| `SECRET_KEY` | generated | overrides the generated key in `/data/secret_key` |
| `CANTORHUB_DATA` | `/data` | set inside the image; the directory for everything changing |

If `VEREINS_URL` is neither set nor configured and there is no administrator yet, any hostname is
accepted, so the first-run setup is reachable. With an administrator but no address, only
`localhost` and `127.0.0.1` are accepted and every request under the real hostname is answered
with "Bad Request (400)"; the log says so in plain words.

Everything else — mail server, XMPP, map, upload limits, language, time zone, all mail texts —
lives in the database and is edited at runtime under `/intern/konfiguration/`. As a convenience,
any such key may also be passed as an environment variable on first start: it is then written
into the database during `post_migrate`, after which the variable can be dropped again.

## Language and time zone

German is the default throughout, and the image is built for it: the `de_DE.UTF-8` locale is
generated, `LANG`/`LC_ALL` and `TZ=Europe/Berlin` are set, and the system time zone database is
installed explicitly. Neither is cosmetic. Without the locale, the month names in the portal
come out English — Debian's `locale-gen` ignores its argument and reads `/etc/locale.gen`, so
simply asking for a locale on the command line generates nothing. And every timestamp in the
portal is naive local wall-clock time (`USE_TZ = False`), so without `/usr/share/zoneinfo` the
process would silently fall back to UTC and every displayed time would be off by an hour or two.

Both are configuration keys and can be changed at runtime: `SPRACHE` (default `de-de`) and
`ZEITZONE` (default `Europe/Berlin`). A changed time zone takes effect for CalDAV at once and
for the rest of the portal on the next restart. The portal's own texts are German and are not
translated; `SPRACHE` governs Django's own messages plus the date and number formats.

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
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`/`_SSL` | SMTP. Empty host → mail is logged, not sent, and the „Passwort zurücksetzen" page locks its button (no link can reach a member) |
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
  `start.sh` then runs the sync and the relay bot in the background. Server-side requirements and the admin CLI are
  in `docs/xmpp.md`.
- **CardDAV / CalDAV** — while the switch is `0`, the URLs answer `404`, i.e. the service does not
  exist. Turning it on means member data (including photos and, optionally, birthdays) lands in
  personal phone address books and their cloud backups: **inform the members first** — the privacy
  policy covers this in its „Sichtbarkeit Deiner Daten im Portal" section. Members then use
  `https://<host>/` with their normal portal login;
  one base URL finds the address book and both calendars. Anyone who would rather not be in the
  address book at all can switch that off in their own profile — no board action needed, so say so
  when you announce the service.

  DAVx⁵ and iOS find both services through `/.well-known/` alone. GNOME Online Accounts (and
  other clients that start from DNS) also need two **SRV records** (RFC 6764) on the portal's
  domain — without them GOA probes only `OPTIONS /` (the homepage, no `DAV:` header), then the
  Nextcloud path `/remote.php/dav`, and gives up with „Cannot find WebDAV endpoint“:

  ```
  _caldavs._tcp.<domain>.   IN SRV 0 1 443 <host>.
  _carddavs._tcp.<domain>.  IN SRV 0 1 443 <host>.
  ```

  In a registrar's web form that is: name `_caldavs._tcp` / `_carddavs._tcp`, type `SRV`,
  priority `0`, target `1 443 <host>.` (weight, port, host). No TXT `path=` record is needed;
  the clients fall back to `/.well-known/caldav|carddav`. Check with
  `dig +short SRV _caldavs._tcp.<domain>`. Do **not** redirect `/remote.php/dav`: GOA then takes
  the server for a Nextcloud and configures a broken „Files“ entry.
- **iCal feed** — `/intern/calendar/<ICAL_SECRET>.ics`, needs no login and works with Google
  Calendar, which cannot subscribe to CalDAV.
- **Gig-reminder mailing list** — public sign-up at `/auftritte/` with double opt-in; reminders go
  out for events flagged as public gigs. Needs `VEREINS_URL` and a working SMTP server.

### Your own homepage

The public homepage ships with the image. On a start without `startseite/` in the data volume
(`/data/startseite/` inside the container), `start.sh` copies the shipped demo page there — so
the files you see are the ones you edit: overwrite `index.html` and the files under
`startseite/statisch/` (served at `/startseite/…`) with your own. An existing folder is never
touched, even an empty one, so you can also provide it yourself, e.g. as a git checkout you pull
into. A file missing from the folder keeps coming from the image. Changes take effect on the
next page view, no restart needed. The files must be readable by nginx inside the container. The
template variables and tags are listed in `docs/startseite.md`.

The same folder carries your **logo**: `startseite/statisch/logo.svg` replaces the shipped
CantorHub seal everywhere in the portal (login, sidebar, error pages, favicon). Its raster
versions sit next to it: `statisch/brand/icon-192.png` (mail logo, phone home-screen icon),
`statisch/brand/icon-512.png` and `statisch/brand/briefkopf.png` (PDF letterhead, wide format).
Set `BRAND_FARBE` to match; the default is a blue (`#2b6cb0`). Name, sender and the other
choir-specific values are `Konfiguration` keys — the list is in `docs/branding.md`.

## Background jobs

`start.sh` launches these; there is no scheduler, they are plain loops or one-shot jobs. The two long-running ones (`ejabberd_bot`,
`send_auftritt_erinnerungen --loop`) are restarted 30 s after a crash (non-zero exit); a clean
exit — the bot giving up after repeated authentication failures — is final until the next
container start:

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
| `send_reconfirmation --user USERNAME` / `--all` | Ask one member / all active members (tag „Mitglied“, with an address) to re-confirm their data. Locks the portal login until the member confirms; `--user` also re-sends to an account already locked and refuses one without the tag |
| `send_reconfirmation … --print-url` | Print the confirmation URLs instead of sending mail; locks like the mail does, since an active account counts as confirmed — one URL for `--user`, tab-separated `username<TAB>url` lines for `--all`. Add `--base-url https://portal.example.com` to override `VEREINS_URL` |
| `make_invite_url EMAIL` | Print a signed invitation link to the join form without sending mail (valid `MITGLIED_EINLADUNG_TAGE` days, default 7). Refuses an address that already belongs to an account — use `send_antragslink` for that one |
| `datenschutz_zuruecksetzen --all` / `--user USERNAME` | Remove the tag „DSGVO“ so that accounts with access but without membership confirm the privacy policy and photo consent again on their next page view |
| `send_antragslink --user USERNAME` | Send an existing account without access and without the tag „Mitglied“ (e.g. a legacy account) the link to a pre-filled application form (`MAIL_EINLADUNG`); username and password stay. `--print-url` prints the link instead |
| `send_auftritt_erinnerungen [--dry-run] [--now ISO] [--termin ID] [--force]` | One pass of the gig reminders. `--now` tests the timing without touching the clock; `--force` ignores existing send markers (use after a crashed batch) |
| `cleanup_changelog [--days N] [--dry-run]` | Delete audit-log entries past the retention period (config key `AENDERUNGSPROTOKOLL_AUFBEWAHRUNG_TAGE`, default 1095 days) |
| `cleanup_dateiversionen [--keep N] [--days N] [--dry-run]` | Prune old file revisions and their blobs (config keys `DATEIVERSION_AUFBEWAHRUNG_ANZAHL` / `DATEIVERSION_AUFBEWAHRUNG_TAGE`; command defaults: keep 10, 730 days) |
| `cleanup_verwaiste_blobs [--loeschen] [--min-alter MINUTEN] [--liste]` | Report files under `MEDIA_ROOT` that no database row references any more, and delete them on an explicit `--loeschen`. Without that flag nothing happens. This is the safe stand-in for `filer_check --delete-orphans` (see below): it knows about `DateiVersion` blobs and about the previews that sit next to their blob. `--min-alter` (default 60) spares files younger than that, so a concurrent upload whose row is not committed yet survives. Not wired into `start.sh` — run it by hand |
| `cleanup_erinnerung_versand [--days N] [--dry-run]` | Delete `ErinnerungVersand` send markers past the retention period (config key `ERINNERUNG_VERSAND_AUFBEWAHRUNG_TAGE`, default 365 days). Wire into `start.sh` alongside the other cleanup jobs |
| `ejabberd_admin sync` | Full XMPP startup sync — bot account, room JIDs, room configuration |
| `ejabberd_admin <group> <verb>` | XMPP admin operations: `bot ensure`; `room {list,assign-jids,configure,delete,avatar,members,occupants,options}`; `user {list,delete,vcard,password}`; `invite {add,remove,clear}`; `server users` |
| `ejabberd_bot` | Run the XMPP relay bot in the foreground |
| `index_files`, `thumbnail_files` | Rebuild the file search index / pre-generate thumbnails |
| `seitenmessung [--nutzer NAME] [--laeufe N] [--seite TEXT]` | Measure the response time and query count of the main pages. It copies the SQLite file first and throws the copy away afterwards, so the running database is never written to; the last column names a query that occurs more than three times, which is how a per-row query gives itself away |
| `hilfe_anlegen [--autor BENUTZERNAME] [--force]` | Add the shipped help pages („Hilfe“, `Hilfe:…`) and their images to an existing installation. Pages and images that already exist under the same name are left alone; `--force` brings them to the shipped state as well — a new article version where the text differs, a new image revision — and keeps the old ones in the history. A new installation gets them from the first-run setup |
| `createsuperuser` | Django's own — create an administrator |

**Never run `filer_check --delete-orphans`.** File revisions are stored without a database row on
purpose, so that command would delete the entire version history. Use `cleanup_verwaiste_blobs`
instead — same job, but it consults `DateiVersion` as well.

**If the volume keeps growing across migration runs**, that was a bug in `start.sh` up to
v1.0.0-rc2: with `DATABASE_URL` set it dropped every table but left `media/` in place, and since
filer hands each imported file a fresh UUID path, the next import added the whole set again
instead of overwriting it. Fixed — but a volume that already carries those leftovers needs
`cleanup_verwaiste_blobs` once to get the space back:

```bash
podman exec cantorhub python manage.py cleanup_verwaiste_blobs        # report only
podman exec cantorhub python manage.py cleanup_verwaiste_blobs --loeschen
```

## Logs and troubleshooting

Everything logs to stdout/stderr and therefore lands in `podman logs` / journald; rotation is a
host-side setting.

- The **access log contains no IP addresses** by design. The **error log does** (`client: <IP>`),
  which is the quickest way to check what the proxy chain resolves.
- **Mails contain `http://` links** → haproxy is not setting `X-Forwarded-Proto: https` literally.
- **Mails are not arriving** → check `EMAIL_HOST`; with an empty host, mail is only logged. The
  log line names the recipient.
- **The gig reminders do nothing** → the daemon warns and writes no send marker when `VEREINS_URL`
  or `EMAIL_HOST` is missing — but only once a reminder is actually due, so a quiet log means
  nothing was due. Both are re-read every iteration, so fixing the configuration is enough — no
  restart needed.
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

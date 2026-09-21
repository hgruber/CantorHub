# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository. It is the
**developer** entry point: a map of the code, the rules that are not visible from any single
file, and pointers to the topic documents. Running and configuring a deployment is `README.md`;
the one-time migration off the legacy PHP portal is `migration.md`.

**Language:** this file must be written strictly in English. Do not add German prose; code
identifiers and string literals may remain in their original form. Note that the domain
vocabulary in the code *is* German (`Termin`, `Zusage`, `verknuepfte_dateien`,
`darf_avatar_aendern`) and all user-facing text is German — match the surrounding module rather
than translating.

## What this is

CantorHub is a Django 6 member portal for a gospel choir: members, events with attendance, a song
repertoire, forums bridged to XMPP, a versioned wiki, a file archive, a public homepage and a
public gig-reminder mailing list. Phones can subscribe to the directory and the calendar over
CardDAV/CalDAV.

## Commands

```bash
python manage.py runserver 0.0.0.0:8000     # dev server (DB already set up)
DEBUG=1 ./start.sh                          # dev, incl. background jobs
./start.sh                                  # container: nginx + gunicorn
DEBUG=1 python manage.py test intern        # needs no database — see invariants
python manage.py makemigrations intern --name <name> && python manage.py migrate
python manage.py seitenmessung             # Seitenzeiten + Abfragezahl, gegen eine DB-Kopie
./build.sh                                  # image, tagged from `git describe --tags`
podman run -p 8000:8000 -v cantorhub-data:/data \
    -e DATABASE_URL=… -e VEREINS_URL=… cantorhub:latest
```

The management commands an operator runs (reminders, re-confirmation mails, cleanup jobs,
ejabberd admin) are listed in `README.md`. `MIGRATE=1` selects the migration path in `start.sh`;
it wipes the database and belongs to the migration — see `migration.md`.

## Where things are documented

| Topic | File |
|---|---|
| Request flow, proxy assumptions, URLs, logging, cache, runtime config | `docs/architecture.md` |
| Files: identity, versions, standard folders, avatar protection, folder rights, retention | `docs/files.md` |
| Frontend: pages, components, design tokens, calendar, maps, homepage | `docs/frontend.md` |
| Automated e-mails and their markup | `docs/mail.md` |
| Members: joining, re-confirmation, leaving, field privacy | `docs/members.md` |
| Forums: read permissions, reactions and unread markers | `docs/forum.md` |
| Articles: versioning, editor, permissions, wiki markup | `docs/articles.md` |
| Public gig-reminder mailing list | `docs/mailinglist.md` |
| CardDAV and CalDAV | `docs/dav.md` |
| XMPP/ejabberd bridge | `docs/xmpp.md` |
| `Konfiguration` key catalog and mail placeholders | `docs/configuration.md` |
| Privacy-policy compliance tracking | `docs/datenschutz.md` |
| Known technical debt | `docs/technical-debt.md` |
| Branding extraction plan (open-sourcing) | `docs/branding.md` |

## Code map

All application logic lives in the `intern/` app; `config/` holds only settings and URL routing.
Views are split into domain modules under `intern/views/` (`auth.py`, `files.py`, `folders.py`,
`forums.py`, `titel.py`, `termine.py`, `mitglieder.py`, `artikel.py`, `karte.py`, `orte.py`,
`gallerie.py`, `auftritte.py`, `konfiguration.py`, `notify.py`). The package's `__init__.py`
re-exports all public views, so `urls.py` uses `views.forum_list` etc. unchanged.

Three underscore-prefixed modules hold what the view modules share:

- **`views/_pagination.py`** — the infinite-scroll contract: `parse_offset`, `ist_nachladen`,
  `nachlade_antwort`, `paginate_ordered`. Details in `docs/frontend.md`.
- **`views/_decorators.py`** — `perm_or_home(perm)` guards the three management pages
  (`aufgaben`, `gruppen`, `aenderungsprotokoll_list`): permission or superuser, else a silent
  redirect to „Aktuell" rather than a 403, because a member without the right never sees the menu
  entry. It includes `login_required`. `tabellenzustand` remembers a list's sort and filters in
  a per-path cookie and redirects before rendering; every view that renders `table.html` carries
  it (below `login_required`). Details in `docs/frontend.md`.
- **`views/_auswahl.py`** — `chip_eintraege()` builds the entry list `_chip_multiselect.html`
  expects, for the pages that have no Django form.

Cross-cutting modules: `models.py`, `forms.py`, `signals.py` (audit log, activation mails, filer
indexing, MUC room assignment), `app_settings.py` (runtime config), `folders.py` (the standard
folders under Backstage), `folder_access.py` / `avatar_access.py` (the two file access axes), `medientypen.py` (which files a browser can play,
shared by the folder browser and the wiki media bar), `verwendung.py` (what a delete would break),
`terminzeit.py` (what counts as an upcoming event and how the banner names the wait — all-day
events are `00:00`, see `docs/frontend.md`), `forum_gelesen.py` (the forum unread markers, see
`docs/forum.md`), `aufstellung.py` (the stage picture of the answers
in the event list),
`mail.py` / `mail_markup.py`, `mailingliste.py`, `replacements.py` (wiki markup), `pdf.py`,
`ejabberd.py`, `konfig_gruppen.py`, `middleware.py` (the throttled session refresh, see
`docs/architecture.md`), `anfragespeicher.py` (values worth computing once per request —
visible folders, fallback avatars), `tables2_beschleunigung.py` (two caches over django_tables2's per-cell work —
`signature()` and `BoundColumn.attrs`; guarded by `Tables2SignaturTest`,
`Tables2AttributeTest` and a pinned version).
`intern/dav/` is shared by `intern/carddav/` and `intern/caldav/`.

## Key models (`intern/models.py`)

| Model | Purpose |
|---|---|
| `User` | Extended `AbstractUser` — voice type, address, XMPP JID, coordinates, `private_fields`, `adressbuch_verborgen`, nullable `date_joined` (see `docs/members.md`) |
| `Artikel` | Versioned wiki articles, immutable per `(name, version)` |
| `ArtikelPermission` | Per-article read/edit restriction by group |
| `Forum` / `ForumPermission` | Discussion threads, optionally bridged to an XMPP MUC room; read restriction by group |
| `Mitteilung` / `Reaktion` | Forum messages and their emoji reactions (XEP-0444) |
| `ForumGelesen` | Per member and forum, the id of the newest message seen — the unread markers |
| `Termin` / `Ort` | Events and locations |
| `Lied` / `Konzert` | Songs in the repertoire, and the ordered song list of one event |
| `Zusage` | Per-member attendance response to an event |
| `Abstimmung` | Voting records |
| `DateiVersion` | A superseded revision of a file (path + metadata; the blob stays put) |
| `FolderPermission` | Folder access by group — **no rows means open** |
| `Konfiguration` | The runtime key/value settings table |
| `ChangeLog` | Audit trail; retention enforced by `cleanup_changelog` |
| `TabellenPreferenzen` | Per-user table column visibility |
| `Auftrittsabo` / `ErinnerungVersand` | Gig-reminder subscribers and the per-event send markers |

## URL structure

`/` homepage · `/datenschutz/` · `/auftritte/*` gig mailing list · `/carddav/*` · `/caldav/*` ·
`/tiles/<z>/<x>/<y>.png` OSM proxy · `/admin/` · `/intern/*` everything authenticated. The full
list with the well-known redirects and the two privacy proxies is in `docs/architecture.md`.

## Project-wide invariants

These hold across the whole codebase. Each is stated once here; the topic files carry the
reasoning where it matters.

- **Migrations: never create `0004+`.** `0002_add_filer.py` is regenerated on every fresh install
  and must not be committed. All model changes go into `models.py` and are picked up from there.
  The **image builds it at build time** (`makemigrations` in the `Dockerfile`, with `0003` moved
  aside because it declares a dependency on `0002`) — otherwise whether the image can migrate at
  all would depend on a gitignored file happening to sit in the build directory. Note the flip
  side of the scheme: a database that already recorded `0002` never sees a later regeneration of
  it, so model changes reach an existing instance only through the `MIGRATE` rebuild.
  See `migration.md`.
- **A version tag needs its `CHANGELOG.md` section.** The tag is the release: the bare
  repository's `update` hook (`update.sh`) refuses `v<x.y.z>` whose commit carries no filled
  `## v<x.y.z>` section, so `post-receive` never builds an undocumented delivery. Only the tag is
  refused — `master` lands either way. Collect under `## Unveröffentlicht` and rename that heading
  at release time; a pre-release (`v1.0.0-rc2`) may lean on that section or on the one of its final
  version, a final version may not. `ChangelogTest` guards the format the hook parses, the release
  steps and the escape hatch are in `README.md`.
- **All tests are `SimpleTestCase`.** A `TestCase` makes Django build a test database, which runs
  the data migration `0003_import`, which needs the legacy MySQL server. Keep logic free of DB
  access and isolate the DB half in a thin wrapper so it stays testable (`lese_abmelde_token()`
  vs. `read_abmelde_token()` is the pattern).
- **`USE_TZ = False`.** Every datetime is naive local wall-clock time. Never call `localtime()`,
  and pass "now" in as an argument rather than reading the clock inside logic you want to test.
  The wall-clock zone is the `ZEITZONE` `Konfiguration` key (default `Europe/Berlin`), synced
  into `settings.TIME_ZONE` **and into the process** (`os.environ["TZ"]` + `time.tzset()`) at app
  start; `intern.caldav.daten.zeitzone()` reads it live for the iCal/CalDAV UTC conversion.
  Setting `settings.TIME_ZONE` alone would only reach Django's formatting, not `datetime.now()`.
  This also means the runtime image depends on the **system** `tzdata` package: without
  `/usr/share/zoneinfo`, `tzset()` falls back to UTC without a word and every displayed time is
  off. The base image happens to ship it, but the `Dockerfile` installs it explicitly because
  the failure would be silent. The `tzdata` line in `requirements.txt` is the *Python* package
  and serves `zoneinfo` only — it does not help `tzset()`.
- **The image needs the `de_DE.UTF-8` locale.** `replacements.format_datetime` prints month
  names through `%B` and sets `LC_TIME` for it; if that fails it swallows the error and returns
  English names. Debian's `locale-gen` only reads `/etc/locale.gen` and ignores its argument, so
  the locale has to be written into that file before generating. `MonatsnamenTest` guards it.
- **Changing data lives under `CANTORHUB_DATA`, never next to the code.** `MEDIA_ROOT`, the
  nginx tile cache, the generated secret key and a possible SQLite file all sit there (`/data`
  in the image, a volume; the project directory in development). The code is part of the image
  and read-only in spirit — `STATIC_ROOT` is the exception, because `collectstatic` runs at
  build time and its output is a build artefact.
- **Bootstrap settings come from at most one environment variable each**, parsed in
  `config/datenbank.py` (`DATABASE_URL`, and `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` derived from
  `VEREINS_URL`) and `config/geheimnis.py` (the secret key file). Both modules are free of
  Django imports so that `settings.py` can load them early and `SimpleTestCase` can check them.
  **`settings.py` must never touch the database at import time** — that is what would break the
  whole test suite.
- **Runtime settings come from the `Konfiguration` table**, read through `intern.app_settings`
  helpers — never `os.environ` or `settings` for these, and never at import time. Inside a
  request the helpers share one cached read of the whole table; outside one (management
  commands, the two endless loops) every call still hits the DB —
  `konfiguration_gepuffert()` opens the cache for one bulk-mail pass, never around an endless
  loop. See `docs/architecture.md`. A new key needs
  three edits: `_CONFIG_DEFAULTS` in `apps.py`, a group in `konfig_gruppen.py`, and a `FELDTYPEN`
  entry. `KonfigGruppenTest` and `KonfigTypenTest` enforce the last two. A `select`-typed key
  additionally needs an entry in `SELECT_OPTIONEN` (same file). **A new key counts as required**
  — the settings page's banner reports it while blank; if blank is a legitimate state for it, add
  it to `OPTIONAL_LEER` with the reason. See „Completeness" in `docs/configuration.md`.
- **A file's identity is its storage path**, not its row: several `filer.File` rows may share one
  blob. Use the helpers in `views/files.py` instead of touching `File.file`/`name`. Never run
  `filer_check --delete-orphans` — it would delete the whole version history.
- **Every write path on a file must call `darf_avatar_aendern()`**, or one member can overwrite
  another's profile picture.
- **A folder without `FolderPermission` rows is open.** Code that creates a folder must set rows
  explicitly.
- **Forum messages are ordered by `id`, not `datum`.** The read marker (`ForumGelesen.bis_id`),
  the „Neu seit Deinem letzten Besuch" divider, the 5 s poll (`id__gt`) and the paging
  (`id__lt`) all speak ids, so the display must too. `datum` has second resolution and no
  tiebreaker: a tie put the divider inside the tied group, one off the badge. See „Order" in
  `docs/forum.md`; `ForumGelesenTest` pins `Mitteilung.Meta.ordering`.
- **Mail bodies live entirely in `MAIL_*` config keys**, never in templates. Subjects stay in
  Python.
- **DAV: bump `_SERIALISIERUNG`** in `carddav/vcard.py` / `caldav/ical.py` on every change to the
  serialisation, or synced clients keep their stale entries forever.
- **Hidden member fields have no admin bonus outside the portal.** `User.field_visible_to()` lets
  holders of `intern.change_user` see hidden fields *in the portal*; the CardDAV cards, the CalDAV
  birthdays and the calendar birthday chips consult `private_fields` alone. **Every CardDAV member
  selection goes through `carddav.daten.mitglieder_qs()`** — which is why the whole-record opt-out
  (`adressbuch_verborgen`) needs a single filter and reaches collection, single card and CTag at
  once.
- **CSS uses tokens only.** Every new colour is a custom property with a `[data-theme="dark"]`
  value; no hardcoded hex in component styles.
- **Font sizes in `rem`, never `px`** — write `calc(13rem / 14)` for 13px, also in template
  `<style>` blocks (mail templates excepted). The sidebar font-size setting scales the root; a
  `px` size silently ignores it. See „Theme boot" in `docs/frontend.md`.
- **No `sourceMappingURL` without the `.map` next to it.** `ManifestStaticFilesStorage`
  rewrites every reference inside a static file and raises on a missing target; with `set -e`
  in `start.sh` that kills the container before gunicorn starts. Vendor bundles either bring
  their `.map` along or lose the line. `StatikQuellkartenTest` enforces it.
- **Tables: no `TemplateColumn` on a hot list.** It renders every cell with `request=`, which
  runs the context processors again per row, and `DateTimeColumn`/`DateColumn` are subclasses
  of it that compile a `Template` per cell. Use a `render_` method, and `DatumZeitSpalte` /
  `DatumSpalte` from `tables.py` for dates — same output, no template.
- **Template comments over more than one line use `{% comment %}`.** `{# … #}` ends at the
  end of its line; written across several lines Django prints the text instead. In `<head>`
  that closes the head early and the page falls apart. `VorlagenKommentarTest` enforces it.
- **Reuse the shared UI components** rather than hand-rolling: `{% form_field %}` for form rows,
  `ChipMultiSelect` / `_chip_multiselect.html` for every multi-select,
  `_confirm_delete_dialog.html` for delete confirmations, `{% hilfe %}` for explanation tooltips
  (the text lives as the model field's `help_text`), `_leaflet_map.html` for detail-page maps.
- **One hasher per algorithm in `PASSWORD_HASHERS`.** `intern.hashers.PortalPBKDF2Hasher` writes
  new passwords and keeps the `pbkdf2_sha256` algorithm name, so Django's built-in
  `PBKDF2PasswordHasher` must *not* be listed next to it: `get_hashers_by_algorithm()` keys by
  `algorithm` and the last entry wins, so the built-in would answer every verification and its
  `must_update()` would re-hash each password back to Django's 1,200,000 iterations.
- **Redirect targets taken from a `next` parameter must pass
  `url_has_allowed_host_and_scheme()`.**

## Conventions

- New domain code is written with German identifiers, in line with the models; older modules are
  mixed. Follow the file you are in.
- Views are function-based; the few class-based ones are Django's own auth views, subclassed in
  `views/auth.py`.
- Partial updates use htmx with a dedicated partial template; everything else is a full render.
  JavaScript is vanilla, one file per concern, loaded in `base.html`.
- Logging: `logging.getLogger(__name__)`; everything under `intern.*` is at INFO and goes to
  stdout.
- References to the privacy policy — in code comments, `Konfiguration` help texts, `docs/` —
  name the German section heading of `datenschutz.html` („Speicherdauer", „Sichtbarkeit Deiner
  Daten im Portal"), never the section number. Every `<h2>`/`<h3>` there carries a stable
  `ds-*` id and the policy's own cross-links are anchors, so renumbering breaks nothing.

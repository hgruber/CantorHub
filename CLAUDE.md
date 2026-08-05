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
docker build -t cantoreub . && docker run -p 8000:8000 cantoreub
```

The management commands an operator runs (reminders, re-confirmation mails, cleanup jobs,
ejabberd admin) are listed in `README.md`. `./migrate.sh` wipes the database and belongs to the
migration — see `migration.md`.

## Where things are documented

| Topic | File |
|---|---|
| Request flow, proxy assumptions, URLs, logging, cache, runtime config | `docs/architecture.md` |
| Files: identity, versions, avatar protection, folder rights, retention | `docs/files.md` |
| Frontend: pages, components, design tokens, calendar, maps, homepage | `docs/frontend.md` |
| Automated e-mails and their markup | `docs/mail.md` |
| Members: joining, re-confirmation, leaving, field privacy | `docs/members.md` |
| Forums: read permissions and reactions | `docs/forum.md` |
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
  entry. It includes `login_required`.
- **`views/_auswahl.py`** — `chip_eintraege()` builds the entry list `_chip_multiselect.html`
  expects, for the pages that have no Django form.

Cross-cutting modules: `models.py`, `forms.py`, `signals.py` (audit log, activation mails, filer
indexing, MUC room assignment), `app_settings.py` (runtime config), `folder_access.py` /
`avatar_access.py` (the two file access axes), `verwendung.py` (what a delete would break),
`mail.py` / `mail_markup.py`, `mailingliste.py`, `replacements.py` (wiki markup), `pdf.py`,
`ejabberd.py`, `konfig_gruppen.py`. `intern/dav/` is shared by `intern/carddav/` and
`intern/caldav/`.

## Key models (`intern/models.py`)

| Model | Purpose |
|---|---|
| `User` | Extended `AbstractUser` — voice type, address, XMPP JID, coordinates, `private_fields`, `adressbuch_verborgen`, nullable `date_joined` (see `docs/members.md`) |
| `Artikel` | Versioned wiki articles, immutable per `(name, version)` |
| `ArtikelPermission` | Per-article read/edit restriction by group |
| `Forum` / `ForumPermission` | Discussion threads, optionally bridged to an XMPP MUC room; read restriction by group |
| `Mitteilung` / `Reaktion` | Forum messages and their emoji reactions (XEP-0444) |
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
  See `migration.md`.
- **All tests are `SimpleTestCase`.** A `TestCase` makes Django build a test database, which runs
  the data migration `0003_import`, which needs the legacy MySQL server. Keep logic free of DB
  access and isolate the DB half in a thin wrapper so it stays testable (`lese_abmelde_token()`
  vs. `read_abmelde_token()` is the pattern).
- **`USE_TZ = False`.** Every datetime is naive local wall-clock time. Never call `localtime()`,
  and pass "now" in as an argument rather than reading the clock inside logic you want to test.
  The wall-clock zone is the `ZEITZONE` `Konfiguration` key (default `Europe/Berlin`), synced
  into `settings.TIME_ZONE` at app start; `intern.caldav.daten.zeitzone()` reads it live for the
  iCal/CalDAV UTC conversion.
- **Runtime settings come from the `Konfiguration` table**, read through `intern.app_settings`
  helpers — never `os.environ` or `settings` for these, and never at import time. A new key needs
  three edits: `_CONFIG_DEFAULTS` in `apps.py`, a group in `konfig_gruppen.py`, and a `FELDTYPEN`
  entry. `KonfigGruppenTest` and `KonfigTypenTest` enforce the last two. A `select`-typed key
  additionally needs an entry in `SELECT_OPTIONEN` (same file).
- **A file's identity is its storage path**, not its row: several `filer.File` rows may share one
  blob. Use the helpers in `views/files.py` instead of touching `File.file`/`name`. Never run
  `filer_check --delete-orphans` — it would delete the whole version history.
- **Every write path on a file must call `darf_avatar_aendern()`**, or one member can overwrite
  another's profile picture.
- **A folder without `FolderPermission` rows is open.** Code that creates a folder must set rows
  explicitly.
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
- **Reuse the shared UI components** rather than hand-rolling: `{% form_field %}` for form rows,
  `ChipMultiSelect` / `_chip_multiselect.html` for every multi-select,
  `_confirm_delete_dialog.html` for delete confirmations, `{% hilfe %}` for explanation tooltips
  (the text lives as the model field's `help_text`), `_leaflet_map.html` for detail-page maps.
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

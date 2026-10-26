# Known technical debt

Items found during code review, ordered by estimated risk of the fix. Privacy-policy
compliance items are tracked separately in `datenschutz.md`.

## Branding

- **What is left of the branding extraction** — dynamic homepage content (placeholders,
  sub-pages, public wiki articles), the internal `jg` identifiers for the own recording and the
  `!` of the wiki footer. All three under „Left to do" in `branding.md`.
- **Config key naming is mixed** — existing `Konfiguration` keys mix German and
  English (`CALDAV_TAGE_RUECKWIRKEND` vs. `PWRESET_MAX_PER_HOUR`, `UPLOAD_MAX_MB`,
  `NOTIFY_POLL_MS`, `MAP_DEFAULT_ZOOM`). Renaming the existing keys would touch
  stored values in the `Konfiguration` table and every read site, so it is
  deferred. Keys introduced since follow the convention: German for
  Verein/datenschutz terms (`AENDERUNGSPROTOKOLL_AUFBEWAHRUNG_TAGE`,
  `HOSTING_ANBIETER_NAME`), English for purely technical admin values
  (`EJABBERD_API_TIMEOUT`, `OSM_TILE_URL`).

## Configuration structure (low risk) — measured September 2026

The `Konfiguration` catalog itself is in good shape: 91 keys, 11 groups plus the rest group,
no duplicates, and **no undeclared key** — every key the code reads through `get_config*` with a
literal name is in `_CONFIG_DEFAULTS`. That is not discipline but a forcing function: adding a key
to `apps.py` alone fails exactly four tests — verified by doing it —
`KonfigGruppenTest.test_jeder_default_schluessel_hat_eine_gruppe`,
`.test_reihenfolge_ist_vollstaendig`, `.test_gruppiere_invarianten` and
`KonfigTypenTest.test_jeder_default_schluessel_hat_einen_typ`. The items below are the places where
that mechanism does *not* reach. All four fixes are mechanical; none changes behaviour. Related:
„Config key naming is mixed" above.

- **`apps.py` is 72 % data.** 547 of 755 lines are `_CONFIG_DEFAULTS` (502) and
  `_LEGACY_MAIL_DEFAULTS` (45); `InternConfig` itself starts at line 686. Whoever opens the file to
  see what happens at startup scrolls past 500 lines of mail texts first. Moving the catalog to its
  own Django-free module (`intern/konfig_katalog.py`) would also remove a redundancy: the key list
  exists twice today — as `_CONFIG_DEFAULTS` and as `SCHLUESSEL_REIHENFOLGE` in
  `konfig_gruppen.py` — because that module must stay importable without Django for
  `SimpleTestCase`. With the catalog in a Django-free module both could import it, and
  `test_reihenfolge_ist_vollstaendig` would become unnecessary.
- **Four keys are invisible to `grep`.** `intern/dav/auth.py:163,178` composes names at runtime —
  `get_config_int(f"{dienst.prefix}_AUTH_TTL")` and `get_config_bool(f"{dienst.prefix}_AKTIV")` —
  so `CARDDAV_AUTH_TTL`, `CALDAV_AUTH_TTL` and the two `_MAX_FEHLVERSUCHE_PRO_STUNDE` never appear
  as a literal anywhere outside the catalog. Rename one and nothing fails: the service silently
  falls back to the default. A test that crosses the prefixes with the suffixes and checks the
  result against the catalog closes this. Same pattern, but harmless because it is a scan rather
  than a lookup: `verwendung.py:107` selects on `key__endswith="_FILE_ID"`.
- **`docs/configuration.md` is guarded by nothing.** The catalog can drift from the reference
  without a test noticing — the one place in this area where pure discipline carries the load.
  Today the five `EMAIL_*` keys are only covered collectively („the `EMAIL_*` set"), which is
  defensible; a test should therefore allow a family form alongside individual mentions.
- **`_LEGACY_MAIL_DEFAULTS` has no expiry.** 45 lines of superseded mail texts so that an upgrade
  lifts never-edited values to the current default (`apps.py:520-564`). Correct as built, but
  untested and without a rule for when it goes away. Lists like this grow. Cheapest fix is a
  version in the comment rather than a removal now.

Not a defect, but worth knowing: `get_config` consults `os.environ` **at runtime** before the
table, so an environment variable set after startup wins over any stored value — and the settings
page shows no sign of it. `_seed_config` does write env values into the table at startup, so the
usual deployment case is visible; only a later change is not.

## One name per folder: what the rule does not reach yet (October 2026)

Since `intern/dateiablage.py` (see „One name per folder" in `files.md`) no portal path can put
a second file or subfolder of the same name into a folder. Left open on purpose:

- **Existing duplicates are not cleaned up.** Files and folders that already share a name in a
  folder stay as they are. A command would merge each group with the same rule as
  `zusammenfuehren`: the youngest revision in front, equal content kept once, the PK
  references of the dropped rows moved over (`verweise_umhaengen`). Duplicate folders need a
  human decision, because their `FolderPermission` rows can differ — the command should list
  them rather than merge.
- **`/admin/filer/` bypasses the rule.** filer's own admin creates and moves rows without
  `dateiablage`. A model-level guard (`pre_save` on `filer.File`/`Folder`) would close it, but
  it would also fire inside `zusammenfuehren`'s own updates and in migrations.
- **Identical revisions already in a chain are not cleaned up.** Since the ordering rule (the
  youngest in front, of identical revisions the oldest) a merge never adds a duplicate, but a
  chain that held one before keeps it. The migrated legacy data should not have any; should it
  turn up, `cleanup_dateiversionen` could run `dateiablage.kette_bilden(kette, [])` per chain
  (computing missing SHA-1 from the blob first) and write the result through the same path as
  `zusammenfuehren`.
- **`DateiVersion.original_filename` is written but no longer read.** Revisions have no name
  of their own since `datei_restore` stopped renaming. The column can go in a migration,
  together with the writes in `dateiablage.zusammenfuehren`.

## Data model (audited September 2026)

The model is in good shape and needs no rework. 23 models, 956 lines in
`intern/models.py`, 146 fields, no model outside that file, no abstract/proxy/unmanaged
model, and `on_delete` is disciplined (19× `CASCADE`, 11× `SET_NULL`, no `PROTECT`).
Decisive: **no denormalised counters** — no signal maintains a running total; the unread
count and the forum figures are annotations (`ForumQuerySet.mit_ungelesen`,
`extra_data`). `Auftrittsabo` and `Reaktion` avoid redundancy explicitly and say why in
their docstrings, and `ErinnerungVersand` uses a DB constraint as the only guard against
double sending.

What was missing was not normalisation but **enforcement**, at one place and in one
mechanism:

- **`Zusage` had no unique constraint on `(person, termin)`** — fixed (`Meta.constraints`,
  plus `choices` on `option`). Five call sites in `views/termine.py` worked around the gap
  with `order_by("-id").first()`, two `update_or_create` calls would have raised
  `MultipleObjectsReturned` on a duplicate, and an on-screen count was inflated by them.
  `config/context_processors.py` guarded the same way. The constraint is a **no-op on the
  existing data** (2873 rows, 0 duplicate groups; verified read-only before it was added).
- **`Zusage.option` is now a `choices` field** — pure Python validation, no migration
  needed. The earlier entry here suggesting "a choices field with a migration" was wrong:
  `choices` is schema-free.
- **`Mitteilung.formatiert()` tolerates missing text now.** The column keeps `null=True`
  (legacy data, XMPP-relayed messages) and the method treats it as the empty string —
  `apply_replacements()` would crash on `None`. Making the column `NOT NULL` would be the
  cleaner cut, but it makes `makemigrations` ask a question interactively, and the
  `makemigrations` call in the `Dockerfile` and `start.sh` runs without stdin: the build
  would fail. **Any nullable → non-nullable model change has this trap** — it needs
  `--no-input` (or an explicit default) in both scripts, which is why `null=True` stays here.
- **`Abstimmung` got `UniqueConstraint(person, abstimmung, option)`** and an index on
  `(abstimmung, person)`. Deliberately a triple: the poll is multi-select (`max_stimmen`),
  so `unique(person, abstimmung)` would be wrong; only the same *single* vote twice is
  forbidden. It can occur because voting is `delete()` + `bulk_create()` and not atomic.
- **`Konzert.lied` is `SET_NULL` now** instead of `CASCADE` — the only nullable FK paired
  with `CASCADE` in the project. `on_delete` produces no DDL, so this took effect without
  a rebuild.
- **Index hygiene**: `db_index=True` next to `unique=True`
  (`Mitteilung.xmpp_stanza_id`) and on a FK (`Reaktion.mitteilung`) were **no-ops** — only
  one index ever existed; removed so nobody "fixes" a non-problem. `ChangeLog` had a
  genuinely duplicated index on `user` (FK index + explicit) and none on `timestamp`,
  although the list is ordered by it; swapped. `Termin.datum` gained an index — every list,
  calendar, CalDAV and reminder query filters or sorts by it.
- **Dead code removed**: `Lied.find_similar_titles`/`get_similar_titles`,
  `Lied.datei_referenzen`, `Artikel.datei_referenzen`/`aktuelle_datei_referenzen`,
  `fallback_avatar_url` — none had a caller. `intern/fuzzy.py` is gone with them: it was
  imported nowhere, and its only dependency (`rapidfuzz`) was never in `requirements.txt`,
  so it could not have been imported anyway.
- **The hand-maintained field maps are now checked against `_meta`**
  (`RegisterKonsistenzTest`). That is the real repair of this area: field names in
  `_AUDIT_FIELDS`, `FIELD_LABELS`, `_CHANGELOG_FIELD_LABELS`, `_LIED_FELDER`,
  `_FILE_ID_FIELDS` are **strings**, so renaming a field without touching the map makes the
  audit log go quiet with nothing turning red. The test also reads the **source** with
  `ast` to find duplicate dict keys — a repeated key in a literal silently drops the
  earlier one, which is how `FIELD_LABELS["gruppe"]` lost the notification page's
  "Signatur" label to the Group page's "Gruppe". That is fixed with a model-specific
  `_MODELL_FELD_LABELS` consulted first. `_AUDIT_FIELDS` also has **coverage gaps**
  (`Termin.wiederholung`/`ctag`, `Lied.bearbeiter`, five `User` fields) — the test
  does not require completeness, only that nothing named there has vanished.
- **`TabellenPreferenzen`**: `person=None` is the global default row, and a
  `unique_together` does **not** cover it — NULLs count as distinct in a unique index, and
  Django can only change that on PostgreSQL (`UniqueConstraint(nulls_distinct=False)`
  raises elsewhere). So the model keeps the constraint for member rows, and
  `views/files.py` reads with `first()` instead of `get()`.
- The **three permission models stay as they are.** Their rules differ on purpose:
  articles are an axis opt-out ("no row with `can_read=True` ⇒ open again"), folders a row
  opt-in, forums a presence block with no axis at all. Unifying them would be a schema *and*
  data change across three models for no functional gain (0/1/0 rows in the live database).
  The shared "no rows = open" rule is documented, not unified. Note the three resolvers
  (`_artikel_access`, `folder_access`, `_forum_access`) are DB-touching and therefore
  untestable as `SimpleTestCase` — extracting their pure half is its own piece of work.

Deliberately **not** done, so the next audit does not raise it again:

- **The two dead `Termin` columns stay** (`wiederholung`, `ctag`). They are written only by
  `0003_import.py` and read nowhere — but they **carry data**: 179 rows with `ctag <> 0`, 9 with
  `wiederholung ≠ 'e'`. Dropping them would be a deliberate, unrecoverable data loss for no gain.
  `wiederholung` is also declared `CharField(max_length=1)` while the CalDAV serialisation ignores
  it on purpose.
- **`Termin.extern` is not one of them any more.** The column was revived in 2026: it holds the
  public announcement text, decides which events `home()` lists (`intern/views/auth.py`; the
  imported data has 74 filled, 248 `''` and 27 `NULL`, and `exclude(extern="")` alone would keep the
  `NULL` rows) and fills the card „Extern" on the Terminseite. It is also the project's **only
  public HTML output from the database** — `extern_html` in `intern/templatetags/termin_tags.py`
  strips `style` attributes and rewrites `<h1>`–`<h3>` to `<strong>`, but it is deliberately **not
  a sanitizer** and must not be read as one. Trust boundary: only holders of `intern.change_termin`
  (and the admin) can write the field, and there is neither a CSP nor an allowlist library in the
  project — should the field ever be opened to another circle, an allowlist (`nh3`) has to come
  first.
- **`User.notify_enabled` is dead and stays for now.** The sidebar switch for the
  notification bubbles was removed in October 2026 — every member gets them. The column is
  read and written nowhere any more; only its label in `views/aenderungen.py` remains, so old
  audit entries still read well. Backlog: drop the field in a migration, together with
  that label.
- **No field renames.** The member FK is called `autor`, `sender`, `person`, `mitglied` or
  `user` depending on the model, and timestamps are `datum`, `*_am`, `timestamp`,
  `indexed_at` or `aktualisiert`. The gain would be purely cosmetic; the risk is high and
  partly invisible (`ChangeLog.model_name` is a **persisted string**, `_AUDIT_FIELDS` is
  string-keyed, `mitglied.html` uses reverse accessors like `user.dirigent.all`). The
  glossary in `CLAUDE.md` solves the actual problem — confusion — at a fraction of the risk.
- **No `UniqueConstraint(termin, position)` on `Konzert`.** The imported data contains
  three duplicate groups (Termin 20 has 18 songs on position 0 — the legacy "order not yet
  sorted" state), so the constraint would break the import and outlaw a tolerated interim
  state.
- **No `Termin.Meta.ordering`** — it would silently reorder every unordered query,
  including the basis for `paginate_ordered`. `.order_by()` already stands where it matters.
- **No `updated`/`geaendert` field** on the models. `ChangeLog` already answers "who changed
  what when", and `cleanup_changelog` hangs its retention off that.
- `ArtikelPermission.artikel_name` as a string instead of an FK: the clean fix needs an
  `Artikel` parent row, and articles are versioned by `(name, version)`.
- **The four legacy Repertoire subfolders** (`Hörbeispiele`, `Notenblätter`, `Notensatz-Dateien`,
  `Probenmitschnitte`) sit next to the per-song folders after `repertoire_umziehen`; they are
  empty except for files kept for wiki links. Deleting them is an operator decision, not a
  migration.

Until October 2026 model changes reached a database only through the `MIGRATE=1` rebuild,
which is why everything above that touches the schema was done before the cutover. Since
then the migration chain is checked in (`0002` frozen, new changes from `0004` on), so a
schema change is an ordinary migration again.

## Query counts (low risk) — measured, left alone on purpose

N+1 hotspots were swept in September 2026; the four with measurable weight were fixed (see
`docs/architecture.md` on the per-request config cache, plus `select_related` in the repertoire,
forum and groups views). These were found and deliberately left as they are — each is a one-liner,
but the measured effect on this data set does not justify touching the code:

- **CalDAV `einzeln()`** (`intern/caldav/daten.py:160`) serialises the whole collection for every
  single-resource GET — quadratic if a client syncs item by item. Its docstring argues the case:
  a targeted lookup would have to duplicate the time-window and visibility rules, and the ETag
  must match the one from the collection listing. CardDAV does do a targeted lookup
  (`intern/carddav/views.py:303`). Revisit if `CALDAV_AKTIV` is ever switched on and a real client
  turns out to fetch single resources individually.
- **Recursive folder sizes** (`intern/views/folders.py:605-612`) — two queries per subfolder, plus
  one per tree level inside `_descendant_folder_ids`. Measured on the live data: 13 folders,
  maximum depth 1, at most 4 subfolders per level. Would matter with a deep tree, does not here.
- **`select_related("avatar")`** missing in the member list (`intern/views/mitglieder.py:48`) — the
  avatar column is off by default and there are ≤30 members.
- **`select_related("autor")`** missing for `DateiVersion` on the file detail page
  (`intern/views/files.py:528`) — a handful of revisions per file.
- **One `.get()` per entry** in the notification poll (`intern/views/notify.py:106`) — capped at 30
  and usually zero, because the poll normally returns an empty set. The batching pattern is right
  above it at line 76.
- **`get_config` inside loops** in `intern/ejabberd.py:581,696` — both in admin-command paths where
  the per-request cache does not apply, but the loops run over forums/users (single digits).

## Medium risk (15-30%) — need testing after fixing

- **No DB-backed tests yet.** Any `TestCase` used to replay the data migration `0003_import` against the legacy MySQL server, so everything worth testing was written free of DB access (see `intern/tests.py`). Since October 2026 `0003_import` is empty and a test database builds without that environment; the `SimpleTestCase`-only rule in `CLAUDE.md` stands until it is lifted deliberately.
- `intern.js` (about 2,400 lines) puts most JS in one file with global namespace pollution (`appMainDz`, `toggle()`, `fileAction()`, `saveOrder()`). Should be split into modules.
- Dropzone and Sortable are loaded unconditionally in `base.html` on every page (Leaflet and `osm-map.js` already load only where a map is shown, `_leaflet_assets.html`). Should be page-specific `<script>` loads.
- Inline `<script>` blocks in 6 templates (`karte.html`, `termin.html`, `termin_edit.html`, `mitglied.html`, `artikel_history.html`, `ort_detail.html`) should be extracted to separate JS files. The shared OSM tile-referer patch has already been pulled out into `osm-map.js`; the map-init scripts themselves remain inline.
- Inline `style=` attributes in templates bypass the design system and lack dark mode support.

## Higher risk (35-55%) — need careful planning

- Many hardcoded hex colors in `intern.css` (attendance badges, diff views, wiki code block, toasts) lack CSS variables and some lack dark-mode overrides. The version banner now uses `--warn-*` tokens with dark-mode values.
- `alert()`/`confirm()` in `intern.js` for UX feedback should be replaced with toast/modal components, but `confirm()` gates destructive actions so control flow changes.
- `visible_fields()` in `views/files.py` has dual behavior: returns column list on GET, saves and redirects on POST. Splitting it requires touching call sites in `titel.py` and `mitglieder.py`.
- URL parameter naming is inconsistent across views (`id` vs `pk` vs `forum` vs `titel`). Standardizing requires updating URL patterns, view signatures, templates, and `reverse()` calls.

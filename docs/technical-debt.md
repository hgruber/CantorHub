# Known technical debt

Items found during code review, ordered by estimated risk of the fix. Privacy-policy
compliance items are tracked separately in `datenschutz.md`.

## Branding

- **Branding is hardcoded** ("Just Gospel Frankfurt", logos, domain) across
  templates, `replacements.py`, `tables.py`, and static SVGs. Blocks open-sourcing
  as a white-label app. Full extraction plan in `branding.md`.
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

- **No DB-backed tests are possible.** Any `TestCase` (as opposed to `SimpleTestCase`) makes Django create a test database, which replays the data migration `0003_import` — it connects to the legacy MySQL server and expects the filer files imported by `import_files`. Wherever that environment is missing, test-DB setup dies with `File.DoesNotExist` before a single test runs. Consequence: everything worth testing has to be written free of DB access (see `intern/tests.py`). The fix is to make `0003_import` a no-op when the legacy DB is unreachable — it already probes the connection, it just does not tolerate the absence.
- `Zusage.option` is `CharField(max_length=255)` but only uses `"1"`, `"2"`, `"3"`, `""`. Should be a choices field with a migration.
- `Mitteilung.mitteilung` allows `null=True` but `formatiert()` calls `apply_replacements()` which may crash on `None`. Guard the method or remove `null=True`.
- `intern.js` (1022 lines) puts all JS in one file with global namespace pollution (`appMainDz`, `toggle()`, `fileAction()`, `saveOrder()`). Should be split into modules.
- Dropzone, Sortable, Leaflet, and `osm-map.js` are loaded unconditionally in `base.html` on every page. Should be page-specific `<script>` loads.
- `sortablejs@latest` in `base.html` is unpinned — a breaking upstream update could break the app.
- Inline `<script>` blocks in 6 templates (`karte.html`, `termin.html`, `termin_edit.html`, `mitglied.html`, `artikel_history.html`, `ort_detail.html`) should be extracted to separate JS files. The shared OSM tile-referer patch has already been pulled out into `osm-map.js`; the map-init scripts themselves remain inline.
- Inline `style=` attributes in templates bypass the design system and lack dark mode support.

## Higher risk (35-55%) — need careful planning

- Many hardcoded hex colors in `intern.css` (attendance badges, diff views, wiki code block, toasts) lack CSS variables and some lack dark-mode overrides. The version banner now uses `--warn-*` tokens with dark-mode values.
- `main.css` (public homepage) defines `.content` with different properties than `intern.css` — potential clash if both load on the same page.
- `alert()`/`confirm()` in `intern.js` for UX feedback should be replaced with toast/modal components, but `confirm()` gates destructive actions so control flow changes.
- `visible_fields()` in `views/files.py` has dual behavior: returns column list on GET, saves and redirects on POST. Splitting it requires touching call sites in `titel.py` and `mitglieder.py`.
- URL parameter naming is inconsistent across views (`id` vs `pk` vs `forum` vs `titel`). Standardizing requires updating URL patterns, view signatures, templates, and `reverse()` calls.

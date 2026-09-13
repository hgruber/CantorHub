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

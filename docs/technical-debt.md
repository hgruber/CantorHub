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

# Articles: versioning, editor, permissions, markup

## Immutable versions

`Artikel` rows are immutable versions keyed by `(name, version)` — articles are addressed by
`name`, not `id`. Saving an edit at `/intern/artikel/<name>/edit/` creates a new `Artikel` row
with `version + 1` rather than mutating the existing one. Anything that rewrites article text
programmatically has to follow the same path — `_wiki_links_umschreiben` (see `files.md`) writes
a new version per affected article instead of updating in place.

`article_view` shows the latest version by default, or a specific one via `?version=<n>`. When
viewing an outdated version it renders the `.version-banner` — a warning plus a version stepper
with previous/next links (`prev_version` / `next_version`, computed via DB queries so gaps in
the version sequence are skipped) and an "Aktuelle Version" button. History and
unified/side-by-side diffs live at `/intern/artikel/<name>/history/` and `/diff/`.

## Editor

The editor (`artikel.html`, edit branch) renders the `.article-editor` shell: an identity bar, a
collapsible `.ae-help` syntax cheat-sheet, the textarea inside a `.wiki` container (kept so
`abstimmung.js`'s `{abstimmung:...}` helper still binds), and a footer action bar.

Every `.ae-cheat` in that cheat-sheet is a `<button type="button">` carrying its own snippet in
`data-einfuegen`, so the markup lives in exactly one place; `wiki-einfuegen.js` inserts it at the
caret and selects the `${…}` placeholder. `data-block` puts the snippet on its own line,
`data-umschliessen` wraps the selection instead of replacing it (bold, italic, internal link), and
the two file pills insert `[[Datei:` alone so the existing file search in `intern.js` supplies the
name — the media-player pill adds `data-suffix="|Titel"`, which `completeItem()` consumes once to
close the reference as `[[Datei:<name>|Titel]]`. The poll pill asks `abstimmung.js` for its
scaffold (`window.abstimmungGeruest`) so the two-week end date is computed in one place.

New articles are created from the `+` in the article-list topbar (`article_list` sets
`add`/`add_panel_include`). It opens the off-canvas panel `templates/artikel_add_panel.html`,
which has **no** server form — a small vanilla script reads the entered page name and navigates
client-side to `/intern/artikel/<name>/edit/` (built from the panel's `data-edit-url`
`__NAME__` placeholder + `encodeURIComponent`), where the first save creates version 1. Shown to
every logged-in member, matching the open-wiki default: `article_edit` has no permission check
for a name that does not exist yet.

## Permissions

`ArtikelPermission(artikel_name, group, can_read, can_edit)` — unlike the forum's read-only
model, articles have two independent axes, and each is **restrictive only when at least one row
claims it**. `_artikel_access(user, artikel_name)` in `views/artikel.py` returns
`(can_read, can_edit)`:

- no rows for that name at all → `(True, True)`, the open-wiki default;
- no row with `can_read=True` → reading stays open to everyone, even if edit rows exist;
- no row with `can_edit=True` → editing stays open to everyone;
- otherwise the user must be in a group carrying the respective flag.

Holders of `intern.manage_artikel_permissions` bypass the read restriction, and the article list
filters restricted names out for everyone else. Because permissions hang off `artikel_name`, they
survive every new version automatically.

## Files in an article

Uploads on an article page go through the shared `#app-main` dropzone into „Wiki-Anhänge“.
`/upload/` answers with the stored `name`, the name a `[[Datei:…]]` resolves by.

- **View** — `article_view` only sets `upload_folder_id` / `upload_artikel` with edit right and
  on the latest version; otherwise `intern.js` disables the dropzone. After the queue
  completes, *all* uploaded names go in one POST to `article_dateien_einfuegen`, which prepends
  them (`dateien_voranstellen`) as a single new version — one request per file would race for
  the same version number.
- **Editor** — each upload prepends `[[Datei:<name>]]` to the textarea; nothing is saved.

A thumbnail figure carries `data-datei-id` (the row the link resolved to) and `data-datei-name`.
In the view, `wiki-dateimenue.js` turns a click on it into a context menu: download and show for
everyone; with edit right it asks `datei_aktionen` (`/intern/datei/<pk>/aktionen/`) for the
folder, the writable folders not holding the file yet and the delete right. „Enthaltenen Ordner
anzeigen“ opens `folder_view?datei=<pk>`, which stretches the first page to that row; the
parameter is never remembered by `tabellenzustand`. „Referenz erzeugen“ posts to `folder_link`
with a checked `next`. „Datei löschen“ (`article_datei_loeschen`) deletes **this occurrence
only**, same rights as `folder_delete`, and removes the reference in a new version
(`datei_verweis_entfernen`).

## Wiki markup

`intern/replacements.py` renders the article body: headings, `'''bold'''` / `''italic''`, lists,
code blocks, indentation, notes, external links, and `[[Datei:name.pdf]]` file links resolved
against filer by **name**. `internal_links` must use `filter().first()`, not `get()` — a file
linked into several folders has several rows (see `files.md`).

### Embedded media

A `[[Datei:…]]` whose target `intern/medientypen.py` calls playable renders as a **media bar**
instead of a link: the same `.mp-*` markup the floating mini-player uses, inline in the text.
`|Label` overrides the title, which otherwise is the filename without its extension. Video gets a
`<video>` without `controls` — the bar *is* the controls. Everything else keeps the old
`<figure class="wiki-figure">`.

Two constraints on `_medienleiste()` come from `apply_replacements()` and are easy to break:

- The bar must be **phrasing content on a single line**. The `<p>` rule runs over the same line
  *after* this substitution, so a `<div>` would tear the paragraph open. It costs nothing
  visually, because every `.mp-*` rule sets its own `display`.
- The `''italic''`, `""quote""` and `$raw$` rules run afterwards too. So: no single quotes, no
  empty attribute values (two of them would read as `""…""`), no `$`. `MedienleisteMarkupTest`
  guards all of this.

The queue — click a bar, the article's remaining media follow in document order — is built in the
browser from the DOM, not from a `json_script`. See `frontend.md`.

Forum messages deliberately keep the plain link: `Mitteilung.formatiert()` renders without a
`request`, and `internal_links` passes that through as `spieler=False`.

`abstimmung.js` binds the `{abstimmung:...}` directive to the `Abstimmung` model. The form is
`{abstimmung:<Titel>:<max>:<TT.MM.JJJJ>:<Option>;<Option>}` and the **end date is mandatory**:
without one a poll would never lock, so `ABSTIMMUNG_DIRECTIVE` does not match, `article_edit`
refuses to write the version and names the offending lines (`replacements.abstimmungen_ohne_ende`),
and a date that matches the pattern but is no calendar day (`31.02.2026`) leaves the line as
written. The editor snippet (two weeks out), its field hints and the cheat sheet in `artikel.html`
all show that form; the legacy import fills the date in for the old articles — `30.06.2026` for the
bulk, `31.12.2039` for the examples in „Hilfe:Wiki", both in `0003_import.py`.

The same markup vocabulary — plus the mail-only `{button:…}` directive — is re-implemented for
mail bodies in `mail_markup.py`; see `mail.md`.

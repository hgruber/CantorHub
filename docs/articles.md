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

The identity bar carries the `.ae-modus` switch „Bearbeiten | Vorschau“. `wiki-vorschau.js` posts
the unsaved textarea to `/intern/artikel/<name>/vorschau/` (`article_preview`), which returns
`apply_replacements()` of it and saves nothing; it checks the edit right like `article_edit` and
lives under the article's URL because a poll reads the article name from `resolver_match`. The
preview hides the textarea and the cheat-sheet; its content sits in an `inert` box, because it is
inside the editor form — a poll's own `<form>` is dropped by the parser there, and its button
would submit the article.

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
linked into several folders has several rows (see `files.md`). `[[Ordner:<id>|Name]]` links a
folder by its id; without `|Name` it shows the folder's name (one query). It only builds the link —
read access is decided by `folder_view`. Forum messages use the same markup, so both work there too.

Every line is HTML-escaped **before** any rule runs (the XSS fix of June 2026), and three rules
depend on that:

- **Emphasis matches the escaped quotes.** `'` arrives as `&#x27;` and `"` as `&quot;`, so the
  bold/italic patterns look for `(?:&#x27;){3}` and so on, non-greedy — until October 2026 they
  looked for the raw `'''` and no article showed bold or italic at all, and a greedy pattern
  would merge two emphases of one line into one.
- **List depth counts only the leading `*`/`#`.** `line.count("#")` used to count the `#` of
  every escaped `'` as well, which turned `# Bei '''X'''` into a fourth-level list.
- **Blocks (`%` note, `:` indent, `@` box) format their text inline** (links, emphasis) and
  close before any line that does not belong to them. They used to be emitted only when the next
  line of their own processor arrived, which put a box behind the following note or code block.

`WikiMarkupTest` and `WikiListenTest` pin all three.

### Placeholders

`{NAME}` in an article is replaced when the article is shown (`intern/wiki_platzhalter.py`) —
the address of the portal, the CalDAV/CardDAV/iCal URLs, the reader's username and XMPP
address, whether a service is switched on. Only the names in `BESCHREIBUNG` are replaced; any
other `Konfiguration` key would leak secrets such as `EMAIL_HOST_PASSWORD`, so everything else in
braces — `{abstimmung:…}`, unknown names — stays as written. Details:

- Only in the article view (`request` given); a forum message keeps the braces.
- Not on a line that starts with a space: that line is code and shows the placeholder raw, which
  is how „Hilfe:Wiki" documents them.
- The values are escaped and computed at most once per page, and only if a line contains a
  known name; a blank value renders as `(noch nicht eingerichtet)`.
- External links also accept `webcal://` (`[{WEBCAL_URL} Abonnieren]`).

### Help articles

`intern/hilfe/` ships the help pages every installation starts with: the overview `Hilfe` and
`Hilfe:…` pages for first steps, profile, events, forum, repertoire, members, files, the wiki
markup, and the four phone set-ups (CalDAV, iCal subscription, CardDAV, XMPP with Conversations
and Monal) that replaced the info boxes on the event and member lists, one per page of the
admin menu (`Hilfe:Aufgaben`, `Hilfe:Gruppen`, `Hilfe:Änderungsprotokoll`,
`Hilfe:Konfiguration`), plus three for operators:
running costs, backup/restore the browser-only way with screenshots (`Hilfe:Sicherung`) and
everything that needs a shell — commands, ports, clone — in `Hilfe:Sicherung im Detail`. Each
admin page links its article through the help icon at the right of the topbar: the view sets
`hilfe_seite` to the article name and `base.html` renders the icon. The texts are wiki markup
in `intern/hilfe/artikel/`, their images in `intern/hilfe/bilder/` — schematic drawings of the
phone screens (no freely licensed screenshots of the set-up steps exist) and cut-outs of the
portal itself and of Syncthing's web interface.

Every `Hilfe:…` page gets a navigation line at its top and bottom — previous page, overview,
next page in the order of `hilfe.ARTIKEL`. `hilfe.text()` adds it when the text is produced;
the files under `artikel/` do not carry it, so reordering or adding a page needs no edit
elsewhere.

The first-run setup creates them (`hilfe.anlegen()`), `manage.py hilfe_anlegen` adds them to an
existing installation. Neither overwrites: an existing article name and an existing image name
are skipped. `hilfe_anlegen --force` (`anlegen(erneuern=True)`) brings existing ones to the
shipped state: an article whose newest version differs gets the shipped text as its next
version — articles are immutable per version — and an image goes through
`dateiablage.systemablage_inhalt()`, which makes it a new revision unless its content is already
in the chain. The images land in Backstage/Wiki-Anhänge; edit rights go to Webmaster and Vorstand
only, reading stays open. `HilfeArtikelTest` checks that every image is used and present, every
placeholder known and every `[[Hilfe…]]` link resolvable.

### Embedded media

A `[[Datei:…]]` whose target `intern/medientypen.py` calls playable is rendered so that there is
**exactly one set of controls**:

- **Video** renders as a **media bar** instead of a link: the same `.mp-*` markup the floating
  mini-player uses, inline in the text, with a `<video>` without `controls` — the bar *is* the
  controls, and the mini-player stays hidden while it plays.
- **Audio** renders as a `<figure class="wiki-figure wiki-audio">` like any other file, with a
  note icon instead of a thumbnail (`_audiofigur()`) and a download icon next to the caption.
  Clicking the note opens the mini-player, which is the only control; without JavaScript it
  links to the file.

`|Label` overrides the title (and for audio the caption), which otherwise is the filename
without its extension (for audio the caption is the full filename). Everything else keeps the
old `<figure class="wiki-figure">`.

Two constraints on `_medienleiste()` come from `apply_replacements()` and are easy to break:

- The bar must be **phrasing content on a single line**. The `<p>` rule runs over the same line
  *after* this substitution, so a `<div>` would tear the paragraph open. It costs nothing
  visually, because every `.mp-*` rule sets its own `display`.
- The emphasis, quote and `$raw$` rules run afterwards too. So: no single quotes, no
  empty attribute values (two of them would read as `""…""`), no `$`. `MedienleisteMarkupTest`
  guards all of this.

The queue — click a bar or an audio icon, the article's remaining media follow in document
order — is built in the
browser from the DOM, not from a `json_script`. See `frontend.md`.

Forum messages deliberately keep the plain link: `Mitteilung.formatiert()` renders without a
`request`, and `internal_links` passes that through as `spieler=False`.

`abstimmung.js` binds the `{abstimmung:...}` directive to the `Abstimmung` model. The form is
`{abstimmung:<Titel>:<max>:<TT.MM.JJJJ>:<Option>;<Option>}` and the **end date is mandatory**:
without one a poll would never lock, so `ABSTIMMUNG_DIRECTIVE` does not match, `article_edit`
refuses to write the version and names the offending lines (`replacements.abstimmungen_ohne_ende`),
and a date that matches the pattern but is no calendar day (`31.02.2026`) leaves the line as
written. The editor snippet (two weeks out), its field hints and the cheat sheet in `artikel.html`
all show that form; the legacy import filled the date in for the old articles — `30.06.2026` for
the bulk, `31.12.2039` for the examples in „Hilfe:Wiki".

The same markup vocabulary — plus the mail-only `{button:…}` directive — is re-implemented for
mail bodies in `mail_markup.py`; see `mail.md`.

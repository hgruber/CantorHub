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

`fuzzy.py` provides the fuzzy song-title matching used when an article references a `Lied`.
`abstimmung.js` binds the `{abstimmung:...}` directive to the `Abstimmung` model.

The same markup vocabulary — plus the mail-only `{button:…}` directive — is re-implemented for
mail bodies in `mail_markup.py`; see `mail.md`.
